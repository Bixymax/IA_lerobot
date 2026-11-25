"""
cellule.py - essai en DEUX ÉTAPES : communication avec le Stäubli, flux masqué et mesure, le
modèle étant lancé à la main.

  1. Le Stäubli demande une forme (GET-Query) : le flux masqué montre une pièce conforme de cette
     forme.
  2. Terminal 2, bras AU REPOS : ./scripts/rollout_echange.sh  (le bras revient au repos à la fin).
  3. Quand le bras est au repos : touche v. La pièce est mesurée dans la zone d'échange avec `top`
     et les coordonnées sont envoyées (GET-Respond). Le SO-101 ne doit plus bouger.
  4. ACK du Stäubli : la cellule répond ACK-End et redevient libre.

Lancement (remplace flux_masque.py, qui ne doit pas tourner en même temps) :
    source local.env
    python cellule.py --cams side=$SIDE top=$TOP angle45=$ANGLE45

Touches (dans la fenêtre d'aperçu, ou lettre + Entrée dans ce terminal) :
    o = j'ai vérifié : le Stäubli est hors de la zone (au démarrage ou après un blocage)
    v = le bras est au repos, la pièce est posée : mesurer et envoyer
    n = nouvelle cible (second essai)        x = répondre NONE (pas de pièce)
    q = quitter

La cellule NE COMMANDE PAS le SO-101 : elle refuse d'envoyer des coordonnées tant qu'un programme
LeRobot tourne, et alerte s'il en démarre un pendant que le Stäubli a la zone.
"""
import argparse
import os
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from calibration import Calibration, charger_points
from conformite import FORMES, References, _texte
from echange_tcp import (BLOQUE, FORMES_ROBOT, LIBRE, NOMS_ROBOT, PORT, PREPARATION, STAUBLI,
                         ServeurEchange)
from flux_masque import FluxMasque
from masquage import (HAUTEUR, LARGEUR, Masqueur, appliquer_reglages_dossier, parse_cams,
                      stderr_silencieux)
from mesure_echange import (SYMETRIE, Releve, RepereEchange, VisionEchange, correspond,
                            orientation)
from selection import Selection

PROGRAMMES_BRAS = {"lerobot-rollout", "lerobot-record", "lerobot-teleoperate", "lerobot-replay",
                   "lerobot-calibrate"}
ESSAIS_DEPOT = 2          # essais de dépôt avant d'alerter l'opérateur
_A_REFAIRE = object()     # la cible du flux doit être (re)choisie


def processus_bras(racine="/proc"):
    """Programmes LeRobot en cours (ceux qui peuvent faire bouger le SO-101)."""
    trouves = set()
    for fichier in Path(racine).glob("[0-9]*/cmdline"):
        try:
            args = fichier.read_bytes().decode("utf-8", "replace").split("\0")
        except OSError:
            continue
        candidats = [os.path.basename(args[0])]
        if candidats[0].startswith("python"):
            candidats += [os.path.basename(a) for a in args[1:4]]
        for nom in candidats:
            if nom.startswith("lerobot.scripts."):          # python -m lerobot.scripts.lerobot_...
                nom = nom.rsplit(".", 1)[1].replace("_", "-")
            if nom in PROGRAMMES_BRAS:
                trouves.add(nom)
    return sorted(trouves)


class Cellule:
    """Enchaîne demande, cible du flux, validation de l'opérateur, mesure et réponse. Sans
    fenêtre ni caméra propre : tick() est appelé en boucle (testable sans matériel).

    flux   : FluxMasque (choisir_forme, nouvelle_cible, image_brute, selection)
    vision : mesure_echange.VisionEchange"""

    def __init__(self, echange, flux, vision, processus=processus_bras, horloge=time.monotonic,
                 delai_none=5.0, n_mesures=8, intervalle_mesure=0.1, duree_releve=6.0,
                 periode_observation=0.33, seuil_encombrement=0.02):
        self.echange, self.flux, self.vision = echange, flux, vision
        self.processus, self.horloge = processus, horloge
        self.delai_none, self.n_mesures = delai_none, n_mesures
        self.intervalle_mesure, self.duree_releve = intervalle_mesure, duree_releve
        self.periode_observation = periode_observation
        self.seuil = seuil_encombrement
        self.observation = None        # dernière observation de la zone (aperçu)
        self.dernier_envoi = None      # (forme, x, y, rz)
        self.message = ""              # résultat de la dernière action
        self.alerte = ""
        self._messages = deque(maxlen=100)
        self._numero = 0
        self._forme_flux = None
        self._t_cible = 0.0
        self._releve = None
        self._seq = 0
        self._t_image = -1e9
        self._t_observation = -1e9
        self._procs, self._t_procs = [], -1e9
        self._nouvelle_demande()

    def _nouvelle_demande(self):
        self._essais = 0
        self._releve = None
        self._cible_vue = False        # une cible a été trouvée : plus de NONE automatique
        self._zone_examinee = False
        self.deja_dans_zone = False
        self.message = ""

    def _dire(self, message):
        self.message = message
        self._messages.append(message)

    def lire_messages(self):
        ev = list(self._messages)
        self._messages.clear()
        return ev

    def _processus(self, maintenant_obligatoire=False):
        t = self.horloge()
        if maintenant_obligatoire or t - self._t_procs >= 0.5:
            self._procs, self._t_procs = self.processus(), t
        return self._procs

    @property
    def mesure_en_cours(self):
        return self._releve is not None

    # ---- actions de l'opérateur ---------------------------------------------
    def touche(self, t):
        photo = self.echange.photo()
        if t == "o":
            if not self.echange.confirmer_zone_libre():
                self._dire("o : rien à confirmer, la cellule n'est pas bloquée")
            return
        if t not in ("v", "x", "n"):
            return
        if photo["etat"] != PREPARATION or photo["numero"] != self._numero:
            self._dire(f"{t} : aucune demande en préparation")
            return
        if t == "x":
            self._releve = None
            if self.echange.envoyer_none(self._numero):
                self._dire("NONE envoyé")
        elif t == "n":
            self._releve = None
            self.flux.nouvelle_cible()
            self._dire("nouvelle cible : vérifiez l'aperçu, puis relancez le modèle")
        elif self._releve is None:
            procs = self._processus(True)
            if procs:
                self._dire(f"REFUSÉ : {', '.join(procs)} tourne encore. Attendre la fin (bras au "
                           f"repos), puis v")
                return
            self._releve = Releve(FORMES_ROBOT[photo["forme"]], n=self.n_mesures,
                                  seuil_encombrement=self.seuil)
            self._debut_releve = self.horloge()
            self._t_mesure = -1e9
            # seules les images prises APRÈS la touche comptent
            self._seq = self.flux.image_brute(self.vision.camera)[0]
            self._dire("mesure en cours...")

    # ---- boucle ----------------------------------------------------------------
    def tick(self):
        photo = self.echange.photo()
        etat, t = photo["etat"], self.horloge()
        procs = self._processus()
        if etat == PREPARATION and photo["numero"] != self._numero:
            self._numero = photo["numero"]
            self._nouvelle_demande()
            self._forme_flux = _A_REFAIRE
            self._dire(f"demande {photo['forme']} : lancer ./scripts/rollout_echange.sh, puis v")
        if etat != PREPARATION:
            self._releve = None
        voulue = FORMES_ROBOT[photo["forme"]] if etat == PREPARATION else None
        # on ne change pas les images pendant que le modèle les regarde
        if voulue != self._forme_flux and not procs:
            self.flux.choisir_forme(voulue)
            self._forme_flux, self._t_cible = voulue, t

        alerte = ""
        if procs and not photo["mouvement_autorise"]:
            alerte = (f"ARRÊTEZ LE SO-101 : {', '.join(procs)} tourne alors que "
                      + ("le Stäubli a la zone" if etat == STAUBLI else "la cellule est bloquée"))
        if alerte and alerte != self.alerte:
            self._messages.append(alerte)
        self.alerte = alerte

        seq, image = self.flux.image_brute(self.vision.camera)
        nouvelle = seq != self._seq
        if nouvelle:
            self._seq, self._t_image = seq, t

        if self._releve is not None:
            self._mesurer(nouvelle, image, t, procs)
        elif nouvelle and t - self._t_observation >= self.periode_observation:
            self._observer(image, t)
            if etat == PREPARATION:
                self._examiner(voulue, t, procs)

    def _observer(self, image, t):
        self.observation = self.vision.observer(image)
        self._t_observation = t

    def _examiner(self, forme, t, procs):
        """Pendant la préparation : pièce déjà dans la zone ? aucune pièce disponible (NONE) ?"""
        obs = self.observation
        presente = any(correspond(p, forme) for p in obs.pieces)
        if not self._zone_examinee and obs.encombrement <= self.seuil:
            self._zone_examinee = True
            if presente:
                self.deja_dans_zone = self._cible_vue = True
                self._dire(f"{NOMS_ROBOT[forme]} déjà dans la zone : NE PAS lancer le modèle, "
                           f"bras au repos puis v")
        if self._forme_flux != forme or self._cible_vue:
            return
        if self.flux.selection.verrouille:
            self._cible_vue = True
        elif (self.delai_none > 0 and t - self._t_cible >= self.delai_none and not procs
              and self._zone_examinee and obs.encombrement <= self.seuil and not presente):
            vues = ", ".join(f"{p['forme']} {p['couleur']}" + ("" if p["conforme"] else " (défaut)")
                             for p in self.flux.selection.inventaire()) or "aucune pièce"
            if self.echange.envoyer_none(self._numero):
                self._dire(f"NONE envoyé : pas de {NOMS_ROBOT[forme]} conforme disponible "
                           f"(vu : {vues})")

    def _mesurer(self, nouvelle, image, t, procs):
        if procs:
            self._releve = None
            self._dire(f"mesure abandonnée : {', '.join(procs)} vient de démarrer")
        elif nouvelle and t - self._t_mesure >= self.intervalle_mesure:
            self._t_mesure = t
            self._observer(image, t)
            self._releve.ajouter(self.observation)
            if self._releve.complet:
                self._conclure()
        elif t - self._debut_releve > self.duree_releve:
            self._releve = None
            self._dire("mesure abandonnée : pas assez d'images (caméra top figée ?)")

    def _conclure(self):
        releve, self._releve = self._releve, None
        r = releve.resultat()
        if r.ok:
            procs = self._processus(True)
            if procs:
                self._dire(f"REFUSÉ : {', '.join(procs)} tourne encore")
            elif self.echange.envoyer_coordonnees(self._numero, r.x, r.y, r.rz):
                self.dernier_envoi = (NOMS_ROBOT[releve.forme], r.x, r.y, r.rz)
                self._dire(f"envoyé : {NOMS_ROBOT[releve.forme]} X={r.x:.1f} Y={r.y:.1f} "
                           f"RZ={r.rz:.1f}" + "".join(f" [{m}]" for m in r.remarques))
        elif r.absente:
            self._essais += 1
            if self._essais < ESSAIS_DEPOT:
                self._dire(f"{r.raison}. Second essai : n (nouvelle cible), relancer le modèle, v")
            else:
                self._dire(f"ALERTE : {self._essais} essais ratés, rien n'est envoyé. {r.raison}. "
                           f"Vérifier la zone puis v, ou x = NONE")
        else:
            self._dire(f"mesure refusée : {r.raison}. Corriger puis v")

    # ---- texte de l'aperçu ----------------------------------------------------
    def consigne(self):
        photo = self.echange.photo()
        etat = photo["etat"]
        if etat == BLOQUE:
            return f"{photo['raison']}. Taper o si le Stäubli est hors de la zone"
        if etat == STAUBLI:
            return f"Le Stäubli a la zone ({photo['forme']}) : NE PAS BOUGER LE SO-101"
        if etat == LIBRE:
            return "En attente d'une demande" if photo["connecte"] else "Robot non connecté"
        if self.mesure_en_cours:
            return "Mesure en cours : ne rien toucher"
        if self._procs:
            return "Modèle en cours : attendre la fin (bras au repos), puis v"
        if self.deja_dans_zone:
            return f"{photo['forme']} déjà dans la zone : bras au repos, taper v"
        return f"Demande {photo['forme']} : lancer le modèle, puis v quand le bras est au repos"


# --------------------------------------------------------------------------- #
# Aperçu
# --------------------------------------------------------------------------- #
COULEURS_ETAT = {BLOQUE: (0, 0, 255), STAUBLI: (0, 0, 255), PREPARATION: (0, 165, 255),
                 LIBRE: (0, 200, 0)}


def dessiner_zone(image, vision, observation):
    """Sur une image BRUTE de `top` : zone d'échange, axes de fEchange et pièces mesurées."""
    img = image.copy()
    calib, repere, cam = vision.calib, vision.repere, vision.camera
    taille = (img.shape[1], img.shape[0])

    def px(points_table):
        return np.round(calib.vers_image(cam, points_table, taille)).astype(int)

    cv2.polylines(img, [px(repere.coins_table()).reshape(-1, 1, 2)], True, (255, 160, 0), 2)
    for bout, nom, couleur in (((40, 0), "X", (0, 0, 255)), ((0, 40), "Y", (0, 160, 0))):
        o, b = px(repere.vers_table([(0, 0), bout]))
        cv2.arrowedLine(img, o.tolist(), b.tolist(), couleur, 2, tipLength=0.2)
        _texte(img, nom, (b[0] + 4, b[1]), couleur)
    if observation is None:
        return img
    for p in observation.pieces:
        c = px([p["table"]])[0]
        cv2.drawMarker(img, c.tolist(), (0, 0, 0), cv2.MARKER_CROSS, 10, 1)
        nom = NOMS_ROBOT.get(p["forme"], p["forme"])
        rz = orientation(p["forme"], p["points"])
        if p["forme"] in SYMETRIE:
            a = np.radians(rz + 90)
            bout = p["table"] + 28 * (np.cos(a) * repere.ex + np.sin(a) * repere.ey)
            cv2.arrowedLine(img, c.tolist(), px([bout])[0].tolist(), (0, 0, 0), 2, tipLength=0.25)
        _texte(img, f"{nom} X={p['x']:.1f} Y={p['y']:.1f} RZ={rz:.0f}",
               (c[0] - 110, c[1] + 40), (255, 160, 0))
    _texte(img, f"zone encombree : {observation.encombrement:.1%}", (8, img.shape[0] - 8),
           (255, 160, 0))
    return img


def composer(flux, cellule, evenements, echelle=0.7):
    """Image de l'aperçu : bandeau d'état, caméras masquées (ce que voit le modèle) et vue `top`
    brute avec la zone d'échange."""
    vide = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
    vues = []
    for nom, _ in flux.cams:
        image = flux.etat[nom]["image"]
        img = vide.copy() if image is None else image.copy()
        _texte(img, f"{nom} (vu par le modele)", (8, 22), (255, 255, 255), 0.6)
        vues.append(img)
    brute = flux.image_brute(cellule.vision.camera)[1]
    img = vide.copy() if brute is None else dessiner_zone(brute, cellule.vision,
                                                          cellule.observation)
    _texte(img, "top brute : zone d'echange", (8, 22), (255, 160, 0), 0.6)
    vues.append(img)
    vues += [vide] * (len(vues) % 2)
    grille = np.vstack([np.hstack(vues[i:i + 2]) for i in range(0, len(vues), 2)])
    grille = cv2.resize(grille, None, fx=echelle, fy=echelle, interpolation=cv2.INTER_AREA)

    photo = cellule.echange.photo()
    couleur = COULEURS_ETAT[photo["etat"]]
    bandeau = np.zeros((170, grille.shape[1], 3), np.uint8)
    cv2.rectangle(bandeau, (0, 0), (bandeau.shape[1], 8), couleur, -1)
    titre = {STAUBLI: "STAUBLI DANS LA ZONE", PREPARATION: f"DEMANDE {photo['forme']}",
             LIBRE: "LIBRE", BLOQUE: "BLOQUE"}[photo["etat"]]
    _texte(bandeau, titre, (10, 34), couleur, 0.8)
    _texte(bandeau, cellule.consigne(), (10, 60), couleur, 0.55)
    _texte(bandeau, cellule.alerte or cellule.message, (10, 84),
           (0, 0, 255) if cellule.alerte else (90, 90, 90), 0.45)
    for i, ligne in enumerate(list(evenements)[-3:]):
        _texte(bandeau, ligne, (10, 106 + 18 * i), (60, 60, 60), 0.4)
    _texte(bandeau, "o = zone libre | v = mesurer et envoyer | n = nouvelle cible | x = NONE | "
                    "q = quitter", (10, 164), (60, 60, 60), 0.4)
    return np.vstack([bandeau, grille])


# --------------------------------------------------------------------------- #
def main(args):
    cams = parse_cams(args.cams)
    sorties = dict(parse_cams(args.sorties))
    if args.camera_ref not in dict(cams):
        raise SystemExit(f"La caméra '{args.camera_ref}' (vue de dessus) doit être dans --cams")
    collisions = {i for _, i in cams} & set(sorties.values())
    if collisions:
        raise SystemExit(f"Index utilisé à la fois en entrée et en sortie : {sorted(collisions)}")
    appliquer_reglages_dossier(args.fonds, dict(cams))
    masqueur = Masqueur.charger(args.fonds)
    calib = Calibration.charger(args.fonds)
    refs = References.charger(args.fonds)
    try:
        repere = RepereEchange.depuis_points(charger_points(args.fonds)["points"])
        vision = VisionEchange(masqueur, calib, refs, repere, args.camera_ref,
                               args.hauteur_camera, args.epaisseur)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    print(f"[cellule] zone d'échange : {repere.largeur:.0f} x {repere.hauteur:.0f} mm")
    if args.hauteur_camera is None:
        print("[ATTENTION] pas de correction de hauteur (--hauteur-camera et --epaisseur) : "
              "positions décalées de quelques mm")
    manquantes = [f for f in FORMES if refs.modele(f) is None]
    if manquantes:
        print(f"[ATTENTION] formes non apprises : {', '.join(manquantes)} (conformite.py apprendre)")
    selection = Selection(masqueur, calib, refs, camera_ref=args.camera_ref)
    flux = FluxMasque(masqueur, cams, sorties, forme=None, detection_hz=args.detection_hz,
                      selection=selection, asynchrone=True)
    try:
        serveur = ServeurEchange(args.host, args.port)
    except OSError as e:
        raise SystemExit(f"Port {args.port} indisponible ({e}) : un autre serveur tourne ?") from e
    try:
        flux.demarrer()
    except BaseException:
        serveur.server_close()
        raise
    serveur.demarrer()
    cellule = Cellule(serveur.echange, flux, vision, delai_none=args.delai_none,
                      seuil_encombrement=args.seuil_encombrement)
    print(f"[cellule] serveur TCP sur {args.host}:{args.port} | caméras virtuelles : "
          + ", ".join(f"{nom} -> /dev/video{sorties[nom]}" for nom, _ in cams))
    print("[cellule] touches (+ Entrée) : o v n x q")

    touches = queue.Queue()

    def lire_terminal():
        for ligne in sys.stdin:
            touches.put(ligne.strip().lower()[:1])

    threading.Thread(target=lire_terminal, daemon=True).start()
    evenements = deque(maxlen=3)
    quitter_demande, t_rendu, flux_mort = -1e9, 0.0, False
    try:
        while True:
            while not touches.empty():
                t = touches.get()
                if t == "q":
                    if (serveur.echange.photo()["etat"] == STAUBLI
                            and time.monotonic() - quitter_demande > 5):
                        quitter_demande = time.monotonic()
                        print("[cellule] le Stäubli a la zone : retaper q pour quitter quand même")
                        continue
                    return
                cellule.touche(t)
            cellule.tick()
            for ligne in serveur.echange.lire_evenements():
                evenements.append(ligne)
                print(f"[echange] {ligne}")
            for ligne in cellule.lire_messages():
                print(f"[cellule] {ligne}")
            for ligne in selection.lire_evenements():
                print(f"[flux] {ligne}")
            if not flux_mort and not all(f.is_alive() for f in flux._fils):
                flux_mort = True
                print("[ALERTE] un flux caméra s'est arrêté (voir l'erreur ci-dessus) : relancer "
                      "la cellule quand le Stäubli est hors de la zone")
            if args.sans_apercu:
                time.sleep(0.03)
                continue
            if time.monotonic() - t_rendu >= 0.1:        # 10 img/s : le flux garde le processeur
                t_rendu = time.monotonic()
                cv2.imshow("cellule P-IA", composer(flux, cellule, evenements, args.echelle))
            t = cv2.waitKey(30) & 0xFF
            if t != 255:
                touches.put(chr(t).lower())
    except KeyboardInterrupt:
        pass
    finally:
        serveur.arreter()
        flux.arreter()
        if not args.sans_apercu:
            cv2.destroyAllWindows()


def analyseur():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cams", nargs="+", required=True,
                    help="VRAIES caméras, nom=index (ex. side=2 top=4 angle45=6)")
    ap.add_argument("--sorties", nargs="+", default=["side=10", "top=11", "angle45=12"])
    ap.add_argument("--fonds", default="fonds/")
    ap.add_argument("--camera-ref", default="top")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--detection-hz", type=float, default=3.0)
    ap.add_argument("--delai-none", type=float, default=5.0,
                    help="secondes sans pièce disponible avant d'envoyer NONE (0 = jamais, touche x)")
    ap.add_argument("--seuil-encombrement", type=float, default=0.02,
                    help="part de la zone d'échange pouvant différer du fond (bras au-dessus ?)")
    ap.add_argument("--hauteur-camera", type=float, help="mm, de la table à l'objectif de top")
    ap.add_argument("--epaisseur", type=float, help="mm, épaisseur des pièces")
    ap.add_argument("--echelle", type=float, default=0.7, help="taille de l'aperçu")
    ap.add_argument("--sans-apercu", action="store_true")
    ap.add_argument("--verbeux", action="store_true", help="messages du décodeur JPEG")
    return ap


if __name__ == "__main__":
    a = analyseur().parse_args()
    if a.verbeux:
        main(a)
    else:
        with stderr_silencieux():
            main(a)
