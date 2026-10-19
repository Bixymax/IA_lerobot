"""
flux_masque.py - caméras virtuelles masquées pour LeRobot (téléopération, enregistrement, inférence).

Lit les vraies caméras, efface les pièces non ciblées (masquage.py) et publie le résultat sur des
caméras virtuelles v4l2loopback (/dev/video10, 11, 12...). lerobot-teleoperate et lerobot-record
lisent ces caméras virtuelles comme des webcams : rien à modifier dans LeRobot, seuls les index
changent. Le robot voit ainsi exactement les mêmes images à l'enregistrement et à l'inférence.

Prérequis (une fois par démarrage du PC pour modprobe) : voir docs/flux_masque.md
    sudo modprobe v4l2loopback devices=3 video_nr=10,11,12 \\
        card_label="side_masque,top_masque,angle45_masque" exclusive_caps=1
    pip install pyvirtualcam

Lancement (index des vraies caméras à vérifier à chaque installation) :
    python flux_masque.py --cams side=2 top=4 angle45=6 --sorties side=10 top=11 angle45=12 \\
                          --forme triangle

Commandes pendant le flux (taper la lettre puis Entrée dans ce terminal, ou dans la fenêtre
d'aperçu avec --apercu) :
    t = triangle, r = rond, h = hexagone, e = étoile   -> seule cette forme reste visible
    a = aucune (toutes les pièces effacées)
    b = brut (flux sans masquage, pour comparer)       m = revenir au masquage
    q = quitter
"""
import argparse
import sys
import threading
import time

import cv2
import numpy as np

from masquage import (FPS, HAUTEUR, LARGEUR, Masqueur, appliquer_reglages_dossier,
                      choisir_cible, ouvrir_camera, parse_cams, stderr_silencieux)

FORMES = {"t": "triangle", "r": "rond", "h": "hexagone", "e": "etoile"}


# --------------------------------------------------------------------------- #
# Sortie vers une caméra virtuelle
# --------------------------------------------------------------------------- #
class SortieVirtuelle:
    """Caméra virtuelle v4l2loopback alimentée en images BGR (via pyvirtualcam)."""

    def __init__(self, index, largeur=LARGEUR, hauteur=HAUTEUR, fps=FPS):
        try:
            import pyvirtualcam
        except ImportError as e:
            raise SystemExit("pyvirtualcam manquant : pip install pyvirtualcam") from e
        device = f"/dev/video{index}"
        try:
            self.cam = pyvirtualcam.Camera(largeur, hauteur, fps, device=device,
                                           fmt=pyvirtualcam.PixelFormat.BGR)
        except Exception as e:  # noqa: BLE001 - message clair pour l'utilisateur
            raise SystemExit(
                f"Impossible d'ouvrir la caméra virtuelle {device} : {e}\n"
                f"Le module v4l2loopback est-il chargé ? (voir docs/flux_masque.md, "
                f"`sudo modprobe v4l2loopback ...`)") from e

    def envoyer(self, image_bgr):
        self.cam.send(image_bgr)

    def fermer(self):
        self.cam.close()


# --------------------------------------------------------------------------- #
# Stabilisation des détections dans le temps
# --------------------------------------------------------------------------- #
class Suivi:
    """Relie les détections d'une exécution à l'autre pour éviter les clignotements.

    Sans mémoire, une pièce ratée UNE fois par le détecteur (reflet, ombre du bras, seuil de
    teinte) réapparaît pendant 0,2 s, et une pièce dont la forme est devinée tantôt « étoile »
    tantôt « rond » est tour à tour montrée et effacée. Ici :
      - une pièce non revue reste effacée pendant `oublier` détections ;
      - sa forme est le vote majoritaire des `memoire` dernières détections ;
      - chaque pièce garde un identifiant (sert à ne pas changer de cible en cours de route).
    """

    def __init__(self, oublier=4, memoire=5, distance=30.0):
        self.oublier = oublier
        self.memoire = memoire
        self.distance = distance
        self.pistes = []
        self._prochain = 0

    @staticmethod
    def _centre(b):
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def maj(self, detections):
        paires = []
        for i, p in enumerate(self.pistes):
            cp = self._centre(p["boite"])
            for j, d in enumerate(detections):
                cd = self._centre(d["boite"])
                dist = float(np.hypot(cp[0] - cd[0], cp[1] - cd[1]))
                if dist <= self.distance:
                    paires.append((dist, i, j))
        pris_p, pris_d = set(), set()
        for dist, i, j in sorted(paires):
            if i in pris_p or j in pris_d:
                continue
            pris_p.add(i)
            pris_d.add(j)
            p, d = self.pistes[i], detections[j]
            p["boite"], p["conforme"], p["conf"], p["rates"] = d["boite"], d["conforme"], d.get("conf", 1.0), 0
            p["teinte"] = d.get("teinte")
            p["formes"] = (p["formes"] + [d["forme"]])[-self.memoire:]
        for i, p in enumerate(self.pistes):
            if i not in pris_p:
                p["rates"] += 1
        for j, d in enumerate(detections):
            if j not in pris_d:
                self.pistes.append({"id": self._prochain, "boite": d["boite"],
                                    "conforme": d["conforme"], "conf": d.get("conf", 1.0),
                                    "formes": [d["forme"]], "rates": 0, "teinte": d.get("teinte")})
                self._prochain += 1
        self.pistes = [p for p in self.pistes if p["rates"] <= self.oublier]
        return [{"id": p["id"], "boite": p["boite"], "conforme": p["conforme"], "conf": p["conf"],
                 "teinte": p["teinte"], "forme": max(set(p["formes"]), key=p["formes"].count)}
                for p in self.pistes]


# --------------------------------------------------------------------------- #
# Flux masqué
# --------------------------------------------------------------------------- #
class FluxMasque:
    """Masquage en continu de plusieurs caméras.

    Utilisable depuis un autre programme (futur orchestrateur relié à P-Robo) :
        flux = FluxMasque(masqueur, cams, sorties, forme="triangle"); flux.demarrer()
        flux.choisir_forme("etoile")   # changement à chaud
        flux.arreter()

    La détection des pièces (lente) n'est refaite que `detection_hz` fois par seconde ; entre
    deux détections, les boîtes précédentes servent à l'effacement (rapide), fait sur chaque image.
    """

    def __init__(self, masqueur, cams, sorties, forme="triangle", detection_hz=5.0,
                 ouvrir=ouvrir_camera, creer_sortie=SortieVirtuelle, horloge=time.monotonic):
        manquants = [nom for nom, _ in cams if nom not in masqueur.fonds]
        if manquants:
            raise SystemExit(f"Pas de fond pour : {', '.join(manquants)} "
                             f"(lancez d'abord : python masquage.py capture ...)")
        sans_sortie = [nom for nom, _ in cams if nom not in sorties]
        if sans_sortie:
            raise SystemExit(f"Pas de caméra virtuelle pour : {', '.join(sans_sortie)} (--sorties)")
        self.masqueur = masqueur
        self.cams = cams
        self.sorties = sorties
        self.periode_detection = 1.0 / detection_hz if detection_hz > 0 else 0.0
        self.ouvrir = ouvrir
        self.creer_sortie = creer_sortie
        self.horloge = horloge
        self.diagnostic = False                 # True : affiche dans le terminal ce que voit le détecteur
        self.verrou = threading.Lock()
        self._forme = forme
        self._brut = False
        self._stop = threading.Event()
        self._fils = []
        # état par caméra : dernières détections, date de la dernière détection, dernière image
        self.etat = {nom: {"detections": [], "t_det": -1e9, "image": None, "cible": None,
                           "cible_id": None, "suivi": Suivi(), "n": 0, "ms": 0.0}
                     for nom, _ in cams}

    # ---- commandes (thread-safe) -------------------------------------------
    def choisir_forme(self, forme):
        with self.verrou:
            self._forme = forme
            for e in self.etat.values():
                e["t_det"] = -1e9          # nouvelle forme : on redétecte tout de suite
        print(f"[flux] forme visible : {forme or 'aucune'}")

    def mode_brut(self, actif):
        with self.verrou:
            self._brut = actif
        print(f"[flux] {'flux BRUT (sans masquage)' if actif else 'masquage actif'}")

    @property
    def forme(self):
        with self.verrou:
            return self._forme

    @property
    def brut(self):
        with self.verrou:
            return self._brut

    # ---- traitement d'une image (testable sans matériel) -------------------
    def traiter(self, nom, frame):
        """Renvoie l'image à publier pour la caméra `nom`."""
        e = self.etat[nom]
        if self.brut:
            e["cible"] = None
            return frame
        maintenant = self.horloge()
        if maintenant - e["t_det"] >= self.periode_detection:
            e["detections"] = e["suivi"].maj(self.masqueur.detecter(nom, frame))
            e["t_det"] = maintenant
            if self.diagnostic:
                sig = [(d["forme"], round(d["teinte"] or 0), d["boite"]) for d in e["detections"]]
                if [x[:2] for x in sig] != e.get("sig"):
                    e["sig"] = [x[:2] for x in sig]
                    print(f"[diag] {nom} : " + (", ".join(f"{f} h={h}" for f, h, _ in sig) or "aucune pièce"))
        forme = self.forme
        dets = e["detections"]
        cible = None
        if forme is not None:
            # on garde la même cible tant qu'elle reste valable (pas de saut entre 2 pièces
            # identiques d'une détection à l'autre)
            cible = next((d for d in dets if d["id"] == e["cible_id"]
                          and d["forme"] == forme and d["conforme"]), None)
            if cible is None:
                cible, _ = choisir_cible(dets, forme)
        e["cible_id"] = cible["id"] if cible else None
        non_cibles = [d["boite"] for d in dets if d is not cible]
        e["cible"] = cible
        protegees = [cible["boite"]] if cible else None
        return self.masqueur.effacer(nom, frame, non_cibles, boites_protegees=protegees)

    # ---- boucle par caméra --------------------------------------------------
    def _boucle(self, nom, cap, sortie):
        echecs = 0
        derniere = None
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    echecs += 1
                    if echecs % 30 == 0:
                        print(f"[flux] {nom} : {echecs} lectures ratées (câble / USB ?)")
                    if derniere is not None:
                        sortie.envoyer(derniere)    # garde le flux vivant pour LeRobot
                    time.sleep(0.01)
                    continue
                echecs = 0
                if frame.shape[1] != LARGEUR or frame.shape[0] != HAUTEUR:
                    frame = cv2.resize(frame, (LARGEUR, HAUTEUR))
                t0 = time.perf_counter()
                image = self.traiter(nom, frame)
                e = self.etat[nom]
                e["ms"] = 0.9 * e["ms"] + 0.1 * (time.perf_counter() - t0) * 1000
                e["n"] += 1
                e["image"] = image
                derniere = image
                sortie.envoyer(image)
        except Exception as e:  # noqa: BLE001 - stderr peut être masqué : on affiche sur stdout
            print(f"[flux] {nom} : arrêt sur erreur {e!r}")
        finally:
            cap.release()
            sortie.fermer()

    def demarrer(self):
        """Ouvre toutes les caméras et sorties AVANT de lancer les fils : une erreur (caméra
        absente, v4l2loopback non chargé) arrête tout de suite avec un message clair."""
        ouverts, caps = [], []
        try:
            for nom, index in self.cams:
                cap = self.ouvrir(index)
                caps.append(cap)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # image la plus récente : moins de latence
                except Exception:  # noqa: BLE001 - réglage facultatif
                    pass
                ouverts.append((nom, cap, self.creer_sortie(self.sorties[nom])))
        except BaseException:
            for cap in caps:
                cap.release()
            for _, _, sortie in ouverts:
                sortie.fermer()
            raise
        for nom, cap, sortie in ouverts:
            f = threading.Thread(target=self._boucle, args=(nom, cap, sortie), name=f"flux-{nom}",
                                 daemon=True)
            f.start()
            self._fils.append(f)

    def arreter(self):
        self._stop.set()
        for f in self._fils:
            f.join(timeout=2)

    def vivant(self):
        return any(f.is_alive() for f in self._fils)


# --------------------------------------------------------------------------- #
# Interface en ligne de commande
# --------------------------------------------------------------------------- #
def appliquer_commande(flux, cmd):
    """Applique une commande clavier ; renvoie False pour quitter."""
    cmd = cmd.strip().lower()[:1]
    if cmd == "q":
        return False
    if cmd in FORMES:
        flux.choisir_forme(FORMES[cmd])
    elif cmd == "a":
        flux.choisir_forme(None)
    elif cmd == "b":
        flux.mode_brut(True)
    elif cmd == "m":
        flux.mode_brut(False)
    elif cmd:
        print("[flux] commandes : t r h e (forme), a (aucune), b (brut), m (masque), q (quitter)")
    return True


def _lire_terminal(flux, stop):
    for ligne in sys.stdin:
        if not appliquer_commande(flux, ligne):
            stop.set()
            return


def _apercu(flux, echelle, diagnostic=False):
    colonnes = []
    for nom, _ in flux.cams:
        e = flux.etat[nom]
        img = e["image"] if e["image"] is not None else np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
        img = img.copy()
        if diagnostic and not flux.brut:
            # boîtes de ce que le détecteur a vu : vert = cible (montrée), orange = effacée
            for d in e["detections"]:
                x1, y1, x2, y2 = d["boite"]
                cible = e["cible"] is not None and d["id"] == e["cible"]["id"]
                couleur = (0, 200, 0) if cible else (0, 140, 255)
                cv2.rectangle(img, (x1, y1), (x2, y2), couleur, 1)
                h = d.get("teinte")
                cv2.putText(img, f"{d['forme']} h={h:.0f}" if h is not None else d["forme"],
                            (x1, max(y1 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, couleur, 1)
        etat = "BRUT" if flux.brut else f"forme: {flux.forme or 'aucune'}"
        if not flux.brut and flux.forme and e["cible"] is None:
            etat += " INDISPONIBLE"
        cv2.putText(img, f"{nom} | {etat} | {e['ms']:.0f} ms", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        colonnes.append(img)
    grille = np.hstack(colonnes)
    if echelle != 1.0:
        grille = cv2.resize(grille, None, fx=echelle, fy=echelle, interpolation=cv2.INTER_AREA)
    cv2.imshow("flux masque (ce que voit le robot)", grille)
    touche = cv2.waitKey(30) & 0xFF
    return appliquer_commande(flux, chr(touche)) if touche != 255 else True


def main(args):
    cams = parse_cams(args.cams)
    sorties = dict(parse_cams(args.sorties))
    collisions = {i for _, i in cams} & set(sorties.values())
    if collisions:
        raise SystemExit(f"Index utilisé à la fois en entrée et en sortie : {sorted(collisions)}")
    appliquer_reglages_dossier(args.fonds, dict(cams))
    masqueur = Masqueur.charger(args.fonds)
    forme = None if args.forme == "aucune" else args.forme
    flux = FluxMasque(masqueur, cams, sorties, forme=forme, detection_hz=args.detection_hz)
    flux.diagnostic = args.diagnostic
    if args.sans_masquage:
        flux.mode_brut(True)
    flux.demarrer()
    print("[flux] caméras virtuelles : "
          + ", ".join(f"{nom} -> /dev/video{sorties[nom]}" for nom, _ in cams))
    print("[flux] dans LeRobot : index_or_path = l'index virtuel, SANS fourcc. "
          "Commandes : t r h e a b m q (+ Entrée).")
    stop = threading.Event()
    threading.Thread(target=_lire_terminal, args=(flux, stop), daemon=True).start()
    dernier_bilan = time.monotonic()
    try:
        while not stop.is_set() and flux.vivant():
            if args.apercu:
                if not _apercu(flux, args.echelle, args.diagnostic):
                    break
            else:
                time.sleep(0.1)
            if time.monotonic() - dernier_bilan > 10:
                dernier_bilan = time.monotonic()
                print("[flux] " + " | ".join(
                    f"{nom}: {flux.etat[nom]['n'] / 10:.0f} img/s, {flux.etat[nom]['ms']:.0f} ms"
                    for nom, _ in cams))
                for nom, _ in cams:
                    flux.etat[nom]["n"] = 0
    except KeyboardInterrupt:
        pass
    finally:
        flux.arreter()
        if args.apercu:
            cv2.destroyAllWindows()
    if not flux.vivant() and not stop.is_set():
        print("[flux] un flux caméra s'est arrêté (voir l'erreur ci-dessus).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cams", nargs="+", required=True,
                    help="VRAIES caméras, nom=index (ex. side=2 top=4 angle45=6)")
    ap.add_argument("--sorties", nargs="+", default=["side=10", "top=11", "angle45=12"],
                    help="caméras VIRTUELLES, nom=index (défaut : side=10 top=11 angle45=12)")
    ap.add_argument("--fonds", default="fonds/")
    ap.add_argument("--forme", default="triangle",
                    choices=list(FORMES.values()) + ["aucune"])
    ap.add_argument("--detection-hz", type=float, default=5.0,
                    help="détections par seconde (l'effacement, lui, est fait sur chaque image)")
    ap.add_argument("--sans-masquage", action="store_true",
                    help="démarrer en flux brut (touche m pour activer le masquage)")
    ap.add_argument("--apercu", action="store_true", help="fenêtre d'aperçu (Rerun suffit en général)")
    ap.add_argument("--diagnostic", action="store_true",
                    help="affiche les pièces détectées (forme, teinte h) dans le terminal et, avec --apercu, les encadre ; "
                         "orange = effacée, vert = montrée")
    ap.add_argument("--echelle", type=float, default=0.6)
    ap.add_argument("--verbeux", action="store_true", help="afficher les messages du décodeur JPEG")
    a = ap.parse_args()
    if a.verbeux:
        main(a)
    else:
        with stderr_silencieux():
            main(a)
