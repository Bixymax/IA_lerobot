"""Protocole TCP/IP de la zone d'échange (côté P-IA = serveur). Spécification : docs/protocole_tcp.md.

Messages JSON, un par ligne (UTF-8, terminés par \\n). P-Robo se connecte, P-IA arbitre le verrou.

Côté orchestrateur P-IA :
    srv = ServeurEchange(port=5050); srv.demarrer()
    if srv.zone.prendre_pia(timeout=30):       # verrou obtenu : P-Robo n'entre pas
        ...                                    # le bras dépose la pièce
        srv.zone.liberer_pia([{"id": 3, "forme": "triangle", "couleur": "rouge",
                               "x_mm": 40.0, "y_mm": 25.0}])   # inventaire à jour, P-Robo prévenu

Démo sans robot (simule P-IA) :  python echange_tcp.py --port 5050
"""
import argparse
import json
import socketserver
import threading
import time

VERSION = 1
LIBRE, PIA, PROBO = "FREE", "PIA", "PROBO"
FORMES = ("triangle", "etoile", "hexagone", "rond")


class ZoneEchange:
    """État partagé de la zone : qui détient le verrou, et quelles pièces conformes s'y trouvent.
    Règle de sécurité : jamais de reprise automatique du verrou (voir docs/protocole_tcp.md §5)."""

    def __init__(self):
        self.cond = threading.Condition()
        self.detenteur = LIBRE
        self.pieces = []
        self.clients = set()           # ConnexionEchange actives (pour les messages poussés)

    # ---- côté P-IA ----------------------------------------------------------
    def prendre_pia(self, timeout=0.0):
        """Prend le verrou pour P-IA ; attend au plus `timeout` s. True si obtenu."""
        fin = time.monotonic() + timeout
        with self.cond:
            while self.detenteur != LIBRE:
                reste = fin - time.monotonic()
                if reste <= 0:
                    return False
                self.cond.wait(reste)
            self.detenteur = PIA
        return True

    def liberer_pia(self, pieces=None):
        """P-IA a fini : met l'inventaire à jour (liste complète des pièces de la zone) et libère."""
        with self.cond:
            if self.detenteur != PIA:
                raise RuntimeError("P-IA ne détient pas le verrou")
            if pieces is not None:
                self.pieces = [dict(p) for p in pieces]
            self.detenteur = LIBRE
            self.cond.notify_all()
        self.diffuser({"type": "ZONE_UPDATE", "pieces": self.inventaire()})
        self.diffuser({"type": "LOCK_AVAILABLE"})

    def reinitialiser(self):
        """Action OPÉRATEUR après perte de liaison : remet le verrou à LIBRE (vérifier la zone à l'œil)."""
        with self.cond:
            self.detenteur = LIBRE
            self.cond.notify_all()

    # ---- commun ---------------------------------------------------------------
    def inventaire(self):
        with self.cond:
            return [dict(p) for p in self.pieces]

    def diffuser(self, msg):
        for c in list(self.clients):
            c.envoyer(msg)

    def demander_probo(self):
        with self.cond:
            if self.detenteur == LIBRE:
                self.detenteur = PROBO
                return True, None
            return False, self.detenteur

    def liberer_probo(self):
        with self.cond:
            if self.detenteur != PROBO:
                return False
            self.detenteur = LIBRE
            self.cond.notify_all()          # réveille l'orchestrateur P-IA (prendre_pia)
        return True

    def retirer(self, piece_id):
        with self.cond:
            avant = len(self.pieces)
            self.pieces = [p for p in self.pieces if p.get("id") != piece_id]
            return len(self.pieces) < avant


def traiter(zone, msg, role_connecte):
    """Réponse à un message client. `role_connecte` : True si HELLO déjà fait. Renvoie (réponse, nouvel_état_hello)."""
    t = msg.get("type")
    rep = {"v": VERSION, "re": msg.get("id")}
    if t == "HELLO":
        if msg.get("v") != VERSION:
            return {**rep, "type": "ERROR", "code": "VERSION", "msg": f"version {VERSION} attendue"}, False
        return {**rep, "type": "HELLO_ACK", "zone": zone.detenteur}, True
    if not role_connecte:
        return {**rep, "type": "ERROR", "code": "NO_HELLO", "msg": "HELLO d'abord"}, False
    if t == "PING":
        return {**rep, "type": "PONG"}, True
    if t == "LOCK_REQUEST":
        ok, par = zone.demander_probo()
        return ({**rep, "type": "LOCK_GRANTED"} if ok
                else {**rep, "type": "LOCK_DENIED", "holder": par.lower()}), True
    if t == "LOCK_RELEASE":
        if zone.liberer_probo():
            return {**rep, "type": "LOCK_RELEASED"}, True
        return {**rep, "type": "ERROR", "code": "NOT_HOLDER", "msg": "P-Robo ne détient pas le verrou"}, True
    if t == "GET_ZONE":
        return {**rep, "type": "ZONE", "stable": zone.detenteur != PIA, "holder": zone.detenteur,
                "pieces": zone.inventaire()}, True
    if t == "PIECE_TAKEN":
        if zone.detenteur != PROBO:
            return {**rep, "type": "ERROR", "code": "NOT_HOLDER", "msg": "verrou requis"}, True
        if not zone.retirer(msg.get("piece_id")):
            return {**rep, "type": "ERROR", "code": "UNKNOWN_PIECE", "msg": "pièce inconnue"}, True
        return {**rep, "type": "TAKEN_ACK", "piece_id": msg["piece_id"]}, True
    return {**rep, "type": "ERROR", "code": "BAD_TYPE", "msg": f"type inconnu : {t}"}, True


class ConnexionEchange(socketserver.StreamRequestHandler):
    def setup(self):
        super().setup()
        self.ecriture = threading.Lock()

    def envoyer(self, msg):
        try:
            with self.ecriture:
                self.wfile.write((json.dumps({"v": VERSION, **msg}, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
        except OSError:
            pass

    def handle(self):
        zone = self.server.zone
        zone.clients.add(self)
        hello = False
        try:
            for ligne in self.rfile:
                try:
                    msg = json.loads(ligne.decode())
                    assert isinstance(msg, dict)
                except (ValueError, AssertionError):
                    self.envoyer({"type": "ERROR", "code": "BAD_JSON", "msg": "JSON attendu, un objet par ligne"})
                    continue
                rep, hello = traiter(zone, msg, hello)
                self.envoyer(rep)
        except OSError:
            pass
        finally:
            zone.clients.discard(self)
            # Liaison perdue : si P-Robo détenait le verrou, il le GARDE (zone considérée occupée)
            # jusqu'à une libération explicite ou une réinitialisation par l'opérateur.
            if zone.detenteur == PROBO:
                print("[echange] liaison perdue pendant que P-Robo détient le verrou : zone OCCUPÉE, "
                      "intervention opérateur requise")


class ServeurEchange(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host="0.0.0.0", port=5050, zone=None):
        super().__init__((host, port), ConnexionEchange)
        self.zone = zone or ZoneEchange()

    def demarrer(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


def main():
    ap = argparse.ArgumentParser(description="Serveur d'échange P-IA (démo : P-IA simulé)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5050)
    a = ap.parse_args()
    srv = ServeurEchange(a.host, a.port).demarrer()
    print(f"[echange] écoute sur {a.host}:{a.port}. Commandes : d = déposer un triangle (simulé), r = réinitialiser, q = quitter")
    n = 0
    while True:
        c = input().strip().lower()
        if c == "q":
            break
        if c == "r":
            srv.zone.reinitialiser()
            print("[echange] verrou remis à FREE")
        if c == "d":
            if srv.zone.prendre_pia(timeout=5):
                n += 1
                srv.zone.liberer_pia(srv.zone.inventaire() + [
                    {"id": n, "forme": "triangle", "couleur": "rouge", "x_mm": 10.0 * n, "y_mm": 20.0}])
                print("[echange] pièce simulée déposée")
            else:
                print("[echange] zone occupée")


if __name__ == "__main__":
    main()
