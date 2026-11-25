"""
mesure_echange.py - mesure, avec la caméra `top`, la pièce posée dans la zone d'échange : position
dans le repère fEchange et orientation RZ, à envoyer au Stäubli (voir docs/protocole_tcp.md).

Repère fEchange (rectangle bleu de la nappe, tel que vu par `top`) :
  origine = coin BAS GAUCHE (côté SO-101) ; X vers la droite ; Y vers le haut de l'image ;
  Z vers le plafond (repère direct). Unité : mm.
RZ : degrés, sens antihoraire vu de dessus ; 0 = une pointe de la pièce vers +Y. Une forme
régulière se superpose à elle-même : RZ est donné entre 0 et 120 (triangle), 72 (étoile),
60 (hexagone) ; toujours 0 pour le rond.

Correction de hauteur (facultative) : la calibration vaut au niveau de la table, or `top` voit le
DESSUS des pièces, décalé vers l'extérieur de l'image. Avec la hauteur de la caméra et
l'épaisseur des pièces, on ramène le point vers la verticale de la caméra (supposée sous le centre
de l'image).
"""
from dataclasses import dataclass, field

import cv2
import numpy as np

from conformite import COULEUR_ATTENDUE, distances_forme, juger, mesurer, segmenter
from masquage import SEUIL_DIFF

# nombre de répétitions de la forme sur un tour
SYMETRIE = {"triangle": 3, "etoile": 5, "hexagone": 6}
DIAMETRE_MAX = 45.0          # mm : au-delà, la tache n'est pas une pièce (bras, câbles collés)


class RepereEchange:
    def __init__(self, origine, bout_x, bout_y):
        """Trois points de la TABLE (mm, repère de points_table.json) : coin bas gauche, coin bas
        droit, coin haut gauche de la zone d'échange."""
        self.origine = np.asarray(origine, float)
        vx = np.asarray(bout_x, float) - self.origine
        vy = np.asarray(bout_y, float) - self.origine
        self.largeur, self.hauteur = float(np.linalg.norm(vx)), float(np.linalg.norm(vy))
        if min(self.largeur, self.hauteur) < 1:
            raise ValueError("zone d'échange dégénérée")
        self.ex = vx / self.largeur
        # la table a son y vers le bas de l'image : (ex_y, -ex_x) donne un repère DIRECT vu de
        # dessus (Z vers le plafond), exactement perpendiculaire à X
        self.ey = np.array([self.ex[1], -self.ex[0]])
        if float(self.ey @ vy) <= 0:
            raise ValueError("coins de la zone d'échange inversés : origine = bas gauche, puis bas "
                             "droit, puis haut gauche (vus par top)")

    @classmethod
    def depuis_points(cls, points, prefixe="bleu"):
        """`points` : clé "points" de fonds/points_table.json."""
        noms = [f"{prefixe}_{c}" for c in ("bas_gauche", "bas_droite", "haut_gauche")]
        manquants = [n for n in noms if n not in points]
        if manquants:
            raise ValueError(f"points_table.json : repères manquants : {', '.join(manquants)}")
        return cls(*(points[n] for n in noms))

    def vers_echange(self, points_table):
        d = np.asarray(points_table, float).reshape(-1, 2) - self.origine
        return np.stack([d @ self.ex, d @ self.ey], 1)

    def vers_table(self, points_echange):
        p = np.asarray(points_echange, float).reshape(-1, 2)
        return self.origine + p[:, :1] * self.ex + p[:, 1:] * self.ey

    def contient(self, point_echange):
        x, y = point_echange
        return 0 <= x <= self.largeur and 0 <= y <= self.hauteur

    def coins_table(self):
        L, H = self.largeur, self.hauteur
        return self.vers_table([(0, 0), (L, 0), (L, H), (0, H)])


def orientation(forme, points_echange):
    """RZ (degrés) d'une pièce, d'après les points qui la remplissent (repère fEchange).

    Le moment complexe somme((x + iy)^n) d'une forme à symétrie n a pour argument n fois l'angle
    d'une pointe : toute la surface contribue, pas seulement quelques pixels du bord."""
    n = SYMETRIE.get(forme)
    if n is None:
        return 0.0
    p = np.asarray(points_echange, float)
    p = p - p.mean(axis=0)
    moment = np.sum((p[:, 0] + 1j * p[:, 1]) ** n)
    return float((np.degrees(np.angle(moment)) / n - 90) % (360 / n))


@dataclass
class Observation:
    pieces: list = field(default_factory=list)     # pièces dont le centre est dans la zone
    encombrement: float = 0.0                      # part de la zone qui diffère du fond, hors pièces


class VisionEchange:
    def __init__(self, masqueur, calib, refs, repere, camera="top", hauteur_camera=None,
                 epaisseur=None):
        if camera not in masqueur.fonds:
            raise ValueError(f"pas de fond pour la caméra {camera}")
        if not calib.a(camera):
            raise ValueError(f"caméra {camera} non calibrée : pas de coordonnées en mm possibles")
        if (hauteur_camera is None) != (epaisseur is None):
            raise ValueError("correction de hauteur : donner la hauteur de caméra ET l'épaisseur")
        if hauteur_camera is not None and not 0 <= epaisseur < hauteur_camera:
            raise ValueError("épaisseur et hauteur de caméra incohérentes")
        self.masqueur, self.calib, self.refs = masqueur, calib, refs
        self.repere, self.camera = repere, camera
        self.rapport = 1.0 if hauteur_camera is None else 1 - epaisseur / hauteur_camera

    def _corriger(self, points_table, taille_image):
        if self.rapport == 1.0:
            return points_table
        w, h = taille_image
        pied = self.calib.vers_table(self.camera, [(w / 2, h / 2)], taille_image)[0]
        return pied + (points_table - pied) * self.rapport

    def observer(self, frame):
        taille = (frame.shape[1], frame.shape[0])
        pieces, couvert = [], np.zeros(frame.shape[:2], np.uint8)
        for p in self.masqueur.pieces(self.camera, frame):
            m = mesurer(p, frame, self.camera, self.calib)
            if m is None or m["diametre"] > DIAMETRE_MAX:
                continue
            plein = segmenter(p, frame)[0]
            ys, xs = np.nonzero(plein)
            ox, oy = p["origine"]
            couvert[ys + oy, xs + ox] = 255
            brut = np.array([m["x"], m["y"]])
            centre = self.repere.vers_echange(self._corriger(brut, taille))[0]
            if not self.repere.contient(centre):
                continue
            v = juger(m, self.refs)
            contour = self.calib.vers_table(self.camera, np.stack([xs + ox, ys + oy], 1), taille)
            pieces.append({"forme": v["forme"], "couleur": v["couleur"], "conforme": v["conforme"],
                           "raisons": v["raisons"], "ambigue": v["forme_ambigue"],
                           "distances": distances_forme(m, self.refs), "mesure": m,
                           "x": float(centre[0]), "y": float(centre[1]), "table": brut,
                           "points": self.repere.vers_echange(contour)})
        return Observation(pieces, self._encombrement(frame, couvert))

    def _encombrement(self, frame, couvert):
        """Part de la zone d'échange où l'image diffère de la table vide, pièces exclues : le bras
        du SO-101 (ou une main) au-dessus de la zone."""
        taille = (frame.shape[1], frame.shape[0])
        coins = self.calib.vers_image(self.camera, self.repere.coins_table(), taille)
        zone = np.zeros(frame.shape[:2], np.uint8)
        cv2.fillPoly(zone, [np.round(coins).astype(np.int32)], 255)
        if not zone.any():
            return 1.0                    # zone hors de l'image : on ne peut rien garantir
        fond = self.masqueur._fond_ajuste(frame, self.masqueur.fonds[self.camera])
        diff = np.abs(cv2.GaussianBlur(frame, (5, 5), 0).astype(np.int16)
                      - cv2.GaussianBlur(fond, (5, 5), 0).astype(np.int16)).max(axis=2)
        pieces = cv2.dilate(couvert, np.ones((5, 5), np.uint8), iterations=3)   # bords et ombre
        return float(((diff > SEUIL_DIFF) & (zone > 0) & (pieces == 0)).sum() / (zone > 0).sum())


def correspond(piece, forme):
    """La pièce vue est-elle la forme demandée ? La couleur (propre à chaque forme conforme) ET le
    contour doivent concorder ; un contour hésitant entre deux formes (rond / hexagone) est admis
    si la forme demandée est l'une des deux."""
    if piece["couleur"] != COULEUR_ATTENDUE[forme]:
        return False
    if piece["forme"] == forme:
        return True
    return piece["ambigue"] and forme in sorted(piece["distances"], key=piece["distances"].get)[:2]


@dataclass
class Resultat:
    ok: bool
    raison: str = ""
    absente: bool = False          # la pièce demandée n'est pas dans la zone (zone dégagée)
    x: float = 0.0
    y: float = 0.0
    rz: float = 0.0
    remarques: list = field(default_factory=list)


class Releve:
    """Accumule des observations (images différentes) et ne rend des coordonnées que si TOUTES
    concordent : zone dégagée, une seule pièce de la forme demandée, immobile."""

    def __init__(self, forme, n=8, ecart_position=1.5, ecart_angle=5.0, seuil_encombrement=0.02):
        self.forme, self.n = forme, n
        self.ecart_position, self.ecart_angle = ecart_position, ecart_angle
        self.seuil = seuil_encombrement
        self.observations = []

    def ajouter(self, observation):
        self.observations.append(observation)

    @property
    def complet(self):
        return len(self.observations) >= self.n

    def resultat(self):
        if not self.complet:
            return Resultat(False, f"seulement {len(self.observations)} images sur {self.n}")
        pire = max(o.encombrement for o in self.observations)
        if pire > self.seuil:
            return Resultat(False, f"quelque chose est dans la zone d'échange (bras ?) : "
                                   f"{pire:.0%} de la zone, limite {self.seuil:.0%}")
        candidats = [[p for p in o.pieces if correspond(p, self.forme)] for o in self.observations]
        if not any(candidats):
            vues = {f"{p['forme']} {p['couleur']}" for o in self.observations for p in o.pieces}
            return Resultat(False, f"pas de {self.forme} dans la zone d'échange"
                            + (f" (vu : {', '.join(sorted(vues))})" if vues else ""), absente=True)
        if any(len(c) > 1 for c in candidats):
            return Resultat(False, f"plusieurs pièces « {self.forme} » dans la zone : n'en laisser "
                                   f"qu'une")
        if not all(candidats):
            return Resultat(False, f"{self.forme} vu sur certaines images seulement : pièce cachée "
                                   f"ou lecture instable")
        pieces = [c[0] for c in candidats]
        xy = np.array([(p["x"], p["y"]) for p in pieces])
        centre = np.median(xy, axis=0)
        dispersion = float(np.max(np.hypot(*(xy - centre).T)))
        if dispersion > self.ecart_position:
            return Resultat(False, f"la pièce bouge ou la mesure varie ({dispersion:.1f} mm)")
        rz = 0.0
        n = SYMETRIE.get(self.forme)
        if n:
            periode = 360 / n
            angles = np.array([orientation(self.forme, p["points"]) for p in pieces])
            # moyenne circulaire sur la période de la forme (59° et 1° sont voisins pour l'hexagone)
            moyenne = np.angle(np.mean(np.exp(1j * np.radians(angles * n)))) / n
            ecarts = (angles - np.degrees(moyenne) + periode / 2) % periode - periode / 2
            if np.max(np.abs(ecarts)) > self.ecart_angle:
                return Resultat(False, f"orientation instable (± {np.max(np.abs(ecarts)):.0f}°)")
            rz = float(round(np.degrees(moyenne) % periode, 1) % periode)
        remarques = []
        if len(self.observations[-1].pieces) > 1:
            remarques.append("une autre pièce est aussi dans la zone d'échange")
        if not pieces[-1]["conforme"]:
            remarques.append("verdict dans la zone d'échange : " + "; ".join(pieces[-1]["raisons"]))
        return Resultat(True, x=float(centre[0]), y=float(centre[1]), rz=rz, remarques=remarques)
