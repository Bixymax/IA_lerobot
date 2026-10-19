"""
detection.py - démo : montrer UNE forme au modèle du robot et effacer les autres pièces.

Utilise le détecteur PROVISOIRE de masquage.py (Masqueur.detecter : différence avec le fond +
couleur ; la forme est déduite de la teinte, réglable dans masquage.TEINTES). La couleur se voit
sur les trois caméras, y compris la vue de côté : tant qu'il n'y a qu'une pièce de chaque
couleur, chaque caméra retrouve la même cible. Sera remplacé par YOLO (formes + défauts).

Démo (index à adapter à l'installation du jour) :
    python vision/detection.py --cams side=4 top=2 angle45=0 --forme triangle
Touches (fenêtre au premier plan) : t = triangle, r = rond, h = hexagone, e = étoile,
                                    a = aucune (tout effacer), q = quitter.
Haut = image brute annotée (vert = cible gardée, rouge = effacée ; h = teinte mesurée,
       s = nombre de sommets), bas = ce que verrait le modèle du robot.
"""
import argparse

import cv2
import numpy as np

from masquage import (HAUTEUR, LARGEUR, Masqueur, appliquer_reglages_dossier, choisir_cible,
                      ouvrir_camera, parse_cams, stderr_silencieux)

FORMES = ["triangle", "rond", "hexagone", "etoile"]
TOUCHES = {ord("t"): "triangle", ord("r"): "rond", ord("h"): "hexagone", ord("e"): "etoile",
           ord("a"): None}


def montrer_forme(masqueur, camera, frame_bgr, forme):
    """Détecte les pièces, garde visible UNE pièce conforme de la forme demandée, efface les
    autres. Renvoie (image_pour_le_modele, detections, cible) ; cible = None si indisponible."""
    detections = masqueur.detecter(camera, frame_bgr)
    if forme is None:
        cible, non_cibles = None, [d["boite"] for d in detections]
    else:
        cible, non_cibles = choisir_cible(detections, forme)
    protegees = [cible["boite"]] if cible else None
    image = masqueur.effacer(camera, frame_bgr, non_cibles, boites_protegees=protegees)
    return image, detections, cible


def annoter(frame_bgr, nom, detections, cible, forme):
    img = frame_bgr.copy()
    for d in detections:
        x1, y1, x2, y2 = d["boite"]
        couleur = (0, 200, 0) if d is cible else (0, 0, 255)
        cv2.rectangle(img, (x1, y1), (x2, y2), couleur, 2)
        txt = f"{d['forme']} h={d['teinte']:.0f} s={d.get('sommets', 0)}"
        cv2.putText(img, txt, (x1, max(y1 - 5, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, couleur, 1)
    etat = f"{nom} | demande: {forme or 'aucune'}"
    if forme and cible is None:
        etat += " -> INDISPONIBLE"
    cv2.putText(img, etat, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    return img


def demo(args):
    cams = parse_cams(args.cams)
    appliquer_reglages_dossier(args.fonds, dict(cams))
    masqueur = Masqueur.charger(args.fonds)
    manquants = [nom for nom, _ in cams if nom not in masqueur.fonds]
    if manquants:
        raise SystemExit(f"Pas de fond pour : {', '.join(manquants)} "
                         f"(lancez d'abord : python vision/masquage.py capture ...)")
    caps = {nom: ouvrir_camera(i) for nom, i in cams}
    forme = args.forme
    print("t/r/h/e = choisir la forme, a = aucune, q = quitter (fenêtre au premier plan).")
    while True:
        colonnes = []
        for nom, cap in caps.items():
            ok, frame = cap.read()
            if not ok:
                frame = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
            image, detections, cible = montrer_forme(masqueur, nom, frame, forme)
            colonnes.append(np.vstack([annoter(frame, nom, detections, cible, forme), image]))
        grille = np.hstack(colonnes)
        if args.echelle != 1.0:
            grille = cv2.resize(grille, None, fx=args.echelle, fy=args.echelle,
                                interpolation=cv2.INTER_AREA)
        cv2.imshow("demo forme (haut = detection, bas = vu par le modele)", grille)
        touche = cv2.waitKey(1) & 0xFF
        if touche == ord("q"):
            break
        if touche in TOUCHES:
            forme = TOUCHES[touche]
            print(f"Forme demandée : {forme or 'aucune'}")
    for cap in caps.values():
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cams", nargs="+", required=True, help="nom=index, ex. side=4 top=2 angle45=0")
    ap.add_argument("--fonds", default="fonds/")
    ap.add_argument("--forme", default="triangle", choices=FORMES + ["aucune"])
    ap.add_argument("--echelle", type=float, default=0.6)
    ap.add_argument("--verbeux", action="store_true", help="afficher les messages du décodeur JPEG")
    a = ap.parse_args()
    if a.forme == "aucune":
        a.forme = None
    if a.verbeux:
        demo(a)
    else:
        with stderr_silencieux():
            demo(a)
