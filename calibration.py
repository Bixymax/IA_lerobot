"""
calibration.py - relie les pixels de chaque caméra à des millimètres sur la table.

Pourquoi : la taille d'une pièce en pixels change selon l'endroit où elle est posée (la caméra
`top` n'est pas parfaitement verticale) et selon la caméra. Une homographie par caméra
(plan de la table -> image) donne :
  - la taille des pièces en mm, partout sur la table (conformite.py) ;
  - la même position (mm) pour une pièce vue par `top`, `side` et `angle45` : on sait quelle
    pièce de `side` est celle choisie sur `top`, même s'il y a deux pièces de même couleur ;
  - les coordonnées à envoyer à P-Robo.

Les points de référence sont des repères tracés SUR la table (coins des rectangles de la nappe),
avec leur position en mm dans fonds/points_table.json. Le fichier est créé au premier lancement
avec les 4 coins du rectangle vert (supposé A5 : 210 x 148 mm) : VÉRIFIEZ les mesures à la règle.
Ajoutez des coins d'autres rectangles (mesurés depuis le même coin d'origine) si une caméra ne
voit pas bien le rectangle vert : il faut au moins 4 points visibles par caméra.

Usage (index du jour : v4l2-ctl --list-devices) :
  1) Cliquer les repères, caméra par caméra :
       python calibration.py cliquer --cams top=4 side=2 angle45=6
     clic gauche = placer le point demandé, n = point invisible (passer), z = annuler,
     Entrée = valider (4 points mini), q = abandonner cette caméra
  2) Contrôler : une grille tous les 20 mm est dessinée sur la table de chaque caméra
       python calibration.py voir --cams top=4 side=2 angle45=6

A refaire si une caméra bouge (comme le fond : python masquage.py capture ...).
Résultat : fonds/calibration.json (propre à l'installation, non versionné).
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from masquage import (HAUTEUR, LARGEUR, appliquer_reglages_dossier, ouvrir_camera, parse_cams,
                      stderr_silencieux)

POINTS_FICHIER = "points_table.json"
CALIB_FICHIER = "calibration.json"

# Origine : coin haut-gauche du rectangle vert TEL QUE VU par la caméra top ; x vers la droite de
# l'image top, y vers le bas de l'image top (vers le robot). Unité : mm.
POINTS_DEFAUT = {
    "_aide": ("Repères tracés sur la table, en mm. Origine = coin haut-gauche du rectangle vert vu "
              "par la caméra top, x vers la droite, y vers le robot. VÉRIFIEZ à la règle (A5 supposé) "
              "et ajoutez d'autres coins si besoin (4 points visibles minimum par caméra). "
              "zone_alimentation (facultatif) : polygone en mm ; seules les pièces dedans peuvent "
              "être choisies comme cible. zones_pieces (facultatif) : liste de polygones en mm "
              "(alimentation, déchet, échange) ; un objet détecté hors de ces zones (+30 mm) n'est "
              "pas une pièce (bord de table, robot) et n'est jamais effacé."),
    "points": {
        "vert_haut_gauche": [0.0, 0.0],
        "vert_haut_droite": [210.0, 0.0],
        "vert_bas_droite": [210.0, 148.0],
        "vert_bas_gauche": [0.0, 148.0],
    },
    "zone_alimentation": None,
    "zones_pieces": None,
}


def charger_points(dossier):
    """Lit fonds/points_table.json ; le crée avec les valeurs par défaut s'il manque."""
    fichier = Path(dossier) / POINTS_FICHIER
    if not fichier.exists():
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(POINTS_DEFAUT, indent=2, ensure_ascii=False))
        print(f"[calibration] {fichier} créé avec les coins du rectangle vert (A5 supposé) : "
              f"vérifiez les mesures à la règle.")
    return json.loads(fichier.read_text())


class Calibration:
    """Homographies image -> table (mm), une par caméra.

    Les homographies sont mémorisées pour la taille d'image de la calibration ; une image d'une
    autre résolution (ex. 1280x960 au lieu de 640x480) est remise à l'échelle automatiquement."""

    def __init__(self, cameras=None, zone=None, zones_pieces=None):
        # cameras : {nom: {"H": matrice 3x3 image->table, "taille": (largeur, hauteur)}}
        self.cameras = {nom: {"H": np.asarray(c["H"], np.float64), "taille": tuple(c["taille"])}
                        for nom, c in (cameras or {}).items()}
        self.zone = None if zone is None else np.asarray(zone, np.float32)
        # zones où des pièces peuvent se trouver (alimentation, déchet, échange) : une « pièce »
        # détectée ailleurs (bord de table, robot, câbles) n'en est pas une et n'est jamais effacée
        self.zones_pieces = [np.asarray(z, np.float32) for z in (zones_pieces or [])]

    # ---- fichiers ---------------------------------------------------------
    @classmethod
    def charger(cls, dossier):
        """Calibration vide (aucune caméra) si le fichier n'existe pas encore."""
        dossier = Path(dossier)
        fichier = dossier / CALIB_FICHIER
        cameras = json.loads(fichier.read_text()) if fichier.exists() else {}
        zone, zones_pieces = None, None
        if (dossier / POINTS_FICHIER).exists():
            points = json.loads((dossier / POINTS_FICHIER).read_text())
            zone = points.get("zone_alimentation")
            zones_pieces = points.get("zones_pieces")
        return cls(cameras, zone, zones_pieces)

    def sauver(self, dossier):
        fichier = Path(dossier) / CALIB_FICHIER
        data = {nom: {"H": c["H"].tolist(), "taille": list(c["taille"])}
                for nom, c in self.cameras.items()}
        fichier.write_text(json.dumps(data, indent=2))
        return fichier

    # ---- conversions -------------------------------------------------------
    def a(self, camera):
        return camera in self.cameras

    def _echelle(self, camera, taille_image):
        w0, h0 = self.cameras[camera]["taille"]
        w, h = taille_image
        return np.array([w0 / w, h0 / h])

    def vers_table(self, camera, points_px, taille_image=(LARGEUR, HAUTEUR)):
        """Points image (N, 2) en pixels -> points table (N, 2) en mm."""
        p = np.asarray(points_px, np.float64).reshape(-1, 2) * self._echelle(camera, taille_image)
        return cv2.perspectiveTransform(p.reshape(-1, 1, 2), self.cameras[camera]["H"]).reshape(-1, 2)

    def vers_image(self, camera, points_mm, taille_image=(LARGEUR, HAUTEUR)):
        """Points table (N, 2) en mm -> points image (N, 2) en pixels."""
        Hinv = np.linalg.inv(self.cameras[camera]["H"])
        p = cv2.perspectiveTransform(np.asarray(points_mm, np.float64).reshape(-1, 1, 2), Hinv)
        return p.reshape(-1, 2) / self._echelle(camera, taille_image)

    def mm2_par_pixel(self, camera, point_px, taille_image=(LARGEUR, HAUTEUR)):
        """Surface (mm²) couverte par UN pixel autour de `point_px` : l'homographie est
        localement affine, on prend le déterminant de sa dérivée (différences finies)."""
        x, y = point_px
        p = self.vers_table(camera, [(x, y), (x + 1, y), (x, y + 1)], taille_image)
        dx, dy = p[1] - p[0], p[2] - p[0]
        return float(abs(dx[0] * dy[1] - dx[1] * dy[0]))

    def dans_zone(self, point_mm):
        """True si le point est dans la zone d'alimentation (ou s'il n'y a pas de zone définie)."""
        if self.zone is None or len(self.zone) < 3:
            return True
        return cv2.pointPolygonTest(self.zone.reshape(-1, 1, 2),
                                    (float(point_mm[0]), float(point_mm[1])), False) >= 0


    def dans_zones_pieces(self, point_mm, marge=30.0):
        """True si le point est dans l'une des zones de pièces, à `marge` mm près (ou si aucune
        zone n'est définie : pas de filtre)."""
        if not self.zones_pieces:
            return True
        pt = (float(point_mm[0]), float(point_mm[1]))
        return any(cv2.pointPolygonTest(z.reshape(-1, 1, 2), pt, True) >= -marge
                   for z in self.zones_pieces if len(z) >= 3)


def calculer_homographie(points_px, points_mm):
    """Moindres carrés sur tous les points (pas de RANSAC : les points cliqués sont tous voulus).
    Renvoie (H image->table, erreurs en mm par point)."""
    src = np.asarray(points_px, np.float64)
    dst = np.asarray(points_mm, np.float64)
    if len(src) < 4:
        raise ValueError("il faut au moins 4 points")
    H, _ = cv2.findHomography(src, dst, 0)
    if H is None:
        raise ValueError("homographie impossible (points alignés ?)")
    proj = cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(-1, 2)
    return H, np.hypot(*(proj - dst).T)


# --------------------------------------------------------------------------- #
# Dessin de contrôle
# --------------------------------------------------------------------------- #
def dessiner_grille(img, calib, camera, points_mm, pas=20.0, couleur=(255, 0, 255)):
    """Grille de la table (tous les `pas` mm) autour des repères, vue par cette caméra."""
    pts = np.asarray(list(points_mm), np.float64)
    (xmin, ymin), (xmax, ymax) = pts.min(axis=0) - 2 * pas, pts.max(axis=0) + 2 * pas
    h, w = img.shape[:2]
    for x in np.arange(np.floor(xmin / pas) * pas, xmax + 1e-6, pas):
        ligne = calib.vers_image(camera, [(x, y) for y in np.linspace(ymin, ymax, 30)], (w, h))
        cv2.polylines(img, [ligne.astype(np.int32).reshape(-1, 1, 2)], False, couleur, 1)
    for y in np.arange(np.floor(ymin / pas) * pas, ymax + 1e-6, pas):
        ligne = calib.vers_image(camera, [(x, y) for x in np.linspace(xmin, xmax, 30)], (w, h))
        cv2.polylines(img, [ligne.astype(np.int32).reshape(-1, 1, 2)], False, couleur, 1)
    if calib.zone is not None and len(calib.zone) >= 3:
        z = calib.vers_image(camera, calib.zone, (w, h)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [z], True, (0, 200, 0), 2)
    return img


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #
def _cliquer_camera(nom, cap, points, echelle):
    """Fait cliquer les repères sur une caméra. Renvoie {nom_point: (x, y) px} ou None."""
    noms = list(points)
    clics = {}
    etat = {"i": 0, "clic": None}
    win = f"calibration {nom}"

    def souris(evt, x, y, *_):
        if evt == cv2.EVENT_LBUTTONDOWN:
            etat["clic"] = (x / echelle, y / echelle)

    cv2.namedWindow(win)
    cv2.setMouseCallback(win, souris)
    while True:
        ok, frame = cap.read()
        if not ok:
            frame = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
        if etat["clic"] is not None and etat["i"] < len(noms):
            clics[noms[etat["i"]]] = etat["clic"]
            etat["i"] += 1
        etat["clic"] = None
        img = cv2.resize(frame, None, fx=echelle, fy=echelle, interpolation=cv2.INTER_LINEAR)
        for p, (x, y) in clics.items():
            c = (int(x * echelle), int(y * echelle))
            cv2.drawMarker(img, c, (0, 0, 255), cv2.MARKER_CROSS, 14, 1)
            cv2.putText(img, p, (c[0] + 5, c[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        if etat["i"] < len(noms):
            p = noms[etat["i"]]
            msg = f"{nom} : cliquez '{p}' {tuple(points[p])} mm   (n = invisible, z = annuler)"
            if len(clics) >= 4:
                msg += "  Entree = finir"
        else:
            msg = f"{nom} : {len(clics)} points. Entree = valider, z = annuler, q = abandonner"
        cv2.putText(img, msg, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        cv2.imshow(win, img)
        t = cv2.waitKey(30) & 0xFF
        if t == ord("n") and etat["i"] < len(noms):
            etat["i"] += 1
        elif t == ord("z") and etat["i"] > 0:
            etat["i"] -= 1
            clics.pop(noms[etat["i"]], None)
        elif t in (13, 10) and (len(clics) >= 4 or etat["i"] >= len(noms)):
            cv2.destroyWindow(win)
            return clics if len(clics) >= 4 else None
        elif t == ord("q"):
            cv2.destroyWindow(win)
            return None


def commande_cliquer(args):
    cams = parse_cams(args.cams)
    points = charger_points(args.fonds)["points"]
    appliquer_reglages_dossier(args.fonds, dict(cams))
    calib = Calibration.charger(args.fonds)
    for nom, idx in cams:
        cap = ouvrir_camera(idx)
        print(f"\n== Caméra {nom} : cliquez les repères demandés (n = invisible depuis cette caméra)")
        clics = _cliquer_camera(nom, cap, points, args.echelle)
        cap.release()
        if clics is None:
            print(f"[calibration] {nom} : abandonnée ou moins de 4 points, rien n'est changé.")
            continue
        noms = list(clics)
        H, err = calculer_homographie([clics[p] for p in noms], [points[p] for p in noms])
        for p, e in zip(noms, err):
            print(f"  {p:<22} écart {e:5.1f} mm")
        print(f"  -> écart moyen {err.mean():.1f} mm, max {err.max():.1f} mm")
        if len(noms) == 4:
            print("  (4 points : l'écart est toujours ~0 ; ajoutez des repères pour vérifier la "
                  "précision, ou contrôlez avec la commande 'voir')")
        elif err.max() > 3:
            print("  [ATTENTION] écart > 3 mm : point mal cliqué ou mesure fausse dans "
                  f"{POINTS_FICHIER}.")
        calib.cameras[nom] = {"H": H, "taille": (LARGEUR, HAUTEUR)}
        print(f"[calibration] {nom} enregistrée -> {calib.sauver(args.fonds)}")
    cv2.destroyAllWindows()


def commande_voir(args):
    cams = parse_cams(args.cams)
    points = charger_points(args.fonds)["points"]
    appliquer_reglages_dossier(args.fonds, dict(cams))
    calib = Calibration.charger(args.fonds)
    caps = {nom: ouvrir_camera(i) for nom, i in cams}
    print("Grille tous les 20 mm, croix = repères. Elle doit coller aux traits de la nappe. "
          "q = quitter.")
    while True:
        colonnes = []
        for nom, cap in caps.items():
            ok, frame = cap.read()
            if not ok:
                frame = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
            if calib.a(nom):
                dessiner_grille(frame, calib, nom, points.values())
                for p, mm in points.items():
                    x, y = calib.vers_image(nom, [mm])[0]
                    cv2.drawMarker(frame, (int(x), int(y)), (0, 0, 255), cv2.MARKER_CROSS, 12, 2)
            else:
                cv2.putText(frame, "NON CALIBREE", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (0, 0, 255), 2)
            cv2.putText(frame, nom, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            colonnes.append(frame)
        grille = np.hstack(colonnes)
        if args.echelle != 1.0:
            grille = cv2.resize(grille, None, fx=args.echelle, fy=args.echelle)
        cv2.imshow("calibration (grille 20 mm)", grille)
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break
    for cap in caps.values():
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbeux", action="store_true", help="messages du décodeur JPEG")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cliquer", help="cliquer les repères de la table sur chaque caméra")
    c.add_argument("--cams", nargs="+", required=True, help="nom=index, ex. top=4 side=2 angle45=6")
    c.add_argument("--fonds", default="fonds/")
    c.add_argument("--echelle", type=float, default=1.5, help="agrandissement pour cliquer précisément")
    c.set_defaults(fn=commande_cliquer)
    v = sub.add_parser("voir", help="contrôler la calibration (grille sur la table)")
    v.add_argument("--cams", nargs="+", required=True)
    v.add_argument("--fonds", default="fonds/")
    v.add_argument("--echelle", type=float, default=0.6)
    v.set_defaults(fn=commande_voir)
    a = ap.parse_args()
    if a.verbeux:
        a.fn(a)
    else:
        with stderr_silencieux():
            a.fn(a)
