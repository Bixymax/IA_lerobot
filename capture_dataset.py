"""
capture_dataset.py - constitue le jeu de données YOLO (détection des formes) depuis la caméra du dessus.

Principe : on pose UNE pièce dont on connaît la forme, on appuie sur la touche de sa forme, puis sur
espace. La classe vient de la touche ; la boîte vient du détecteur de masquage.py (différence avec
le fond), qui trouve bien la POSITION d'une pièce même s'il se trompe sur sa forme. On obtient ainsi
des étiquettes YOLO sans dessiner de boîte à la main.
Les pièces défectueuses sont étiquetées par leur FORME comme les autres (touche d = défaut) : le
détecteur de formes doit les voir aussi. Le défaut sera jugé à part (étape suivante).

Pour plusieurs pièces à la fois (mode m) ou si le détecteur ne trouve pas la pièce (défaut très pâle,
par exemple), l'image est sauvée SANS étiquette : à étiqueter ensuite à la main (CVAT, Label Studio).

Usage (index à adapter : v4l2-ctl --list-devices) :
    python capture_dataset.py --cam top=2 --fonds fonds/ --out dataset/
Touches (fenêtre au premier plan) :
    t r h e = forme de la pièce posée (triangle, rond, hexagone, étoile)
    d       = pièce défectueuse oui/non        m = plusieurs pièces (pas d'étiquette auto)
    espace  = sauver l'image                   u = annuler la dernière image
    q       = quitter
Conseils : bougez la pièce (position, rotation) et changez de pièce entre deux prises ; faites
des séries avec la caméra légèrement déplacée et des éclairages différents. Visez 40+ images par
forme, dont des défauts.
Sortie : dataset/images/*.jpg, dataset/labels/*.txt (format YOLO), dataset/meta.csv, dataset/classes.txt
"""
import argparse
import csv
import time
from collections import Counter
from pathlib import Path

import cv2

from masquage import (Masqueur, appliquer_reglages_dossier, ouvrir_camera, parse_cams,
                      stderr_silencieux)

CLASSES = ["triangle", "rond", "hexagone", "etoile"]
TOUCHES_FORME = {ord("t"): "triangle", ord("r"): "rond", ord("h"): "hexagone", ord("e"): "etoile"}
OBJECTIF = 40   # images conseillées par forme
META_ENTETE = ["fichier", "forme", "defaut", "etiquette_auto", "camera", "horodatage"]


def camera_unique(texte):
    """'top=2' -> ('top', 2). parse_cams attend une LISTE de jetons, d'où l'enveloppe."""
    (nom, index), = parse_cams([texte])
    return nom, index


def ligne_label(classe, boite, largeur, hauteur):
    """Ligne YOLO « classe cx cy w h » (coordonnées normalisées 0-1) pour une boîte (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = boite
    cx, cy = (x1 + x2) / 2 / largeur, (y1 + y2) / 2 / hauteur
    w, h = (x2 - x1) / largeur, (y2 - y1) / hauteur
    return f"{CLASSES.index(classe)} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def boite_auto(masqueur, camera, frame):
    """Boîte de la pièce quand il y en a exactement UNE, sinon None (rien, ou plusieurs : bras compris)."""
    if masqueur is None:
        return None
    detections = masqueur.detecter(camera, frame)
    return detections[0]["boite"] if len(detections) == 1 else None


def sauver(dossier, frame, classe, defaut, boite, camera="top"):
    """Écrit l'image, son étiquette si `boite` est donnée, et une ligne dans meta.csv.
    classe = None pour une scène à plusieurs pièces. Renvoie (chemin_image, chemin_label ou None)."""
    dossier = Path(dossier)
    (dossier / "images").mkdir(parents=True, exist_ok=True)
    (dossier / "labels").mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    nom = f"{classe or 'multi'}_{'def' if defaut else 'ok'}_{stamp}"
    img = dossier / "images" / f"{nom}.jpg"
    cv2.imwrite(str(img), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    label = None
    if boite is not None and classe is not None:
        h, w = frame.shape[:2]
        label = dossier / "labels" / f"{nom}.txt"
        label.write_text(ligne_label(classe, boite, w, h) + "\n")
    meta = dossier / "meta.csv"
    nouveau = not meta.exists()
    with meta.open("a", newline="") as f:
        ecr = csv.writer(f)
        if nouveau:
            ecr.writerow(META_ENTETE)
        ecr.writerow([img.name, classe or "", int(defaut), int(label is not None), camera, stamp])
    (dossier / "classes.txt").write_text("\n".join(CLASSES) + "\n")
    return img, label


def annuler(dossier, img, label):
    """Supprime une image, son étiquette et sa ligne de meta.csv."""
    dossier = Path(dossier)
    for p in (img, label):
        if p is not None and Path(p).exists():
            Path(p).unlink()
    meta = dossier / "meta.csv"
    if meta.exists():
        lignes = list(csv.reader(meta.open()))
        gardees = [l for i, l in enumerate(lignes) if i == 0 or l[0] != Path(img).name]
        with meta.open("w", newline="") as f:
            csv.writer(f).writerows(gardees)


def compter(dossier):
    """Compteur {(forme, defaut): nombre d'images} d'après meta.csv (reprise d'une session)."""
    meta = Path(dossier) / "meta.csv"
    c = Counter()
    if meta.exists():
        for ligne in csv.DictReader(meta.open()):
            if ligne["forme"]:
                c[(ligne["forme"], int(ligne["defaut"]))] += 1
    return c


def _texte(img, txt, y, couleur=(0, 0, 255)):
    cv2.putText(img, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, couleur, 2)


def boucle(args):
    nom, index = camera_unique(args.cam)
    masqueur = None
    if args.fonds and Path(args.fonds).exists():
        appliquer_reglages_dossier(args.fonds, {nom: index})   # mêmes réglages qu'à l'enregistrement
        try:
            masqueur = Masqueur.charger(args.fonds)
            if nom not in masqueur.fonds:
                print(f"[ATTENTION] pas de fond pour '{nom}' : pas d'étiquetage automatique.")
                masqueur = None
        except FileNotFoundError:
            print("[ATTENTION] aucun fond trouvé : pas d'étiquetage automatique.")
    else:
        print("[ATTENTION] pas de dossier de fonds : les images seront sauvées SANS étiquette.")
    cap = ouvrir_camera(index)
    classe, defaut, multi, derniers = None, False, False, []
    compteur = compter(args.out)
    print("t/r/h/e = forme, d = défaut, m = plusieurs pièces, espace = sauver, u = annuler, q = quitter")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        boite = None if multi or masqueur is None else boite_auto(masqueur, nom, frame)
        vue = frame.copy()
        if boite:
            cv2.rectangle(vue, boite[:2], boite[2:], (0, 200, 0), 2)
        mode = "plusieurs pièces (sans étiquette)" if multi else f"forme={classe or '?'}"
        _texte(vue, f"{mode} | defaut={'OUI' if defaut else 'non'} | "
                    f"boite auto={'oui' if boite else 'NON'}", 25)
        _texte(vue, "  ".join(f"{c[:3]}:{compteur[(c, 0)]}+{compteur[(c, 1)]}d" for c in CLASSES)
                    + f"  (objectif {OBJECTIF}/forme)", 50, (0, 120, 255))
        cv2.imshow("capture dataset (espace = sauver)", vue)
        touche = cv2.waitKey(1) & 0xFF
        if touche == ord("q"):
            break
        elif touche in TOUCHES_FORME:
            classe, multi = TOUCHES_FORME[touche], False
        elif touche == ord("d"):
            defaut = not defaut
        elif touche == ord("m"):
            multi = not multi
        elif touche == ord("u") and derniers:
            img, label, cle = derniers.pop()
            annuler(args.out, img, label)
            if cle:
                compteur[cle] -= 1
            print(f"annulé : {img.name}")
        elif touche == ord(" "):
            if not multi and classe is None:
                print("Choisissez d'abord la forme (t/r/h/e) ou le mode plusieurs pièces (m).")
                continue
            img, label = sauver(args.out, frame, None if multi else classe, defaut, boite, nom)
            cle = None if multi else (classe, int(defaut))
            if cle:
                compteur[cle] += 1
            derniers.append((img, label, cle))
            print(f"{img.name} " + ("(étiquette auto)" if label else "(SANS étiquette : à étiqueter)"))
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", default="top=2", help="nom=index de la caméra du dessus, ex. top=2")
    ap.add_argument("--fonds", default="fonds/", help="dossier des fonds et réglages (masquage.py capture)")
    ap.add_argument("--out", default="dataset/")
    ap.add_argument("--verbeux", action="store_true", help="afficher les messages du décodeur JPEG")
    a = ap.parse_args()
    if a.verbeux:
        boucle(a)
    else:
        with stderr_silencieux():
            boucle(a)