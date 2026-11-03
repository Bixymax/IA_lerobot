"""
conformite.py - forme, couleur et taille d'une pièce vue par la caméra `top`, et verdict OK / défaut.

Règles du client (pièces OK) : étoile verte, hexagone jaune, triangle rouge, rond orange, à la
taille réglementaire. Une pièce défectueuse a la mauvaise TAILLE ou la mauvaise COULEUR (elle
n'est pas déformée). Donc :
  - la FORME se lit au contour (pas à la couleur : une étoile rouge reste une étoile, défectueuse) ;
  - la COULEUR est comparée à celle des étoiles OK pour une étoile, etc. ;
  - la TAILLE (diamètre équivalent en mm, via calibration.py) est comparée à celle des pièces OK
    au même endroit de la table.
Les références sont APPRISES sur vos pièces OK (commande `apprendre`) plutôt que tirées des cotes
nominales : la mesure dépend de la caméra (angle, flou, côtés visibles de la pièce) et ce biais
est le même pour les pièces OK et défectueuses.

Usage (caméra du dessus ; index du jour : v4l2-ctl --list-devices) :
  0) Prérequis : fond (masquage.py capture) et calibration (calibration.py cliquer).
  1) Apprendre chaque forme OK : poser 1 à 4 pièces OK de cette forme, espace, les déplacer,
     espace, ... (8 à 15 échantillons par forme, répartis sur toute la zone d'alimentation) :
       python conformite.py apprendre --cam top=4 --forme etoile
  2) Vérifier en direct, avec des pièces OK et défectueuses :
       python conformite.py verifier --cam top=4
     Chaque pièce affiche forme, diamètre, écart à la référence et verdict. « sigma » = dispersion
     de la mesure sur les 30 dernières images : un défaut plus petit que ~3 sigma n'est pas
     détectable de façon fiable. c = ajouter les mesures dans fonds/mesures.csv (pour le rapport).

Les tolérances se règlent dans fonds/references.json, clé "tolerances" (voir TOLERANCES).
"""
import argparse
import csv
import json
import time
import unicodedata
from pathlib import Path

import cv2
import numpy as np

from calibration import Calibration
from masquage import (Masqueur, appliquer_reglages_dossier, ouvrir_camera,
                      parse_cams, stderr_silencieux)

FORMES = ["triangle", "rond", "hexagone", "etoile"]
COULEUR_ATTENDUE = {"triangle": "rouge", "rond": "orange", "hexagone": "jaune", "etoile": "vert"}

# Nom de couleur d'après la teinte H d'OpenCV (0-179). Sert à l'affichage et, tant qu'une forme
# n'a pas été apprise, au contrôle de couleur. Mêmes plages que masquage.TEINTES.
TEINTES_COULEURS = [("rouge", 0, 10), ("rouge", 165, 179), ("orange", 11, 22),
                    ("jaune", 23, 38), ("vert", 39, 90), ("bleu", 91, 130), ("violet", 131, 164)]

# Forme = (solidité, remplissage) mesurés sur le contour ramené sur le plan de la table :
#   solidité    = aire / aire de l'enveloppe convexe (étoile basse, les autres ~1)
#   remplissage = aire / aire du cercle circonscrit (triangle ~0.4-0.55, hexagone ~0.8, rond ~0.9)
# Valeurs mesurées sur vos photos (pièces de ~28 px) ; remplacées par vos mesures après `apprendre`.
PROTOTYPES_FORME = {"etoile": (0.82, 0.64), "triangle": (0.95, 0.53),
                    "hexagone": (0.97, 0.80), "rond": (0.98, 0.90)}
SIGMA_FORME_MIN = 0.03

TOLERANCES = {
    "taille_min_pct": 2.5,   # tolérance de taille minimale (± %), même si la mesure est très stable
    "taille_k": 3.0,         # sinon : k x dispersion des pièces OK autour de la référence
    "couleur_min": 10.0,     # écart de couleur minimal toléré (unités Lab, ~ ΔE)
    "couleur_k": 3.0,        # sinon : k x dispersion de couleur des pièces OK
    "forme_max": 6.0,        # au-delà (en écarts-types), la forme est « inconnue » -> défaut
}
REFERENCES_FICHIER = "references.json"
ECHANTILLONS_MIN = 3          # en dessous, la forme est considérée comme non apprise


def couleur_par_teinte(h):
    h = float(h) % 180            # une moyenne circulaire peut rendre 180.0 (= 0, rouge)
    for nom, bas, haut in TEINTES_COULEURS:
        if bas <= h < haut + 1:
            return nom
    return "autre"


def _teinte_moyenne(h_valeurs):
    ang = h_valeurs.astype(np.float32) * (2 * np.pi / 180)
    return float((np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * np.pi)) * 180 / (2 * np.pi))


def distance_couleur(lab, ref):
    """Écart de couleur (Lab). La clarté L compte deux fois moins que la teinte (a, b) : elle varie
    avec l'éclairage et l'ombre, alors qu'un défaut de colorimétrie change surtout a et b."""
    d = np.asarray(lab, float) - np.asarray(ref, float)
    return float(np.sqrt((0.5 * d[0]) ** 2 + d[1] ** 2 + d[2] ** 2))


# --------------------------------------------------------------------------- #
# Mesure d'une pièce
# --------------------------------------------------------------------------- #
def segmenter(piece, frame_bgr):
    """Contour précis de la pièce, pour la mesurer (l'effacement, lui, prend large).

    On regarde l'écart de couleur (Lab, clarté comptée à moitié : une ombre légère reste sous le
    seuil, mais une pièce sombre comme l'étoile verte reste bien contrastée) entre l'image et la
    table vide, sans flou. Le bord de la pièce est placé à mi-chemin entre
    le niveau de la table et celui de la pièce : il ne dépend pas du contraste (une pièce jaune
    pâle n'est pas mesurée plus petite qu'une verte foncée). Les pixels du bord, à moitié sur la
    pièce, comptent pour la fraction qu'ils couvrent : la surface est précise à mieux qu'un pixel.

    Renvoie (masque plein uint8 du découpage, contour, nombre de pixels fractionnaire) ou None."""
    colore = piece["masque_colore"].astype(np.uint8)
    ox, oy = piece["origine"]
    h, w = colore.shape
    region = cv2.dilate(colore, np.ones((3, 3), np.uint8), iterations=3) > 0
    fond = piece.get("fond")
    fraction = None
    masque = cv2.morphologyEx(colore, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    if fond is not None:
        f = cv2.cvtColor(frame_bgr[oy:oy + h, ox:ox + w], cv2.COLOR_BGR2LAB).astype(np.float32)
        g = cv2.cvtColor(fond, cv2.COLOR_BGR2LAB).astype(np.float32)
        d = np.sqrt((0.5 * (f[..., 0] - g[..., 0])) ** 2 + (f[..., 1] - g[..., 1]) ** 2
                    + (f[..., 2] - g[..., 2]) ** 2)
        coeur = cv2.erode(colore, np.ones((3, 3), np.uint8)) > 0
        if coeur.sum() < 5:
            coeur = colore > 0
        table = ~region
        d0 = float(np.median(d[table])) if table.sum() >= 20 else float(np.percentile(d[region], 5))
        d1 = float(np.percentile(d[coeur], 75))
        if d1 - d0 >= 8:                               # contraste suffisant : mesure fine
            masque = (((d - d0) > (d1 - d0) / 2) & region).astype(np.uint8)
            masque = cv2.morphologyEx(masque, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            fraction = np.clip((d - d0) / (d1 - d0), 0, 1) * region
    contours, _ = cv2.findContours(masque, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 15:
        return None
    plein = np.zeros_like(masque)
    cv2.drawContours(plein, [contour], -1, 1, -1)       # pièce sans trous (reflets)
    if fraction is None:
        return plein, contour, float(plein.sum())
    # intérieur compté entier (un reflet n'enlève pas de surface), bord en fraction, voisins exclus
    interieur = cv2.erode(plein, np.ones((3, 3), np.uint8)) > 0
    proche = cv2.dilate(plein, np.ones((3, 3), np.uint8), iterations=2) > 0
    nb = float(np.where(interieur, 1.0, fraction * proche).sum())
    return plein, contour, nb



def mesurer(piece, frame_bgr, camera, calib=None):
    """Mesure une pièce trouvée par Masqueur.pieces(). Renvoie None si elle est trop petite.

    Avec une calibration de `camera`, les longueurs sont en mm et la forme est mesurée sur le
    contour redressé (la perspective ne déforme plus la pièce) ; sinon tout reste en pixels."""
    seg = segmenter(piece, frame_bgr)
    if seg is None:
        return None
    plein, g, nb_pixels = seg
    ox, oy = piece["origine"]
    m = cv2.moments(plein, binaryImage=True)
    cx, cy = m["m10"] / m["m00"] + ox, m["m01"] / m["m00"] + oy
    contour = g.reshape(-1, 2).astype(np.float64) + (ox, oy)
    taille_image = (frame_bgr.shape[1], frame_bgr.shape[0])
    if calib is not None and calib.a(camera):
        unite = "mm"
        contour_t = calib.vers_table(camera, contour, taille_image)
        centre = calib.vers_table(camera, [(cx, cy)], taille_image)[0]
        aire_pixel = calib.mm2_par_pixel(camera, (cx, cy), taille_image)
    else:
        unite, contour_t, centre, aire_pixel = "px", contour, np.array([cx, cy]), 1.0
    # Aire = pixels de la pièce (bords comptés en fraction) x surface d'un pixel à cet endroit
    aire = nb_pixels * aire_pixel
    poly = contour_t.astype(np.float32).reshape(-1, 1, 2)
    a_poly = max(cv2.contourArea(poly), 1e-6)
    _, rayon = cv2.minEnclosingCircle(poly)
    solidite = a_poly / max(cv2.contourArea(cv2.convexHull(poly)), 1e-6)
    remplissage = a_poly / max(np.pi * rayon ** 2, 1e-6)
    # Couleur mesurée à l'intérieur de la pièce (le bord est mélangé avec la table)
    interieur = cv2.erode(plein, np.ones((3, 3), np.uint8))
    if interieur.sum() < 10:
        interieur = plein
    h, w = plein.shape
    decoupe = frame_bgr[oy:oy + h, ox:ox + w]
    sel = interieur > 0
    lab8 = cv2.cvtColor(decoupe, cv2.COLOR_BGR2LAB)[sel].astype(np.float64)
    L, a, b = np.median(lab8, axis=0)
    teinte = _teinte_moyenne(cv2.cvtColor(decoupe, cv2.COLOR_BGR2HSV)[..., 0][sel])
    return {"unite": unite, "centre_px": (float(cx), float(cy)),
            "x": float(centre[0]), "y": float(centre[1]),
            "aire": aire, "diametre": float(2 * np.sqrt(aire / np.pi)),
            "solidite": float(solidite), "remplissage": float(remplissage),
            "lab": [float(L * 100 / 255), float(a - 128), float(b - 128)],
            "teinte": teinte, "couleur": couleur_par_teinte(teinte)}


# --------------------------------------------------------------------------- #
# Références apprises sur les pièces OK
# --------------------------------------------------------------------------- #
def _base_taille(x, y, degre):
    """Variables du modèle de taille : constante, puis pente (x, y), puis courbure."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    cols = [np.ones_like(x)]
    if degre >= 1:
        cols += [x, y]
    if degre >= 2:
        cols += [x * x, y * y, x * y]
    return np.stack(cols, axis=-1)


class References:
    """Échantillons de pièces OK par forme, et modèles calculés à partir d'eux.

    Taille : la taille MESURÉE d'une pièce OK varie un peu avec sa position (caméra inclinée,
    côtés de la pièce plus ou moins visibles). Avec assez d'échantillons, on modélise cette
    variation (plan, puis surface courbe à partir de 15 échantillons) et on compare chaque pièce
    à la référence de SON endroit : la tolérance peut alors être plus serrée."""

    def __init__(self, data=None):
        data = data or {}
        self.unite = data.get("unite")
        self.tolerances = {**TOLERANCES, **data.get("tolerances", {})}
        self.echantillons = {f: list(v) for f, v in data.get("formes", {}).items()}
        self._cache = {}

    @classmethod
    def charger(cls, dossier):
        f = Path(dossier) / REFERENCES_FICHIER
        return cls(json.loads(f.read_text()) if f.exists() else None)

    def sauver(self, dossier):
        f = Path(dossier) / REFERENCES_FICHIER
        f.write_text(json.dumps({"unite": self.unite, "tolerances": self.tolerances,
                                 "formes": self.echantillons}, indent=1))
        return f

    def ajouter(self, forme, mesures):
        for m in mesures:
            if self.unite is None:
                self.unite = m["unite"]
            elif m["unite"] != self.unite:
                raise ValueError(f"références en {self.unite}, mesure en {m['unite']} : refaire "
                                 f"l'apprentissage (supprimer {REFERENCES_FICHIER}) après calibration")
            self.echantillons.setdefault(forme, []).append(
                {k: m[k] for k in ("x", "y", "diametre", "lab", "solidite", "remplissage")})
        self._cache.pop(forme, None)

    def retirer(self, forme, n):
        if n > 0:
            self.echantillons[forme] = self.echantillons.get(forme, [])[:-n]
        self._cache.pop(forme, None)

    def nombre(self, forme):
        return len(self.echantillons.get(forme, []))

    def modele(self, forme):
        """None si la forme n'a pas assez d'échantillons."""
        if forme in self._cache:
            return self._cache[forme]
        ech = self.echantillons.get(forme, [])
        if len(ech) < ECHANTILLONS_MIN:
            return None
        x = np.array([e["x"] for e in ech])
        y = np.array([e["y"] for e in ech])
        d = np.array([e["diametre"] for e in ech])
        lab = np.array([e["lab"] for e in ech])
        f = np.array([[e["solidite"], e["remplissage"]] for e in ech])
        centre_xy = (x.mean(), y.mean())
        degre = 2 if len(ech) >= 15 else 1 if len(ech) >= 6 else 0
        X = _base_taille((x - centre_xy[0]) / 100, (y - centre_xy[1]) / 100, degre)
        coef, *_ = np.linalg.lstsq(X, d, rcond=None)
        residus = d - X @ coef
        sigma_d = float(np.sqrt((residus ** 2).sum() / max(len(d) - X.shape[1], 1)))
        lab_ref = lab.mean(axis=0)
        sigma_c = float(np.sqrt(np.mean([distance_couleur(l, lab_ref) ** 2 for l in lab])))
        mod = {"n": len(ech), "degre": degre, "coef": coef, "centre_xy": centre_xy,
               "sigma_taille": max(sigma_d, 0.05), "borne_taille": (d.min(), d.max()),
               "lab": lab_ref, "sigma_couleur": sigma_c,
               "forme_mu": f.mean(axis=0), "forme_sigma": np.maximum(f.std(axis=0), SIGMA_FORME_MIN)}
        self._cache[forme] = mod
        return mod

    def taille_attendue(self, forme, x, y):
        mod = self.modele(forme)
        if mod is None:
            return None
        cx, cy = mod["centre_xy"]
        v = float(_base_taille((x - cx) / 100, (y - cy) / 100, mod["degre"]) @ mod["coef"])
        # pas d'extrapolation folle hors de la zone apprise
        lo, hi = mod["borne_taille"]
        marge = 2 * mod["sigma_taille"]
        return float(np.clip(v, lo - marge, hi + marge))


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
def classer_forme(mesure, refs=None):
    """Forme la plus proche en (solidité, remplissage). Renvoie (forme ou None, distance)."""
    f = np.array([mesure["solidite"], mesure["remplissage"]])
    meilleure, dmin = None, np.inf
    for forme in FORMES:
        mod = refs.modele(forme) if refs is not None else None
        if mod is not None:
            mu, sigma = mod["forme_mu"], mod["forme_sigma"]
        else:
            mu, sigma = np.array(PROTOTYPES_FORME[forme]), np.full(2, 0.04)
        d = float(np.sqrt(np.mean(((f - mu) / sigma) ** 2)))
        if d < dmin:
            meilleure, dmin = forme, d
    limite = (refs.tolerances if refs is not None else TOLERANCES)["forme_max"]
    return (meilleure if dmin <= limite else None), dmin


def juger(mesure, refs=None):
    """Verdict pour une pièce mesurée. Renvoie un dict :
      forme, couleur (nom), conforme (bool), raisons (liste de textes si défaut),
      ecart_taille_pct / tol_taille_pct (None si la taille n'a pas pu être vérifiée),
      ecart_couleur / tol_couleur, remarques (ce qui n'a pas pu être vérifié)."""
    refs = refs if refs is not None else References()
    tol = refs.tolerances
    forme, dist_forme = classer_forme(mesure, refs)
    v = {"forme": forme or "inconnue", "couleur": mesure["couleur"], "conforme": False,
         "raisons": [], "remarques": [], "distance_forme": dist_forme,
         "ecart_taille_pct": None, "tol_taille_pct": None, "ecart_couleur": None, "tol_couleur": None}
    if forme is None:
        v["raisons"].append("forme inconnue")
        return v
    mod = refs.modele(forme)
    # --- couleur
    if mod is not None:
        dc = distance_couleur(mesure["lab"], mod["lab"])
        tc = max(tol["couleur_min"], tol["couleur_k"] * mod["sigma_couleur"])
        v["ecart_couleur"], v["tol_couleur"] = dc, tc
        if dc > tc:
            v["raisons"].append(f"couleur ({mesure['couleur']}, écart {dc:.0f} > {tc:.0f})")
    else:
        v["remarques"].append(f"{forme} non appris : couleur jugée par la teinte")
        if mesure["couleur"] != COULEUR_ATTENDUE[forme]:
            v["raisons"].append(f"couleur {mesure['couleur']} (attendu {COULEUR_ATTENDUE[forme]})")
    # --- taille
    if mod is not None and refs.unite == mesure["unite"]:
        ref = refs.taille_attendue(forme, mesure["x"], mesure["y"])
        ecart = (mesure["diametre"] - ref) / ref * 100
        t = max(tol["taille_min_pct"], tol["taille_k"] * mod["sigma_taille"] / ref * 100)
        v["ecart_taille_pct"], v["tol_taille_pct"], v["taille_ref"] = ecart, t, ref
        if abs(ecart) > t:
            v["raisons"].append(f"taille {ecart:+.1f}% (tolérance ±{t:.1f}%)")
    elif mod is None:
        v["remarques"].append("taille non vérifiée (forme non apprise)")
    else:
        v["remarques"].append(f"taille non vérifiée (références en {refs.unite}, mesure en "
                              f"{mesure['unite']})")
    v["conforme"] = not v["raisons"]
    return v


def analyser(masqueur, camera, frame_bgr, calib=None, refs=None):
    """Toutes les pièces d'une image : liste de (piece, mesure, verdict)."""
    res = []
    for p in masqueur.pieces(camera, frame_bgr):
        m = mesurer(p, frame_bgr, camera, calib)
        if m is not None:
            res.append((p, m, juger(m, refs)))
    return res


def mediane_mesures(mesures):
    """Mesure médiane (champ par champ) d'une même pièce sur plusieurs images."""
    base = dict(mesures[-1])
    for k in ("x", "y", "aire", "diametre", "solidite", "remplissage"):
        base[k] = float(np.median([m[k] for m in mesures]))
    base["teinte"] = _teinte_moyenne(np.array([m["teinte"] for m in mesures]))   # rouge : 178 ~ 2
    base["lab"] = np.median([m["lab"] for m in mesures], axis=0).tolist()
    base["couleur"] = couleur_par_teinte(base["teinte"])
    return base


def regrouper(series, distance):
    """series = liste (une par image) de listes de mesures. Regroupe les mesures d'une même pièce
    immobile (centres à moins de `distance`). Renvoie une liste de listes de mesures."""
    groupes = []
    for mesures in series:
        for m in mesures:
            for g in groupes:
                if np.hypot(g[-1]["x"] - m["x"], g[-1]["y"] - m["y"]) <= distance:
                    g.append(m)
                    break
            else:
                groupes.append([m])
    return groupes


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #
def _preparer(args):
    nom, idx = parse_cams([args.cam])[0]
    appliquer_reglages_dossier(args.fonds, {nom: idx})
    masqueur = Masqueur.charger(args.fonds)
    if nom not in masqueur.fonds:
        raise SystemExit(f"Pas de fond pour {nom} : python masquage.py capture --cams {nom}={idx}")
    calib = Calibration.charger(args.fonds)
    if not calib.a(nom):
        print(f"[ATTENTION] {nom} n'est pas calibrée : tailles en PIXELS, qui varient avec la "
              f"position. Lancez : python calibration.py cliquer --cams {nom}={idx}")
    return nom, ouvrir_camera(idx), masqueur, calib, References.charger(args.fonds)


def _texte(img, txt, pos, couleur, taille=0.45):
    # OpenCV n'affiche pas les accents : « écart » -> « ecart »
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    cv2.putText(img, txt, pos, cv2.FONT_HERSHEY_SIMPLEX, taille, (255, 255, 255), 3)
    cv2.putText(img, txt, pos, cv2.FONT_HERSHEY_SIMPLEX, taille, couleur, 1)


def commande_apprendre(args):
    nom, cap, masqueur, calib, refs = _preparer(args)
    forme = args.forme
    distance = 10.0
    lots = []          # nombre d'échantillons ajoutés à chaque espace (pour 'u')
    print(f"Posez 1 à 4 pièces OK '{forme}' ({COULEUR_ATTENDUE[forme]}), bras hors du champ. "
          f"espace = enregistrer, u = annuler le dernier, q = sauver et quitter.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            res = analyser(masqueur, nom, frame, calib, refs)
            img = frame.copy()
            for p, m, v in res:
                x1, y1, x2, y2 = p["boite"]
                cv2.rectangle(img, (x1, y1), (x2, y2), (255, 160, 0), 1)
                _texte(img, f"{v['forme']} {m['diametre']:.1f}{m['unite']} {m['couleur']}",
                       (x1, max(y1 - 4, 12)), (255, 160, 0))
            _texte(img, f"apprendre '{forme}' : {refs.nombre(forme)} echantillons | espace u q",
                   (10, 22), (0, 0, 255), 0.6)
            cv2.imshow(f"apprendre {forme}", img)
            t = cv2.waitKey(30) & 0xFF
            if t == ord(" "):
                series = []
                for _ in range(args.images):
                    ok, f = cap.read()
                    if ok:
                        series.append([m for _, m, _ in analyser(masqueur, nom, f, calib, refs)])
                groupes = [g for g in regrouper(series, distance) if len(g) >= args.images // 2]
                ajout = []
                for g in groupes:
                    m = mediane_mesures(g)
                    if m["couleur"] != COULEUR_ATTENDUE[forme] and not args.forcer:
                        print(f"  ignorée : pièce {m['couleur']} en ({m['x']:.0f}, {m['y']:.0f}) "
                              f"(une {forme} OK est {COULEUR_ATTENDUE[forme]} ; --forcer pour "
                              f"l'accepter)")
                        continue
                    f_cl, d = classer_forme(m, refs)
                    if f_cl != forme:
                        print(f"  [info] pièce en ({m['x']:.0f}, {m['y']:.0f}) ressemble plutôt à "
                              f"'{f_cl}' (écart {d:.1f}) : gardée comme '{forme}'.")
                    ajout.append(m)
                refs.ajouter(forme, ajout)
                lots.append(len(ajout))
                print(f"  +{len(ajout)} échantillon(s) : "
                      + ", ".join(f"Ø{m['diametre']:.2f}{m['unite']}" for m in ajout)
                      + f"  (total {refs.nombre(forme)})")
                mod = refs.modele(forme)
                if mod is not None:
                    print(f"  modèle : dispersion taille {mod['sigma_taille']:.2f}{refs.unite}, "
                          f"couleur {mod['sigma_couleur']:.1f}")
            elif t == ord("u") and lots:
                refs.retirer(forme, lots.pop())
                print(f"  dernier lot annulé (total {refs.nombre(forme)})")
            elif t == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print(f"Références sauvegardées -> {refs.sauver(args.fonds)}")
    for f in FORMES:
        print(f"  {f:<9} {refs.nombre(f):3d} échantillons")


def commande_verifier(args):
    nom, cap, masqueur, calib, refs = _preparer(args)
    manquantes = [f for f in FORMES if refs.modele(f) is None]
    if manquantes:
        print(f"[ATTENTION] formes non apprises (taille non vérifiée) : {', '.join(manquantes)}")
    historique = []    # [(x, y, [diamètres])] : dispersion de la mesure par pièce
    csv_f = Path(args.fonds) / "mesures.csv"
    print("Vert = OK, rouge = défaut (raison affichée). c = enregistrer les mesures dans "
          f"{csv_f}, q = quitter.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            res = analyser(masqueur, nom, frame, calib, refs)
            img = frame.copy()
            vus = []
            for p, m, v in res:
                h = next((h for h in historique if np.hypot(h[0] - m["x"], h[1] - m["y"]) < 8), None)
                if h is None:
                    h = [m["x"], m["y"], []]
                h[0], h[1] = m["x"], m["y"]
                h[2] = (h[2] + [m["diametre"]])[-30:]
                vus.append(h)
                sigma = float(np.std(h[2])) if len(h[2]) >= 5 else float("nan")
                couleur = (0, 180, 0) if v["conforme"] else (0, 0, 230)
                x1, y1, x2, y2 = p["boite"]
                cv2.rectangle(img, (x1, y1), (x2, y2), couleur, 2)
                ligne1 = f"{v['forme']} {m['diametre']:.1f}{m['unite']}"
                if v["ecart_taille_pct"] is not None:
                    ligne1 += f" ({v['ecart_taille_pct']:+.1f}%)"
                ligne2 = ("OK" if v["conforme"] else "DEFAUT: " + "; ".join(v["raisons"]))
                ligne2 += f"  sigma={sigma:.2f}"
                _texte(img, ligne1, (x1, max(y1 - 18, 12)), couleur)
                _texte(img, ligne2, (x1, max(y1 - 4, 26)), couleur, 0.4)
            historique = vus
            _texte(img, f"verifier ({nom}) : c = enregistrer, q = quitter", (10, 22), (0, 0, 255), 0.6)
            if args.echelle != 1.0:
                img = cv2.resize(img, None, fx=args.echelle, fy=args.echelle)
            cv2.imshow("verifier conformite", img)
            t = cv2.waitKey(30) & 0xFF
            if t == ord("c") and res:
                nouveau = not csv_f.exists()
                with csv_f.open("a", newline="") as fh:
                    w = csv.writer(fh)
                    if nouveau:
                        w.writerow(["horodatage", "forme", "couleur", "conforme", "raisons", "x", "y",
                                    "diametre", "unite", "ecart_taille_pct", "ecart_couleur",
                                    "solidite", "remplissage"])
                    for _, m, v in res:
                        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), v["forme"], m["couleur"],
                                    v["conforme"], " ; ".join(v["raisons"]), f"{m['x']:.1f}",
                                    f"{m['y']:.1f}", f"{m['diametre']:.2f}", m["unite"],
                                    "" if v["ecart_taille_pct"] is None else f"{v['ecart_taille_pct']:.2f}",
                                    "" if v["ecart_couleur"] is None else f"{v['ecart_couleur']:.1f}",
                                    f"{m['solidite']:.3f}", f"{m['remplissage']:.3f}"])
                print(f"  {len(res)} mesure(s) ajoutée(s) à {csv_f}")
            elif t == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbeux", action="store_true", help="messages du décodeur JPEG")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apprendre", help="enregistrer des pièces OK d'une forme")
    a.add_argument("--cam", required=True, help="caméra du dessus, ex. top=4")
    a.add_argument("--forme", required=True, choices=FORMES)
    a.add_argument("--fonds", default="fonds/")
    a.add_argument("--images", type=int, default=10, help="images moyennées par échantillon")
    a.add_argument("--forcer", action="store_true",
                   help="accepter une pièce dont la couleur ne correspond pas à la forme")
    a.set_defaults(fn=commande_apprendre)
    v = sub.add_parser("verifier", help="afficher le verdict de chaque pièce en direct")
    v.add_argument("--cam", required=True, help="caméra du dessus, ex. top=4")
    v.add_argument("--fonds", default="fonds/")
    v.add_argument("--echelle", type=float, default=1.3)
    v.set_defaults(fn=commande_verifier)
    args = ap.parse_args()
    if args.verbeux:
        args.fn(args)
    else:
        with stderr_silencieux():
            args.fn(args)
