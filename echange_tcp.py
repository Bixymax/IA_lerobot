"""Liaison TCP avec P-Robo (Stäubli) : nous sommes le SERVEUR. Spécification : docs/protocole_tcp.md.

Trames texte ASCII, champs séparés par des virgules, terminées par « @ » (jamais de retour à la
ligne ajouté) :
    robot -> vision : GET-Query,Forme@   ACK-Done,Forme@   ACK-NotDone,Forme@
    vision -> robot : GET-Respond,Forme,X,Y,RZ@   GET-Respond,Forme,NONE@   ACK-End@

Il n'y a pas de message de verrou : le Stäubli a le droit d'entrer dans la zone d'échange entre
l'envoi des coordonnées et son ACK. Règle d'or : au moindre doute, on ne débloque rien.

États (classe Echange) :
    BLOQUE       le SO-101 ne bouge pas, aucune coordonnée envoyée ; sortie : l'opérateur confirme
                 que le Stäubli est hors de la zone (au démarrage, liaison perdue, incohérence)
    LIBRE        aucune demande ; le SO-101 peut travailler
    PREPARATION  forme demandée ; le SO-101 la dépose, puis on mesure et on répond
    STAUBLI      coordonnées envoyées ; le SO-101 reste immobile jusqu'à l'ACK

Essai sans caméra ni bras, avec des coordonnées FIXES (remplace Hercules) :
    python echange_tcp.py --port 5000
"""
import argparse
import math
import socket
import socketserver
import threading
import time
from collections import Counter, deque

# Nom utilisé par le robot -> nom utilisé par la vision (conformite.py)
FORMES_ROBOT = {"Etoile": "etoile", "Cercle": "rond", "Triangle": "triangle",
                "Hexagone": "hexagone"}
NOMS_ROBOT = {v: k for k, v in FORMES_ROBOT.items()}

GET_QUERY, GET_RESPOND = "GET-Query", "GET-Respond"
ACK_DONE, ACK_NOTDONE, ACK_END = "ACK-Done", "ACK-NotDone", "ACK-End"
TYPES_RECUS = (GET_QUERY, ACK_DONE, ACK_NOTDONE)

FIN = b"@"
TAILLE_MAX = 128          # au-delà sans « @ », ce n'est pas une trame
ESSAIS_MAX = 3            # prises ratées (ACK-NotDone) avant d'alerter l'opérateur

BLOQUE, LIBRE, PREPARATION, STAUBLI = "BLOQUE", "LIBRE", "PREPARATION", "STAUBLI"
PORT = 5000


# --------------------------------------------------------------------------- #
# Trames
# --------------------------------------------------------------------------- #
class TrameInvalide(ValueError):
    pass


def decoder(texte):
    """Trame reçue (sans le @) -> (type, forme au nom du robot). Aucune tolérance sur
    l'orthographe : message douteux = rien ne se passe."""
    champs = texte.split(",")
    if champs[0] not in TYPES_RECUS:
        raise TrameInvalide(f"type inconnu : {champs[0]!r}")
    if len(champs) != 2:
        raise TrameInvalide(f"{champs[0]} attend 2 champs, reçu {len(champs)}")
    if champs[1] not in FORMES_ROBOT:
        raise TrameInvalide(f"forme inconnue : {champs[1]!r}")
    return champs[0], champs[1]


def encoder(*champs):
    return ",".join(champs).encode("ascii") + FIN


def nombre(v):
    """Nombre au format attendu par toNum() : point décimal, une décimale, jamais « -0.0 »."""
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(f"coordonnée non finie : {v}")
    return f"{round(v, 1) + 0.0:.1f}"


class Decoupeur:
    """Reconstitue les trames à partir des paquets TCP (coupés ou collés)."""

    def __init__(self):
        self.tampon = b""

    def ajouter(self, octets):
        """Renvoie la liste des trames complètes (texte sans le @, sans espaces ni retours à la
        ligne autour : nc et certains terminaux en ajoutent)."""
        self.tampon += octets
        *completes, self.tampon = self.tampon.split(FIN)
        trames = [t.decode("ascii", "replace").strip(" \t\r\n\x00") for t in completes]
        if len(self.tampon) > TAILLE_MAX:
            trames.append(self.tampon[:40].decode("ascii", "replace") + "... (trop longue)")
            self.tampon = b""
        return trames


# --------------------------------------------------------------------------- #
# Déroulement du dialogue
# --------------------------------------------------------------------------- #
class Echange:
    """État du dialogue avec le Stäubli, sans réseau (testable seul). Utilisable depuis plusieurs
    fils. L'orchestrateur lit photo(), puis répond par envoyer_coordonnees() ou envoyer_none() en
    rappelant le `numero` de la demande : une réponse à une demande périmée est refusée."""

    def __init__(self, confirmer_au_demarrage=True):
        self.verrou = threading.RLock()
        self.etat = LIBRE
        self.forme = None          # nom robot de la demande en cours (PREPARATION, STAUBLI)
        self.numero = 0            # +1 à chaque nouvelle demande
        self.raison = ""           # pourquoi on est BLOQUE
        self.echecs = Counter()    # ACK-NotDone consécutifs par forme
        self._jeton = 0
        self._emettre = None       # fonction(octets) -> bool de la connexion active
        self._attente = None       # message reçu pendant un blocage : (type, forme)
        self._zone_forme = None    # forme dont le Stäubli avait la zone quand on s'est bloqué
        self._ack_tolere = None    # un ACK de cette forme peut encore recevoir ACK-End
        self._evenements = deque(maxlen=200)
        if confirmer_au_demarrage:
            self._bloquer("démarrage : vérifiez que le Stäubli est hors de la zone")

    # ---- consultation -----------------------------------------------------
    def photo(self):
        with self.verrou:
            return {"etat": self.etat, "forme": self.forme, "numero": self.numero,
                    "raison": self.raison, "connecte": self._emettre is not None,
                    "mouvement_autorise": self.etat in (LIBRE, PREPARATION)}

    def lire_evenements(self):
        with self.verrou:
            ev = list(self._evenements)
            self._evenements.clear()
        return ev

    def _noter(self, message):
        self._evenements.append(f"{time.strftime('%H:%M:%S')} {message}")

    # ---- connexion ---------------------------------------------------------
    def connexion(self, emettre):
        """Nouvelle connexion (remplace l'ancienne). Renvoie son jeton."""
        with self.verrou:
            if self._emettre is not None:
                self._perdre_liaison("remplacée par une nouvelle connexion")
            self._jeton += 1
            self._emettre = emettre
            self._noter("robot connecté")
            return self._jeton

    def deconnexion(self, jeton):
        with self.verrou:
            if jeton == self._jeton and self._emettre is not None:
                self._perdre_liaison("fermée")

    def _perdre_liaison(self, cause):
        self._emettre = None
        self._attente = None
        self._ack_tolere = None
        self._noter(f"liaison {cause}")
        if self.etat == STAUBLI:
            self._zone_forme = self.forme
            self._bloquer("liaison perdue pendant que le Stäubli a la zone")
        elif self.etat == PREPARATION:
            self._noter(f"demande {self.forme} annulée : finir le geste en cours, bras au repos")
            self._liberer()

    # ---- états ---------------------------------------------------------------
    def _bloquer(self, raison):
        self.etat, self.raison = BLOQUE, raison
        self._noter(f"BLOQUE : {raison}")

    def _liberer(self):
        self.etat, self.forme, self.raison = LIBRE, None, ""

    def _preparer(self, forme):
        self.etat, self.forme, self.raison = PREPARATION, forme, ""
        self.numero += 1
        self._ack_tolere = None
        self._noter(f"demande n°{self.numero} : {forme}")
        if self.echecs[forme] >= ESSAIS_MAX:
            self._noter(f"ALERTE : {self.echecs[forme]} prises ratées de suite pour {forme} : "
                        f"vérifiez la pièce (x = répondre NONE)")

    def _transmettre(self, *champs):
        trame = encoder(*champs)
        ok = self._emettre is not None and self._emettre(trame)
        self._noter(f"{'envoyé' if ok else 'ÉCHEC d envoi'} : {trame.decode()}")
        return bool(ok)

    def _clore(self, type_ack, forme):
        """ACK accepté : le Stäubli est sorti, on confirme."""
        self.echecs[forme] = self.echecs[forme] + 1 if type_ack == ACK_NOTDONE else 0
        self._transmettre(ACK_END)
        self._zone_forme = None
        self._liberer()

    # ---- messages du robot ---------------------------------------------------
    def recevoir(self, jeton, texte):
        with self.verrou:
            if jeton != self._jeton or self._emettre is None:
                return
            self._noter(f"reçu : {texte}@")
            try:
                type_msg, forme = decoder(texte)
            except TrameInvalide as e:
                self._noter(f"ALERTE trame ignorée ({e})")
                return
            if self.etat == BLOQUE:
                self._attente = (type_msg, forme)
                self._noter("mis en attente : confirmation de l'opérateur requise (o)")
            elif type_msg == GET_QUERY:
                if self.etat == STAUBLI:
                    self._zone_forme = self.forme
                    self._attente = (type_msg, forme)
                    self._bloquer("nouvelle demande alors que le Stäubli n'a pas envoyé son ACK")
                elif self.etat == PREPARATION and forme == self.forme:
                    self._noter("demande répétée, déjà en préparation")
                else:
                    if self.etat == PREPARATION:
                        self._noter(f"la demande {self.forme} est remplacée par {forme}")
                    self._preparer(forme)
            elif self.etat == STAUBLI:
                if forme == self.forme:
                    self._clore(type_msg, forme)
                else:
                    self._zone_forme = self.forme
                    self._attente = (type_msg, forme)
                    self._bloquer(f"ACK pour {forme} alors que la zone a été donnée pour {self.forme}")
            elif self.etat == LIBRE and forme == self._ack_tolere:
                # après un NONE ou un déblocage : ACK-End ne donne accès à rien
                self._ack_tolere = None
                self._transmettre(ACK_END)
            else:
                self._noter(f"ALERTE {type_msg} inattendu (zone non donnée) : pas de réponse")

    # ---- réponses de la cellule ----------------------------------------------
    def envoyer_coordonnees(self, numero, x, y, rz):
        """Donne la zone au Stäubli. False si la demande n'est plus d'actualité."""
        champs = (nombre(x), nombre(y), nombre(rz))
        with self.verrou:
            if self.etat != PREPARATION or numero != self.numero or self._emettre is None:
                self._noter("coordonnées non envoyées : demande périmée ou robot déconnecté")
                return False
            # l'état change AVANT l'envoi : dès que le robot peut les lire, la zone est à lui
            self.etat = STAUBLI
            if not self._transmettre(GET_RESPOND, self.forme, *champs):
                self._zone_forme = self.forme
                self._bloquer("envoi des coordonnées incertain : vérifiez le Stäubli")
                return False
            return True

    def envoyer_none(self, numero):
        with self.verrou:
            if self.etat != PREPARATION or numero != self.numero or self._emettre is None:
                return False
            forme = self.forme
            ok = self._transmettre(GET_RESPOND, forme, "NONE")
            self._liberer()
            self._ack_tolere = forme
            return ok

    def confirmer_zone_libre(self):
        """Action OPÉRATEUR : « j'ai vérifié, le Stäubli est hors de la zone »."""
        with self.verrou:
            if self.etat != BLOQUE:
                return False
            attente, self._attente = self._attente, None
            zone, self._zone_forme = self._zone_forme, None
            self._noter("opérateur : zone libre")
            self._liberer()
            if attente is None:
                self._ack_tolere = zone
            elif attente[0] == GET_QUERY:
                self._preparer(attente[1])
            else:
                self._clore(*attente)
            return True


# --------------------------------------------------------------------------- #
# Réseau
# --------------------------------------------------------------------------- #
class _Connexion(socketserver.BaseRequestHandler):
    def handle(self):
        sock, echange = self.request, self.server.echange
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)     # comme côté robot
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)     # câble débranché : ~11 s
        for option, valeur in (("TCP_KEEPIDLE", 5), ("TCP_KEEPINTVL", 2), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, option):
                sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, option), valeur)

        def emettre(octets):
            try:
                sock.sendall(octets)
                return True
            except OSError:
                return False

        jeton = self.server.remplacer(sock, emettre)
        decoupeur = Decoupeur()
        try:
            while donnees := sock.recv(1024):
                for trame in decoupeur.ajouter(donnees):
                    echange.recevoir(jeton, trame)
        except OSError:
            pass
        finally:
            echange.deconnexion(jeton)


class ServeurEchange(socketserver.ThreadingTCPServer):
    """Un seul robot à la fois : une nouvelle connexion ferme l'ancienne."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host="0.0.0.0", port=PORT, echange=None):
        super().__init__((host, port), _Connexion)
        self.echange = echange or Echange()
        self._verrou_client = threading.Lock()
        self._client = None

    def remplacer(self, sock, emettre):
        with self._verrou_client:
            ancien, self._client = self._client, sock
            jeton = self.echange.connexion(emettre)
        self._fermer(ancien)
        return jeton

    @staticmethod
    def _fermer(sock):
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def demarrer(self):
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.1},
                         daemon=True).start()
        return self

    def arreter(self):
        self.shutdown()
        self._fermer(self._client)
        self.server_close()


# --------------------------------------------------------------------------- #
# Essai à coordonnées fixes
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Serveur d'essai à coordonnées FIXES (sans caméra)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    srv = ServeurEchange(a.host, a.port).demarrer()
    print(f"[echange] écoute sur {a.host}:{a.port}\n"
          "[ATTENTION] essai de COMMUNICATION : les coordonnées sont fictives, le Stäubli ne doit "
          "pas exécuter le mouvement.\n"
          "Commandes (+ Entrée) : o = zone libre, v [x y rz] = envoyer des coordonnées "
          "(défaut 130.5 46.2 30), x = NONE, e = état, q = quitter")
    fin = threading.Event()

    def afficher():
        while not fin.is_set():
            for ligne in srv.echange.lire_evenements():
                print(f"[echange] {ligne}")
            time.sleep(0.1)

    threading.Thread(target=afficher, daemon=True).start()
    try:
        while True:
            mots = input().split()
            if not mots:
                continue
            cmd, numero = mots[0].lower(), srv.echange.photo()["numero"]
            if cmd == "q":
                break
            if cmd == "o":
                srv.echange.confirmer_zone_libre()
            elif cmd == "x":
                srv.echange.envoyer_none(numero)
            elif cmd == "v":
                try:
                    x, y, rz = map(float, mots[1:4]) if len(mots) > 1 else (130.5, 46.2, 30.0)
                    srv.echange.envoyer_coordonnees(numero, x, y, rz)
                except ValueError:
                    print("usage : v 130.5 46.2 30")
            elif cmd == "e":
                print(srv.echange.photo())
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        fin.set()
        srv.arreter()


if __name__ == "__main__":
    main()
