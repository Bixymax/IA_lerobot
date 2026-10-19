"""
masquage.py - réglage des caméras, fond de référence (table vide) et effacement des pièces non ciblées.

Les caméras sont identifiées par un NOM (le même que dans LeRobot : side, top, angle45) et un
index /dev/videoN, écrits  nom=index. Les fonds et réglages sont rangés par NOM : si les index
changent d'une installation à l'autre, seul l'argument --cams change, pas les fichiers.

Usage (adaptez les index à l'installation du jour : voir `v4l2-ctl --list-devices`) :
  0) Régler exposition et balance des blancs (une fois, éclairage définitif) :
       python vision/masquage.py reglages --cams side=4 top=2 angle45=0 --out fonds/
     -> 's' pour sauvegarder dans fonds/reglages.json, 'q' pour sauvegarder et quitter
  1) Table vide, bras en position de repos, même éclairage :
       python vision/masquage.py capture --cams side=4 top=2 angle45=0 --out fonds/
  2) Contrôler le masquage en direct (efface TOUTES les pièces) :
       python vision/masquage.py voir --cams side=4 top=2 angle45=0 --fonds fonds/
  3) Dans vos scripts d'enregistrement ET d'inférence, AVANT d'ouvrir les caméras :
       indices = {"side": 4, "top": 2, "angle45": 0}
       appliquer_reglages_dossier("fonds/", indices)
       masqueur = Masqueur.charger("fonds/")
       # frames LeRobot = RGB  ->  entree_rgb=True
       image = masqueur.effacer("top", frame, non_cibles, boites_protegees=[cible["boite"]],
                                entree_rgb=True)
  Ancien format (fond_cam0.png, reglages.json par index) -> migration unique :
       python vision/masquage.py migrer --out fonds/ --cams side=4 top=2 angle45=0

Les mêmes réglages doivent servir pour la capture du fond, l'enregistrement des épisodes
et l'inférence, sinon le fond de référence ne correspond plus aux images.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np


@contextmanager
def stderr_silencieux():
    """Masque ce que le code C (libjpeg/OpenCV) écrit sur stderr, par exemple
    'Corrupt JPEG data: 2 extraneous bytes before marker 0xd6'. Ces messages sont des
    avertissements du décodeur MJPG : l'image est décodée quand même.
    Les erreurs Python (traceback) restent visibles : elles s'affichent après la sortie du bloc.
    Utilisable dans vos propres scripts : `with stderr_silencieux(): ...`"""
    sys.stderr.flush()
    sauve = os.dup(2)
    poubelle = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(poubelle, 2)
        yield
    finally:
        os.dup2(sauve, 2)
        os.close(sauve)
        os.close(poubelle)

# Pièces vives (saturées) ; sert aux diagnostics de capture.
HSV_BAS = (0, 90, 70)
HSV_HAUT = (180, 255, 255)

# Effacement par différence avec le fond (voir Masqueur._masque_pieces) :
SEUIL_DIFF = 22   # écart max (sur 255) entre l'image et le fond pour dire "ça a changé"
SEUIL_CHROMA = 15  # écart de couleur (Lab) mini avec la table pour qu'un pixel "change de couleur" :
                   # un ensemble changé n'est effacé que s'il contient de tels pixels (= une pièce)

# Détecteur PROVISOIRE (avant YOLO) : forme déduite de la teinte H (OpenCV : 0-179, rouge = 0 ou 179).
# A VÉRIFIER sur vos pièces avec `python vision/detection.py ...`, qui affiche la teinte mesurée (h=..).
TEINTES = [("triangle", 0, 10), ("triangle", 165, 179),    # rouge
           ("rond", 11, 22),                                # orange
           ("hexagone", 23, 38),                            # jaune
           ("etoile", 39, 90)]                              # vert


def forme_par_teinte(h):
    for forme, bas, haut in TEINTES:
        if bas <= h <= haut:
            return forme
    return "inconnue"


REGLAGES_FICHIER = "reglages.json"

# Mêmes paramètres que dans votre commande lerobot-record
LARGEUR, HAUTEUR, FPS, FOURCC = 640, 480, 30, "MJPG"


# --------------------------------------------------------------------------- #
# Noms de caméras
# --------------------------------------------------------------------------- #
def parse_cams(tokens):
    """['side=4', 'top=2'] -> [('side', 4), ('top', 2)].  Un index seul ('4') sert de nom."""
    cams = []
    for t in tokens:
        nom, sep, idx = t.partition("=")
        if not sep:
            nom, idx = t, t
        if not idx.isdigit():
            raise SystemExit(f"Caméra '{t}' invalide : utilisez nom=index (ex. top=2)")
        if any(nom == n for n, _ in cams):
            raise SystemExit(f"Nom de caméra en double : {nom}")
        cams.append((nom, int(idx)))
    return cams


# --------------------------------------------------------------------------- #
# Réglages des caméras (v4l2)
# --------------------------------------------------------------------------- #
def _v4l2(index, *args):
    return subprocess.run(["v4l2-ctl", "-d", f"/dev/video{index}", *args],
                          capture_output=True, text=True)


def lister_controles(index):
    """{nom_du_contrôle: {"min": .., "max": .., "default": .., "value": ..}} via v4l2-ctl."""
    sortie = _v4l2(index, "--list-ctrls").stdout
    res = {}
    for ligne in sortie.splitlines():
        m = re.match(r"\s*(\w+)\s+0x[0-9a-fA-F]+\s+\(\w+\)\s*:\s*(.*)", ligne)
        if m:
            nom, reste = m.groups()
            res[nom] = {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", reste)}
    return res


def appliquer_reglages(index, reglage):
    """reglage = {"exposition": int|None, "balance": int|None}.
    None = on ne touche pas à ce paramètre (la caméra reste en automatique)."""
    ctrls = lister_controles(index)

    def regler(nom, val):
        r = _v4l2(index, "--set-ctrl", f"{nom}={val}")
        if r.returncode != 0:
            print(f"[v4l2] caméra {index} : {nom}={val} refusé ({r.stderr.strip()})")

    if reglage.get("exposition") is not None:
        regler("auto_exposure", 1)                       # 1 = mode manuel
        if "exposure_dynamic_framerate" in ctrls:
            regler("exposure_dynamic_framerate", 0)      # sinon l'exposition varie d'elle-même
        regler("exposure_time_absolute", reglage["exposition"])
    if reglage.get("balance") is not None:
        for nom in ("white_balance_automatic", "white_balance_temperature_auto"):
            if nom in ctrls:
                regler(nom, 0)
        regler("white_balance_temperature", reglage["balance"])


def appliquer_reglages_dossier(dossier, indices=None):
    """Applique reglages.json aux caméras. `indices` = {"side": 4, "top": 2, ...} (index du jour).
    Sans `indices`, les clés du fichier sont supposées être des index (ancien format).
    A appeler avant l'enregistrement et l'inférence. Renvoie le dict des réglages."""
    fichier = Path(dossier) / REGLAGES_FICHIER
    if not fichier.exists():
        return {}
    reglages = json.loads(fichier.read_text())
    for nom, reglage in reglages.items():
        if indices is not None:
            if nom in indices:
                appliquer_reglages(indices[nom], reglage)
        elif nom.isdigit():
            appliquer_reglages(int(nom), reglage)
    return reglages


def commande_reglages(args):
    cams = parse_cams(args.cams)
    indices = dict(cams)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fichier = out / REGLAGES_FICHIER
    existants = json.loads(fichier.read_text()) if fichier.exists() else {}

    caps, bornes, derniers = {}, {}, {}
    for nom, i in cams:
        ctrls = lister_controles(i)
        if "exposure_time_absolute" not in ctrls:
            print(f"[ATTENTION] caméra {nom} (/dev/video{i}) : contrôle exposure_time_absolute "
                  f"introuvable (vérifiez `v4l2-ctl -d /dev/video{i} --list-ctrls`)")
        e = ctrls.get("exposure_time_absolute", {})
        b = ctrls.get("white_balance_temperature", {})
        emin, emax = e.get("min", 3), e.get("max", 2047)
        bmin, bmax = b.get("min", 2800), b.get("max", 6500)
        pre = existants.get(nom, {})
        e0 = min(max(pre.get("exposition", e.get("default", 150)), emin), emax)
        b0 = min(max(pre.get("balance", b.get("default", 4600)), bmin), bmax)

        win = f"cam {nom}"
        cv2.namedWindow(win)
        cv2.createTrackbar("exposition", win, e0 - emin, emax - emin, lambda v: None)
        cv2.createTrackbar("balance K", win, b0 - bmin, bmax - bmin, lambda v: None)
        bornes[nom] = (emin, bmin)
        derniers[nom] = None
        caps[nom] = ouvrir_camera(i)

    def sauvegarder():
        data = dict(existants)   # garde les caméras non réglées cette fois-ci
        data.update({nom: {"exposition": d[0], "balance": d[1]} for nom, d in derniers.items() if d})
        fichier.write_text(json.dumps(data, indent=2))
        print(f"Réglages sauvegardés -> {fichier.resolve()} : {data}")

    print("Réglez chaque fenêtre : image nette, table claire mais NON saturée, blanc neutre "
          "(pas de dominante jaune/verte/bleue).\n"
          "IMPORTANT : cliquez d'abord sur une fenêtre d'image (pas sur le terminal), puis "
          "'s' = sauvegarder, 'q' = sauvegarder et quitter.")
    try:
        _boucle_reglages(caps, bornes, derniers, indices, sauvegarder)
    except KeyboardInterrupt:
        pass
    sauvegarder()   # sauvegarde finale, même si on quitte avec Ctrl+C
    for cap in caps.values():
        cap.release()
    cv2.destroyAllWindows()


def _boucle_reglages(caps, bornes, derniers, indices, sauvegarder):
    while True:
        for nom, cap in caps.items():
            win = f"cam {nom}"
            emin, bmin = bornes[nom]
            e = cv2.getTrackbarPos("exposition", win) + emin
            b = cv2.getTrackbarPos("balance K", win) + bmin
            if derniers[nom] != (e, b):
                appliquer_reglages(indices[nom], {"exposition": e, "balance": b})
                derniers[nom] = (e, b)
            ok, frame = cap.read()
            if ok:
                # Carré central (à placer sur du papier blanc) : viser B ≈ G ≈ R et max < 240
                h, w = frame.shape[:2]
                x1, y1, x2, y2 = int(w * 0.45), int(h * 0.45), int(w * 0.55), int(h * 0.55)
                bgr = frame[y1:y2, x1:x2].reshape(-1, 3).mean(axis=0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 1)
                cv2.putText(frame, f"carre central B={bgr[0]:.0f} G={bgr[1]:.0f} R={bgr[2]:.0f}",
                            (10, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                cv2.putText(frame, f"{nom}  expo={e}  balance={b}K", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.putText(frame, "s = sauver   q = sauver + quitter", (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                cv2.imshow(win, frame)
        touche = cv2.waitKey(30) & 0xFF
        if touche == ord("s"):
            sauvegarder()
        elif touche == ord("q"):
            return


# --------------------------------------------------------------------------- #
# Caméras
# --------------------------------------------------------------------------- #
def ouvrir_camera(index, largeur=LARGEUR, hauteur=HAUTEUR, fps=FPS, fourcc=FOURCC):
    """Ouvre la caméra avec les mêmes paramètres que lerobot-record (MJPG, 640x480, 30 fps)."""
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, largeur)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, hauteur)
    cap.set(cv2.CAP_PROP_FPS, fps)
    if not cap.isOpened():
        raise RuntimeError(f"Caméra {index} introuvable")
    return cap


def masque_couleur(frame_bgr):
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, HSV_BAS, HSV_HAUT)


def pixels_colores(frame_bgr, fond_bgr):
    """Pixels PLUS colorés que la table au même endroit, et de couleur différente (espace Lab).
    Une pièce colorée y répond ; le bras noir ou blanc et ses bords flous jamais (leur couleur
    est moins vive que celle de la table), même si la table elle-même est un peu teintée."""
    f = cv2.cvtColor(cv2.GaussianBlur(frame_bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    g = cv2.cvtColor(cv2.GaussianBlur(fond_bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    af, bf = f[..., 1] - 128, f[..., 2] - 128
    ag, bg = g[..., 1] - 128, g[..., 2] - 128
    plus_vif = np.hypot(af, bf) > np.hypot(ag, bg) + SEUIL_CHROMA / 2
    autre_teinte = np.hypot(af - ag, bf - bg) > SEUIL_CHROMA
    return ((plus_vif & autre_teinte).astype(np.uint8)) * 255


def diagnostic(frame_bgr):
    """(luminosité moyenne 0-255, part de pixels saturés >= 250)."""
    gris = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(gris.mean()), float((gris >= 250).mean())


# --------------------------------------------------------------------------- #
# Capture du fond
# --------------------------------------------------------------------------- #
def capturer_fond(index, n_images=30, ignorer=15, essais_max=300, minimum=10):
    """Médiane de n_images valides : élimine le bruit capteur et un éventuel passage rapide.
    Les lectures ratées (images MJPG corrompues par des erreurs USB) sont ignorées et on
    réessaie, jusqu'à `essais_max` lectures. Renvoie (fond, nb_images_valides, nb_echecs)."""
    cap = ouvrir_camera(index)
    for _ in range(ignorer):          # laisse le capteur se stabiliser
        cap.read()
    images, echecs = [], 0
    for _ in range(essais_max):
        ok, frame = cap.read()
        if ok and frame is not None:
            images.append(frame)
            if len(images) >= n_images:
                break
        else:
            echecs += 1
            time.sleep(0.01)
    cap.release()
    if len(images) < minimum:
        raise RuntimeError(f"seulement {len(images)} images valides sur {len(images) + echecs} "
                           f"lectures (erreurs USB probables)")
    return np.median(np.stack(images), axis=0).astype(np.uint8), len(images), echecs


def commande_capture(args):
    cams = parse_cams(args.cams)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    reglages = appliquer_reglages_dossier(out, dict(cams))
    if not reglages:
        print("[ATTENTION] pas de reglages.json : les caméras restent en automatique, donc le fond "
              "peut ne pas correspondre aux images prises plus tard. Lancez d'abord la commande "
              "'reglages'.")
    echecs_cameras = []
    for nom, idx in cams:
        if nom not in reglages:
            print(f"[ATTENTION] caméra {nom} : aucun réglage enregistré (reste en automatique).")
        try:
            fond, n_ok, n_ko = capturer_fond(idx)
        except RuntimeError as e:
            print(f"[ERREUR] caméra {nom} (/dev/video{idx}) : {e}. Fond NON enregistré.")
            echecs_cameras.append(nom)
            continue
        if n_ko:
            print(f"[ATTENTION] caméra {nom} : {n_ko} lectures ratées pour {n_ok} images valides "
                  f"(erreurs USB : voir `dmesg`, ports et câbles).")
        lum, sature = diagnostic(fond)
        print(f"Caméra {nom} : luminosité moyenne {lum:.0f}/255, pixels saturés {sature:.1%}")
        if sature > 0.03 or lum > 225:
            print(f"[ATTENTION] caméra {nom} : image surexposée, les détails sont perdus. "
                  f"Baissez l'exposition (commande 'reglages') et refaites la capture.")
        elif lum < 60:
            print(f"[ATTENTION] caméra {nom} : image trop sombre. Augmentez l'exposition.")
        part = float((masque_couleur(fond) > 0).mean())
        if part > 0.002:
            print(f"[INFO] caméra {nom} : {part:.2%} de pixels colorés dans le fond. Normal si la "
                  f"caméra voit le décor (fenêtre, objets colorés). Sinon : pièce oubliée sur la "
                  f"table, ou dominante de couleur (balance des blancs).")
        cv2.imwrite(str(out / f"fond_{nom}.png"), fond)
        print(f"Caméra {nom} : fond enregistré -> {out / f'fond_{nom}.png'}")
    if echecs_cameras:
        print(f"\nCaméras sans fond : {', '.join(echecs_cameras)}. Relancez seulement celles-ci, "
              f"par exemple : python vision/masquage.py capture --cams {echecs_cameras[0]}=<index> "
              f"--out {out}/")


def commande_migrer(args):
    """Ancien format (fond_cam<index>.png, clés d'index dans reglages.json) -> format par nom."""
    dossier = Path(args.out)
    cams = parse_cams(args.cams)
    for nom, idx in cams:
        ancien = dossier / f"fond_cam{idx}.png"
        if ancien.exists():
            ancien.rename(dossier / f"fond_{nom}.png")
            print(f"{ancien.name} -> fond_{nom}.png")
        else:
            print(f"(pas de {ancien.name})")
    fichier = dossier / REGLAGES_FICHIER
    if fichier.exists():
        index_vers_nom = {str(idx): nom for nom, idx in cams}
        data = json.loads(fichier.read_text())
        nouveau = {index_vers_nom.get(cle, cle): val for cle, val in data.items()}
        fichier.write_text(json.dumps(nouveau, indent=2))
        print(f"{fichier.name} : clés {list(data)} -> {list(nouveau)}")


# --------------------------------------------------------------------------- #
# Masquage
# --------------------------------------------------------------------------- #
class Masqueur:
    def __init__(self, fonds):
        """fonds : dict {nom_camera: image BGR de la table vide}"""
        self.fonds = fonds

    @classmethod
    def charger(cls, dossier):
        fonds = {}
        for p in sorted(Path(dossier).glob("fond_*.png")):
            fonds[p.stem[len("fond_"):]] = cv2.imread(str(p))
        if not fonds:
            raise FileNotFoundError(f"Aucun fond_*.png dans {dossier}")
        return cls(fonds)

    @staticmethod
    def _fond_ajuste(frame, fond):
        """Compense une petite dérive de luminosité (gain par canal). La médiane sur toute
        l'image ignore les pièces, qui n'en couvrent qu'une petite partie."""
        valide = (frame.max(axis=2) > 60) & (fond.max(axis=2) > 60)
        if valide.sum() < 1000:
            return fond
        gain = np.array([np.median(frame[..., c][valide]) / max(np.median(fond[..., c][valide]), 1)
                         for c in range(3)])
        gain = np.clip(gain, 0.8, 1.25)   # on ne corrige que de petites dérives
        return np.clip(fond.astype(np.float32) * gain, 0, 255).astype(np.uint8)

    @staticmethod
    def _masque_pieces(frame, fond, zone):
        """Pixels qui diffèrent du fond (pièce, face sombre, ombre) dans `zone`, en ne gardant
        que les ensembles connexes qui contiennent au moins un pixel coloré (la pièce).
        Le bras (noir/blanc) n'est donc pas effacé, et rien ne change là où l'image
        est identique au fond."""
        f = cv2.GaussianBlur(frame, (5, 5), 0).astype(np.int16)
        g = cv2.GaussianBlur(fond, (5, 5), 0).astype(np.int16)
        diff = ((np.abs(f - g).max(axis=2) > SEUIL_DIFF).astype(np.uint8)) * 255
        diff = cv2.bitwise_and(diff, zone)
        diff = cv2.morphologyEx(diff, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        graine = cv2.bitwise_and(diff, pixels_colores(frame, fond))
        _, labels = cv2.connectedComponents(diff)
        garde = np.unique(labels[graine > 0])
        garde = garde[garde != 0]
        masque = np.isin(labels, garde).astype(np.uint8) * 255
        masque = cv2.dilate(masque, np.ones((5, 5), np.uint8), iterations=2)   # bords + flou
        return cv2.bitwise_and(masque, zone)

    def detecter(self, camera, frame, aire_min=80, aire_max=20000):
        """Détecteur PROVISOIRE sans apprentissage, pour tester l'effacement avant d'avoir YOLO.
        Une pièce = un ensemble de pixels qui diffère du fond et contient des pixels colorés ;
        sa forme est devinée d'après sa teinte moyenne (TEINTES). Ne détecte pas les défauts
        (conforme vaut toujours True). Garder le bras au repos : un bras en mouvement peut être
        pris pour une pièce. Renvoie des dicts compatibles avec choisir_cible()."""
        fond = self._fond_ajuste(frame, self.fonds[str(camera)])
        masque = self._masque_pieces(frame, fond, np.full(frame.shape[:2], 255, np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(masque)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        vif = pixels_colores(frame, fond) > 0
        detections = []
        for k in range(1, n):
            x, y, w, h, aire = stats[k]
            if not aire_min <= aire <= aire_max:
                continue
            colore = (labels == k) & vif          # pixels plus colorés que la table : la pièce
            if colore.sum() < 20:
                continue
            ang = hsv[..., 0][colore].astype(np.float32) * (2 * np.pi / 180)   # moyenne circulaire :
            teinte = (np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * np.pi)) * 180 / (2 * np.pi)
            # nombre de sommets de la partie colorée (indicatif ; utile surtout vue de dessus)
            cs, _ = cv2.findContours(colore.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            g = max(cs, key=cv2.contourArea)
            sommets = len(cv2.approxPolyDP(g, 0.04 * cv2.arcLength(g, True), True))
            detections.append({"forme": forme_par_teinte(teinte), "conforme": True,
                               "boite": (int(x), int(y), int(x + w), int(y + h)),
                               "conf": 1.0, "teinte": float(teinte), "aire": int(aire),
                               "sommets": sommets})
        return detections

    def effacer(self, camera, frame, boites_non_cibles, boites_protegees=None, marge=8,
                marge_protection=3, corriger_lumiere=True, entree_rgb=False):
        """Remplace par le fond les pièces situées dans les boîtes (x1, y1, x2, y2) des pièces
        non ciblées. Les pixels des `boites_protegees` (la cible) ne sont jamais modifiés, même
        si une boîte voisine les recouvre. Le bras n'est jamais touché.

        camera    : nom de la caméra (celui des fonds : "top", "side", ...)
        entree_rgb: True si `frame` est en RGB (cas des images LeRobot). La sortie est alors
                    aussi en RGB. Les fonds sont enregistrés en BGR."""
        if entree_rgb:
            frame_bgr = np.ascontiguousarray(frame[..., ::-1])
            sortie = self.effacer(camera, frame_bgr, boites_non_cibles, boites_protegees, marge,
                                  marge_protection, corriger_lumiere, entree_rgb=False)
            return np.ascontiguousarray(sortie[..., ::-1])
        fond = self.fonds[str(camera)]
        if not boites_non_cibles:
            return frame
        zone = np.zeros(frame.shape[:2], np.uint8)
        h, w = zone.shape
        for x1, y1, x2, y2 in boites_non_cibles:
            zone[max(int(y1) - marge, 0):min(int(y2) + marge, h),
                 max(int(x1) - marge, 0):min(int(x2) + marge, w)] = 255
        for x1, y1, x2, y2 in (boites_protegees or []):
            m = marge_protection
            zone[max(int(y1) - m, 0):min(int(y2) + m, h), max(int(x1) - m, 0):min(int(x2) + m, w)] = 0
        if corriger_lumiere:
            fond = self._fond_ajuste(frame, fond)
        masque = self._masque_pieces(frame, fond, zone)
        sortie = frame.copy()
        sortie[masque > 0] = fond[masque > 0]
        return sortie


# --------------------------------------------------------------------------- #
# Choix de la cible
# --------------------------------------------------------------------------- #
def choisir_cible(detections, forme):
    """Choisit la pièce à montrer au modèle du robot.

    detections : liste de dicts {"forme": "triangle", "conforme": True,
                                 "boite": (x1, y1, x2, y2), "conf": 0.93}
                 (toutes les pièces vues par UNE caméra, défectueuses comprises)
    forme      : forme demandée par P-Robo ("triangle", "etoile", "hexagone", "rond")

    Renvoie (cible, boites_non_cibles). cible vaut None s'il n'y a aucune pièce CONFORME de
    cette forme : l'orchestrateur répond alors "indisponible" à P-Robo.
    Si plusieurs candidates existent, on prend la plus isolée (moins de risque de heurter une
    voisine), puis la plus sûre pour le détecteur.
    Les pièces défectueuses, même de la bonne forme, ne sont jamais la cible."""
    def centre(b):
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def isolement(d):
        c = centre(d["boite"])
        autres = [centre(o["boite"]) for o in detections if o is not d]
        return min((float(np.hypot(c[0] - a[0], c[1] - a[1])) for a in autres), default=1e9)

    candidates = [d for d in detections if d["forme"] == forme and d["conforme"]]
    if not candidates:
        return None, [d["boite"] for d in detections]
    cible = max(candidates, key=lambda d: (isolement(d), d.get("conf", 1.0)))
    return cible, [d["boite"] for d in detections if d is not cible]


# --------------------------------------------------------------------------- #
# Contrôle du masquage en direct
# --------------------------------------------------------------------------- #
def commande_voir(args):
    cams = parse_cams(args.cams)
    appliquer_reglages_dossier(args.fonds, dict(cams))
    masqueur = Masqueur.charger(args.fonds)
    caps = {nom: ouvrir_camera(i) for nom, i in cams}
    print("Une colonne par caméra : haut = image brute, bas = pièces effacées. "
          "'q' (fenêtre au premier plan) pour quitter.")
    while True:
        colonnes = []
        for nom, cap in caps.items():
            ok, frame = cap.read()
            if not ok:
                frame = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
            h, w = frame.shape[:2]
            # Toute l'image est considérée comme "non ciblée" : sert à vérifier le masquage.
            efface = masqueur.effacer(nom, frame, [(0, 0, w, h)])
            brut = frame.copy()
            cv2.putText(brut, nom, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            colonnes.append(np.vstack([brut, efface]))   # haut = brut, bas = effacé
        grille = np.hstack(colonnes)
        if args.echelle != 1.0:
            grille = cv2.resize(grille, None, fx=args.echelle, fy=args.echelle,
                                interpolation=cv2.INTER_AREA)
        cv2.imshow("masquage (haut = brut, bas = efface)", grille)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    for cap in caps.values():
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbeux", action="store_true",
                    help="afficher aussi les messages du décodeur JPEG ('Corrupt JPEG data...'), "
                         "masqués par défaut ; à placer avant la commande")
    sub = ap.add_subparsers(dest="cmd", required=True)
    aide_cams = "caméras au format nom=index, ex. side=4 top=2 angle45=0"

    r = sub.add_parser("reglages", help="régler exposition et balance des blancs")
    r.add_argument("--cams", nargs="+", required=True, help=aide_cams)
    r.add_argument("--out", default="fonds/")
    r.set_defaults(fn=commande_reglages)

    c = sub.add_parser("capture", help="photographier la table vide")
    c.add_argument("--cams", nargs="+", required=True, help=aide_cams)
    c.add_argument("--out", default="fonds/")
    c.set_defaults(fn=commande_capture)

    v = sub.add_parser("voir", help="contrôler le masquage en direct")
    v.add_argument("--cams", nargs="+", required=True, help=aide_cams)
    v.add_argument("--fonds", default="fonds/")
    v.add_argument("--echelle", type=float, default=0.6,
                   help="taille d'affichage (0.6 = 1152x576 px pour 3 caméras ; 1.0 = taille réelle)")
    v.set_defaults(fn=commande_voir)

    m = sub.add_parser("migrer", help="ancien format (par index) -> format par nom")
    m.add_argument("--cams", nargs="+", required=True, help=aide_cams)
    m.add_argument("--out", default="fonds/")
    m.set_defaults(fn=commande_migrer)

    a = ap.parse_args()
    if a.verbeux:
        a.fn(a)
    else:
        with stderr_silencieux():
            a.fn(a)
