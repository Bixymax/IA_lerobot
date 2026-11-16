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
SIGMA_FORME_MIN = 0.012   # mesuré : remplissage d'une même pièce, écart-type ~0,007 (0,03 rendait tout ambigu)
# Vecteur de forme complet : solidité, remplissage, régularité radiale, harmoniques 3, 5 et 6 du
# profil radial (3 = triangle, 5 = étoile, 6 = hexagone). Prototypes issus d'images synthétiques
# (pièces de 28 px, flou et bruit) : ils servent seulement tant que la forme n'est pas apprise.
PROTOTYPES_VECTEUR = {"triangle": (0.95, 0.45, 0.52, 0.29, 0.00, 0.11),
                      "rond": (0.98, 0.90, 0.97, 0.00, 0.00, 0.00),
                      "hexagone": (0.97, 0.82, 0.87, 0.00, 0.00, 0.06),
                      "etoile": (0.80, 0.50, 0.50, 0.00, 0.33, 0.00)}
SIGMA_VECTEUR_MIN = np.array([0.015, 0.012, 0.015, 0.02, 0.02, 0.015])
AMBIGUITE_MIN = 4.0     # écart exigé entre la meilleure forme et la deuxième, en somme de carrés d'écarts-types
                        # (log-vraisemblance) : la moyenne quadratique diluait les 3 mesures qui séparent
                        # rond et hexagone parmi 6 et rendait tous les ronds « ambigus » (mesuré le 2026-11-16)
ZONE_INCERTAINE = (0.8, 1.25)   # écart / tolérance : dans cette plage le verdict est « incertain »


def vecteur_forme(m):
    """Mesures de forme d'une pièce (6 valeurs ; 2 si la mesure est ancienne)."""
    if "regularite" not in m:
        return [m["solidite"], m["remplissage"]]
    h = m["harmoniques"]
    return [m["solidite"], m["remplissage"], m["regularite"], h[1], h[3], h[4]]

TOLERANCES = {
    "taille_min_pct": 2.5,   # tolérance de taille minimale (± %), même si la mesure est très stable
    "taille_k": 3.0,         # sinon : k x dispersion des pièces OK autour de la référence
                             # (2 détecte mieux les petites déformations mais ne laisse plus de marge
                             # à une dérive de lumière : à n'essayer qu'avec un éclairage stable)
    # forme -> k propre à cette forme : l'étoile, dont le « diamètre » dépend de l'orientation des
    # branches, est plus dispersée (±10 % à k=3) : un k plus bas y donnerait des faux défauts
    "taille_k_par_forme": {"etoile": 3.0},
    "couleur_min": 10.0,     # écart de couleur minimal toléré (unités Lab, ~ ΔE)
    "couleur_k": 3.0,        # sinon : k x dispersion de couleur des pièces OK
    "forme_max": 6.0,        # au-delà (en écarts-types), la forme est « inconnue » -> défaut
    # Teinte (canaux a et b de Lab, sans la clarté), jugée canal par canal : la clarté et les
    # reflets d'une pièce brillante (le rond) gonflent l'écart global et laissaient passer une
    # pièce d'une autre couleur (rond jaune pris pour un rond orange).
    "teinte_k": 3.0,         # défaut si |écart a| ou |écart b| > k x dispersion de ce canal
    "teinte_sigma_min": 3.0, # dispersion plancher (unités Lab) : une forme très régulière n'est pas
                             # pour autant rejetée au moindre changement de lumière
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



def _profil_radial(contour, centre, n=72):
    """Profil r(angle) du contour autour du centre de la pièce, ramené à son rayon moyen.
    Renvoie (régularité, harmoniques) :
      régularité  = rayon 5e centile / rayon 95e centile : rond ~1, hexagone ~0,87, triangle ~0,5
      harmoniques = amplitude (relative) des harmoniques 2..6 : 3 = triangle, 5 = étoile à 5
                    branches, 6 = hexagone ; une rotation de la pièce ne les change pas.
    Insensible à la taille et à la rotation, et n'utilise que des rayons : bien plus net que
    l'aire pour distinguer un hexagone d'un rond à 28 px."""
    d = np.asarray(contour, float) - np.asarray(centre, float)
    ang, r = np.arctan2(d[:, 1], d[:, 0]), np.hypot(d[:, 0], d[:, 1])
    bins = ((ang + np.pi) / (2 * np.pi) * n).astype(int) % n
    prof = np.array([r[bins == k].max() if np.any(bins == k) else np.nan for k in range(n)])
    if np.isnan(prof).any():
        ok = ~np.isnan(prof)
        prof = np.interp(np.arange(n), np.arange(n)[ok], prof[ok], period=n)
    prof = prof / max(prof.mean(), 1e-9)
    spectre = np.abs(np.fft.rfft(prof)) / n * 2
    return (float(np.percentile(prof, 5) / np.percentile(prof, 95)),
            [float(v) for v in spectre[2:7]])


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
    regularite, harmoniques = _profil_radial(contour_t, centre)
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
            "regularite": regularite, "harmoniques": harmoniques,
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
                {k: m[k] for k in ("x", "y", "diametre", "lab", "solidite", "remplissage",
                                   "regularite", "harmoniques") if k in m})
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
        complet = all("regularite" in e for e in ech)
        f = np.array([vecteur_forme(e) if complet else [e["solidite"], e["remplissage"]]
                      for e in ech])
        centre_xy = (x.mean(), y.mean())
        degre = 2 if len(ech) >= 15 else 1 if len(ech) >= 6 else 0
        X = _base_taille((x - centre_xy[0]) / 100, (y - centre_xy[1]) / 100, degre)
        coef, *_ = np.linalg.lstsq(X, d, rcond=None)
        residus = d - X @ coef
        sigma_d = float(np.sqrt((residus ** 2).sum() / max(len(d) - X.shape[1], 1)))
        lab_ref = lab.mean(axis=0)
        sigma_ab = lab[:, 1:3].std(axis=0)
        sigma_c = float(np.sqrt(np.mean([distance_couleur(l, lab_ref) ** 2 for l in lab])))
        mod = {"n": len(ech), "degre": degre, "coef": coef, "centre_xy": centre_xy,
               "sigma_taille": max(sigma_d, 0.05), "borne_taille": (d.min(), d.max()),
               "lab": lab_ref, "sigma_couleur": sigma_c, "sigma_ab": sigma_ab,
               "zone_apprise": (float(x.min()), float(x.max()), float(y.min()), float(y.max())),
               "forme_mu": f.mean(axis=0), "forme_sigma": np.maximum(f.std(axis=0), SIGMA_VECTEUR_MIN[:f.shape[1]]
                                          if complet else SIGMA_FORME_MIN)}
        self._cache[forme] = mod
        return mod

    def dans_zone_apprise(self, forme, x, y, marge=40.0):
        """True si (x, y) est dans le rectangle des échantillons de cette forme, à `marge` mm près."""
        mod = self.modele(forme)
        if mod is None:
            return False
        x0, x1, y0, y1 = mod["zone_apprise"]
        return x0 - marge <= x <= x1 + marge and y0 - marge <= y <= y1 + marge

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
def distances_forme(mesure, refs=None):
    """Distance (en écarts-types, moyenne quadratique) de la mesure à chaque forme."""
    f = np.array(vecteur_forme(mesure), float)
    res = {}
    for forme in FORMES:
        mod = refs.modele(forme) if refs is not None else None
        if mod is not None and len(mod["forme_mu"]) == len(f):
            mu, sigma = mod["forme_mu"], mod["forme_sigma"]
        elif len(f) == 6:
            mu, sigma = np.array(PROTOTYPES_VECTEUR[forme]), SIGMA_VECTEUR_MIN * 2.5
        else:
            mu, sigma = np.array(PROTOTYPES_FORME[forme]), np.full(2, 0.04)
            f = f[:2]
        res[forme] = float(np.sqrt(np.mean(((f[:len(mu)] - mu) / sigma) ** 2)))
    return res


def classer_forme(mesure, refs=None):
    """Forme la plus proche (contour : solidité, remplissage, profil radial).
    Renvoie (forme ou None, distance)."""
    d = distances_forme(mesure, refs)
    meilleure = min(d, key=d.get)
    limite = (refs.tolerances if refs is not None else TOLERANCES)["forme_max"]
    return (meilleure if d[meilleure] <= limite else None), d[meilleure]


def juger(mesure, refs=None):
    """Verdict pour une pièce mesurée. Renvoie un dict :
      forme, couleur (nom), conforme (bool), raisons (liste de textes si défaut),
      ecart_taille_pct / tol_taille_pct (None si la taille n'a pas pu être vérifiée),
      ecart_couleur / tol_couleur, remarques (ce qui n'a pas pu être vérifié)."""
    refs = refs if refs is not None else References()
    tol = refs.tolerances
    forme, dist_forme = classer_forme(mesure, refs)
    n_mesures = len(vecteur_forme(mesure))
    dists = sorted(n_mesures * d * d for d in distances_forme(mesure, refs).values())
    ambigue = len(dists) > 1 and (dists[1] - dists[0]) < AMBIGUITE_MIN
    v = {"forme_ambigue": bool(ambigue), "incertain": False, "marge": None, "forme": forme or "inconnue", "couleur": mesure["couleur"], "conforme": False,
         "raisons": [], "remarques": [], "distance_forme": dist_forme,
         "ecart_taille_pct": None, "tol_taille_pct": None, "ecart_couleur": None, "tol_couleur": None,
         "ecart_teinte": None, "tol_teinte": None}
    if forme is None:
        v["raisons"].append("forme inconnue")
        v["incertain"] = True          # taches collées, pièce cachée... : pas un vrai défaut
        return v
    mod = refs.modele(forme)
    # --- couleur
    if mod is not None:
        dc = distance_couleur(mesure["lab"], mod["lab"])
        tc = max(tol["couleur_min"], tol["couleur_k"] * mod["sigma_couleur"])
        v["ecart_couleur"], v["tol_couleur"] = dc, tc
        if dc > tc:
            v["raisons"].append(f"couleur ({mesure['couleur']}, écart {dc:.0f} > {tc:.0f})")
        # teinte canal par canal (a, b) : voir TOLERANCES["teinte_k"]
        sab = np.maximum(mod["sigma_ab"], tol["teinte_sigma_min"])
        z = float(np.max(np.abs(np.asarray(mesure["lab"], float)[1:3] - mod["lab"][1:3]) / sab))
        v["ecart_teinte"], v["tol_teinte"] = z, tol["teinte_k"]
        if z > tol["teinte_k"] and dc <= tc:
            v["raisons"].append(f"teinte ({mesure['couleur']}, {z:.1f} sigma > {tol['teinte_k']:.0f})")
    else:
        v["remarques"].append(f"{forme} non appris : couleur jugée par la teinte")
        if mesure["couleur"] != COULEUR_ATTENDUE[forme]:
            v["raisons"].append(f"couleur {mesure['couleur']} (attendu {COULEUR_ATTENDUE[forme]})")
    # --- taille
    if mod is not None and refs.unite == mesure["unite"] and not refs.dans_zone_apprise(
            forme, mesure["x"], mesure["y"]):
        # la taille apparente change avec la position (caméra inclinée) et le modèle n'est valable
        # que là où on a appris : ailleurs (zone verte, zone bleue) on ne juge pas la taille
        v["remarques"].append("hors de la zone apprise : taille non vérifiée")
    elif mod is not None and refs.unite == mesure["unite"]:
        ref = refs.taille_attendue(forme, mesure["x"], mesure["y"])
        ecart = (mesure["diametre"] - ref) / ref * 100
        k = tol.get("taille_k_par_forme", {}).get(forme, tol["taille_k"])
        t = max(tol["taille_min_pct"], k * mod["sigma_taille"] / ref * 100)
        v["ecart_taille_pct"], v["tol_taille_pct"], v["taille_ref"] = ecart, t, ref
        if abs(ecart) > t:
            v["raisons"].append(f"taille {ecart:+.1f}% (tolérance ±{t:.1f}%)")
    elif mod is None:
        v["remarques"].append("taille non vérifiée (forme non apprise)")
    else:
        v["remarques"].append(f"taille non vérifiée (références en {refs.unite}, mesure en "
                              f"{mesure['unite']})")
    v["conforme"] = not v["raisons"]
    # Incertain : forme ambiguë, ou un contrôle (taille, teinte, couleur) à moins de 25 % de sa
    # limite, d'un côté ou de l'autre. On n'enregistre pas ces pièces (voir selection.py) : mieux
    # vaut les écarter que de risquer une mauvaise étiquette.
    rapports = [r for r in (
        abs(v["ecart_taille_pct"]) / v["tol_taille_pct"] if v["ecart_taille_pct"] is not None else None,
        v["ecart_teinte"] / v["tol_teinte"] if v["ecart_teinte"] is not None else None,
        v["ecart_couleur"] / v["tol_couleur"] if v["ecart_couleur"] is not None else None) if r is not None]
    v["marge"] = max(rapports) if rapports else None
    v["incertain"] = bool(ambigue or (v["marge"] is not None
                                      and ZONE_INCERTAINE[0] < v["marge"] < ZONE_INCERTAINE[1]))
    return v


def analyser(masqueur, camera, frame_bgr, calib=None, refs=None):
    """Toutes les pièces d'une image : liste de (piece, mesure, verdict)."""
    res = []
    for p in masqueur.pieces(camera, frame_bgr):
        m = mesurer(p, frame_bgr, camera, calib)
        if m is None:
            continue
        # hors des zones de pièces (points_table.json : zones_pieces) : bras, câbles, bord de table
        if m["unite"] == "mm" and calib is not None and not calib.dans_zones_pieces((m["x"], m["y"])):
            continue
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
    # Texte BLANC sur fond noir (lisible sur la table blanche comme sur le bras) ; `couleur` sert
    # de liseré autour du cadre (vert = OK, rouge = défaut...).
    ep = 2 if taille >= 0.55 else 1
    (w, h), base = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, taille, ep)
    x = int(max(3, min(pos[0], img.shape[1] - w - 6)))
    y = int(max(h + 5, min(pos[1], img.shape[0] - base - 4)))
    cv2.rectangle(img, (x - 3, y - h - 4), (x + w + 3, y + base + 2), (0, 0, 0), -1)
    cv2.rectangle(img, (x - 3, y - h - 4), (x + w + 3, y + base + 2), couleur, 1)
    cv2.putText(img, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, taille, (255, 255, 255), ep, cv2.LINE_AA)


def _ascii(txt):
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()


def _badge(img, n, boite, couleur):
    """Petit numéro noir sur blanc collé au-dessus du cadre d'une pièce : rien ne masque la pièce.
    Le détail de la pièce n°n est dans le bandeau du bas (voir _panneau)."""
    txt = str(n)
    (w, h), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    x, y = int(max(boite[0], 0)), int(max(boite[1] - h - 8, 0))
    cv2.rectangle(img, (x, y), (x + w + 8, y + h + 8), (0, 0, 0), -1)
    cv2.rectangle(img, (x, y), (x + w + 8, y + h + 8), couleur, 2)
    cv2.putText(img, txt, (x + 4, y + h + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
                cv2.LINE_AA)


def _panneau(img, titre, aide, lignes):
    """Colle sous l'image un bandeau NOIR : titre (jaune), aide, puis une ligne par pièce
    [(texte, couleur)] en texte blanc. Largeur de l'image respectée (texte tronqué avec ...)."""
    f, larg = cv2.FONT_HERSHEY_SIMPLEX, img.shape[1]

    def tenir(txt, taille, ep):
        txt = _ascii(txt)
        while len(txt) > 4 and cv2.getTextSize(txt, f, taille, ep)[0][0] > larg - 44:
            txt = txt[:-4] + "..."
        return txt

    h_ligne = 30
    pan = np.zeros((16 + h_ligne * (2 + len(lignes)), larg, 3), np.uint8)
    cv2.putText(pan, tenir(titre, 0.8, 2), (12, 30), f, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(pan, tenir(aide, 0.55, 1), (12, 30 + h_ligne // 1 - 4), f, 0.55, (190, 190, 190), 1,
                cv2.LINE_AA)
    for i, (txt, couleur) in enumerate(lignes):
        y = 30 + h_ligne * (i + 2) - 6
        cv2.rectangle(pan, (12, y - 14), (26, y), couleur, -1)
        cv2.putText(pan, tenir(txt, 0.65, 1), (36, y), f, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([img, pan])


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
            ech = args.echelle
            img = cv2.resize(frame, None, fx=ech, fy=ech) if ech != 1.0 else frame.copy()
            lignes = []
            for i, (p, m, v) in enumerate(res, 1):
                boite = [int(c * ech) for c in p["boite"]]
                cv2.rectangle(img, tuple(boite[:2]), tuple(boite[2:]), (255, 160, 0), 2)
                _badge(img, i, boite, (255, 160, 0))
                lignes.append((f"{i}   {v['forme']}   {m['diametre']:.1f} {m['unite']}   "
                               f"{m['couleur']}", (255, 160, 0)))
            if not res:
                lignes.append(("aucune piece detectee dans les zones", (128, 128, 128)))
            img = _panneau(img, f"apprendre '{forme}' : {refs.nombre(forme)} echantillons",
                           "[espace] enregistrer     [u] annuler le dernier     [q] sauver et quitter",
                           lignes)
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
    csv_f = Path(args.fonds) / "mesures_v2.csv"
    print("Vert = OK, rouge = défaut (raison affichée). c = enregistrer les mesures dans "
          f"{csv_f}, q = quitter.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            res = analyser(masqueur, nom, frame, calib, refs)
            ech = args.echelle
            img = cv2.resize(frame, None, fx=ech, fy=ech) if ech != 1.0 else frame.copy()
            lignes_pan = []
            vus = []
            for i, (p, m, v) in enumerate(res, 1):
                h = next((h for h in historique if np.hypot(h[0] - m["x"], h[1] - m["y"]) < 8), None)
                if h is None:
                    h = [m["x"], m["y"], [], []]
                h[0], h[1] = m["x"], m["y"]
                h[2] = (h[2] + [m["diametre"]])[-30:]
                h[3] = (h[3] + [v["conforme"]])[-15:]       # verdicts des 15 dernières images
                vus.append(h)
                sigma = float(np.std(h[2])) if len(h[2]) >= 5 else float("nan")
                n_def = h[3].count(False)
                limite = len(h[3]) >= 5 and 0 < n_def < len(h[3])     # verdict instable : frontière
                couleur = ((0, 165, 255) if limite else
                           (0, 180, 0) if v["conforme"] else (0, 0, 230))
                boite = [int(c * ech) for c in p["boite"]]
                cv2.rectangle(img, tuple(boite[:2]), tuple(boite[2:]), couleur, 2)
                _badge(img, i, boite, couleur)
                ligne = f"{i}   {v['forme']} {m['diametre']:.1f}{m['unite']}"
                if v["ecart_taille_pct"] is not None:
                    ligne += f" ({v['ecart_taille_pct']:+.1f}%)"
                if limite:
                    ligne += f"   LIMITE: defaut sur {n_def}/{len(h[3])} images"
                    if v["raisons"]:
                        ligne += " (" + "; ".join(v["raisons"]) + ")"
                else:
                    ligne += "   OK" if v["conforme"] else "   DEFAUT: " + "; ".join(v["raisons"])
                ligne += f"   sigma={sigma:.2f}"
                lignes_pan.append((ligne, couleur))
            historique = vus
            if not res:
                lignes_pan.append(("aucune piece detectee dans les zones", (128, 128, 128)))
            img = _panneau(img, f"verifier ({nom}) : vert = OK, rouge = defaut, orange = limite",
                           "[c] enregistrer les mesures     [q] quitter", lignes_pan)
            cv2.imshow("verifier conformite", img)
            t = cv2.waitKey(30) & 0xFF
            if t == ord("c") and res:
                nouveau = not csv_f.exists()
                with csv_f.open("a", newline="") as fh:
                    w = csv.writer(fh)
                    if nouveau:
                        w.writerow(["horodatage", "forme", "couleur", "conforme", "raisons", "x", "y",
                                    "diametre", "unite", "ecart_taille_pct", "ecart_couleur",
                                    "solidite", "remplissage", "ecart_teinte", "L", "a", "b",
                                    "distance_forme", "regularite", "h3", "h5", "h6",
                                    "forme_ambigue", "incertain", "marge", "vraie_forme", "vraie_etat"])
                    for _, m, v in res:
                        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), v["forme"], m["couleur"],
                                    v["conforme"], " ; ".join(v["raisons"]), f"{m['x']:.1f}",
                                    f"{m['y']:.1f}", f"{m['diametre']:.2f}", m["unite"],
                                    "" if v["ecart_taille_pct"] is None else f"{v['ecart_taille_pct']:.2f}",
                                    "" if v["ecart_couleur"] is None else f"{v['ecart_couleur']:.1f}",
                                    f"{m['solidite']:.3f}", f"{m['remplissage']:.3f}",
                                    "" if v["ecart_teinte"] is None else f"{v['ecart_teinte']:.2f}",
                                    f"{m['lab'][0]:.1f}", f"{m['lab'][1]:.1f}", f"{m['lab'][2]:.1f}",
                                    f"{v['distance_forme']:.2f}", f"{m['regularite']:.3f}",
                                    f"{m['harmoniques'][1]:.3f}", f"{m['harmoniques'][3]:.3f}",
                                    f"{m['harmoniques'][4]:.3f}", v["forme_ambigue"], v["incertain"],
                                    "" if v["marge"] is None else f"{v['marge']:.2f}", "", ""])
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
    a.add_argument("--echelle", type=float, default=1.4, help="agrandissement de la fenêtre")
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
