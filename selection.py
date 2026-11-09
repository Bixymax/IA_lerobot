"""
selection.py - choisit LA pièce que le robot doit voir, et la retrouve sur toutes les caméras.

La décision est prise sur la caméra du dessus (`top`), la seule qui voit bien la forme et la
taille. Les pièces sont suivies d'une détection à l'autre (« pistes ») et jugées sur la médiane
de leurs dernières mesures (conformite.py). Sur `side` et `angle45`, chaque pièce détectée est
rattachée à une piste de `top` par la calibration (même point de la table, calibration.py) :
deux pièces de même couleur ne sont donc plus confondues.

Modes :
  "triangle", "rond", "hexagone", "etoile" : une pièce CONFORME de cette forme (-> zone d'échange)
  "defaut"                                 : une pièce DÉFECTUEUSE, n'importe laquelle (-> poubelle)
  None                                     : aucune, toutes les pièces sont effacées

Verrouillage : une fois la cible choisie, elle ne change plus jusqu'au prochain definir() ou
nouvelle_cible() (touche du flux), même quand le bras la cache ou la déplace. Pendant le
verrou, seules les pièces présentes au moment du choix sont effacées ; ce qui apparaît ensuite
(la cible dans la pince, les câbles rouges du bras) reste visible. Après avoir replacé les
pièces entre deux épisodes, il faut donc refaire le choix (touche de la forme ou n).
"""
import threading

import cv2
import numpy as np

from masquage import SEUIL_DIFF
from conformite import analyser, couleur_par_teinte, juger, mediane_mesures

MODES = ("triangle", "rond", "hexagone", "etoile", "defaut")


def _distance_boite(p, boite):
    """Distance d'un point à une boîte (0 si dedans)."""
    x1, y1, x2, y2 = boite
    dx = max(x1 - p[0], 0, p[0] - x2)
    dy = max(y1 - p[1], 0, p[1] - y2)
    return float(np.hypot(dx, dy))


class Selection:
    def __init__(self, masqueur, calib, refs, camera_ref="top", mode=None, porte=12.0,
                 porte_cible=80.0, porte_reprise=150.0, oublier=150, memoire=7, stable=3,
                 porte_image=25.0, oubli_libre=3):
        """porte          : déplacement max (mm, ou px sans calibration) d'une pièce immobile
                            entre deux détections pour garder la même piste
           porte_cible    : idem pour la cible, qui peut être déplacée par le bras
           porte_reprise  : cible perdue de vue : une pièce nouvelle à moins de cette distance
                            de sa dernière position est la cible (dans la pince, déposée)
           oublier        : détections sans revoir une pièce avant de l'oublier (150 = 30 s à 5/s)
           memoire        : mesures gardées par pièce (verdict sur leur médiane)
           stable         : mesures minimum avant qu'une pièce puisse être choisie
           porte_image    : distance max (px) entre la projection d'une pièce et une détection
                            sur les autres caméras
           oubli_libre    : une pièce non revue dont l'emplacement est VIDE (l'image y est égale au
                            fond) est oubliée après ce nombre de détections (3 = ~1 s à 3/s). Si
                            quelque chose le recouvre (le bras), on la garde jusqu'à `oublier` ;
                            la cible n'est jamais oubliée ainsi (elle peut être dans la pince).
                            Sans cela, le cadre d'une pièce partie efface ce qui passe dedans."""
        self.masqueur = masqueur
        self.calib = calib
        self.refs = refs
        self.camera_ref = camera_ref
        self.porte, self.porte_cible, self.porte_reprise = porte, porte_cible, porte_reprise
        self.oublier, self.memoire, self.stable = oublier, memoire, stable
        self.porte_image = porte_image
        self.oubli_libre = oubli_libre
        self.verrou = threading.Lock()
        self.pistes = []
        self._prochain = 0
        self.mode = mode
        self.cible_id = None
        self.verrouille = False
        self.evenements = []          # messages pour le terminal du flux (lus par lire_evenements)

    # ---- commandes ----------------------------------------------------------
    def definir(self, mode):
        """Change de mode et relance le choix de la cible."""
        if mode is not None and mode not in MODES:
            raise ValueError(f"mode inconnu : {mode}")
        with self.verrou:
            self.mode = mode
            self._liberer()

    def nouvelle_cible(self):
        """Même mode, nouvelle cible (après avoir replacé les pièces)."""
        with self.verrou:
            self._liberer()

    def _liberer(self):
        self.cible_id = None
        self.verrouille = False
        for p in self.pistes:
            p["connue"] = True

    def lire_evenements(self):
        with self.verrou:
            ev, self.evenements = self.evenements, []
        return ev

    # ---- caméra de référence ------------------------------------------------
    def _est_une_piece(self, mesure):
        """Hors des zones de pièces (calibration.zones_pieces) : bord de table, robot, câbles...
        On ne le suit pas, donc on ne l'efface jamais."""
        if mesure.get("unite") != "mm" or self.calib is None:
            return True
        return self.calib.dans_zones_pieces((mesure["x"], mesure["y"]))

    def _unite(self):
        return "mm" if self.calib is not None and self.calib.a(self.camera_ref) else "px"

    def maj_reference(self, frame):
        """Nouvelle image de la caméra du dessus : mesure, suivi, choix de la cible."""
        dets = [{"boite": p["boite"], "mesure": m}
                for p, m, _ in analyser(self.masqueur, self.camera_ref, frame, self.calib, None)
                if self._est_une_piece(m)]
        with self.verrou:
            self._suivre(dets, self._emplacements_vides(frame))
            if not self.verrouille and self.mode is not None:
                self._choisir()

    def _emplacements_vides(self, frame):
        """Ids des pistes dont la boîte est maintenant identique au fond (la pièce n'y est plus)."""
        fond = self.masqueur.fonds.get(str(self.camera_ref))
        if fond is None or not self.pistes:
            return set()
        gain = self.masqueur._gain_lumiere(frame, fond)
        h, w = frame.shape[:2]
        vides = set()
        for p in self.pistes:
            x1, y1, x2, y2 = p["boite"]
            x1, y1, x2, y2 = max(int(x1), 0), max(int(y1), 0), min(int(x2), w), min(int(y2), h)
            if x2 - x1 < 3 or y2 - y1 < 3:
                continue
            f = cv2.GaussianBlur(frame[y1:y2, x1:x2], (5, 5), 0).astype(np.int16)
            g = cv2.GaussianBlur(self.masqueur._appliquer_gain(fond, gain, (y1, y2, x1, x2)),
                                 (5, 5), 0).astype(np.int16)
            if (np.abs(f - g).max(axis=2) > SEUIL_DIFF).mean() < 0.03:
                vides.add(p["id"])
        return vides

    def _suivre(self, dets, vides=frozenset()):
        def dist(piste, d):
            return float(np.hypot(piste["x"] - d["mesure"]["x"], piste["y"] - d["mesure"]["y"]))

        pris_p, pris_d = set(), set()
        # 1) la cible d'abord, avec une porte plus large (le bras la déplace)
        cible = self._piste(self.cible_id)
        if cible is not None and dets:
            j = min(range(len(dets)), key=lambda j: dist(cible, dets[j]))
            if dist(cible, dets[j]) <= self.porte_cible:
                self._maj_piste(cible, dets[j])
                pris_p.add(cible["id"])
                pris_d.add(j)
        # 2) les autres pièces, au plus proche
        paires = sorted((dist(p, d), p["id"], j) for p in self.pistes if p["id"] not in pris_p
                        for j, d in enumerate(dets) if j not in pris_d)
        for dd, pid, j in paires:
            if dd > self.porte or pid in pris_p or j in pris_d:
                continue
            self._maj_piste(self._piste(pid), dets[j])
            pris_p.add(pid)
            pris_d.add(j)
        # 3) cible perdue de vue : une détection nouvelle près de sa dernière position la reprend
        restes = [j for j in range(len(dets)) if j not in pris_d]
        if cible is not None and cible["id"] not in pris_p and restes:
            j = min(restes, key=lambda j: dist(cible, dets[j]))
            if dist(cible, dets[j]) <= self.porte_reprise:
                self._maj_piste(cible, dets[j])
                pris_p.add(cible["id"])
                pris_d.add(j)
        # 4) pièces non revues ; pièces nouvelles
        for p in self.pistes:
            if p["id"] not in pris_p:
                p["rates"] += 1
                # emplacement vide : la pièce est partie (sinon le bras la masque : on la garde)
                p["vide"] = p.get("vide", 0) + 1 if (p["id"] in vides and p["id"] != self.cible_id) else 0
        for j, d in enumerate(dets):
            if j not in pris_d:
                piste = {"id": self._prochain, "rates": 0, "mesures": [],
                         "connue": not self.verrouille, "vue_immobile": 0}
                self._prochain += 1
                self._maj_piste(piste, d)
                self.pistes.append(piste)
        avant = {p["id"] for p in self.pistes}
        self.pistes = [p for p in self.pistes
                       if p["rates"] <= self.oublier and p.get("vide", 0) < self.oubli_libre]
        if self.cible_id in avant and self._piste(self.cible_id) is None:
            self.evenements.append("cible perdue (plus vue depuis longtemps)")
        # une pièce apparue pendant le verrou, immobile depuis un moment : probablement posée à
        # la main -> prévenir (elle reste visible tant qu'on ne refait pas le choix)
        for p in self.pistes:
            if not p["connue"] and p["id"] != self.cible_id and p["vue_immobile"] == 10:
                self.evenements.append(f"nouvelle pièce immobile ({p['verdict']['forme']}) pendant "
                                       f"le verrou : elle reste VISIBLE. Touche n pour refaire le choix.")

    def _maj_piste(self, piste, det):
        m = det["mesure"]
        bouge = bool(piste["mesures"]) and np.hypot(piste["x"] - m["x"], piste["y"] - m["y"]) > 3
        piste["vue_immobile"] = 0 if bouge else piste.get("vue_immobile", 0) + 1
        if bouge and piste.get("id") == self.cible_id:
            piste["mesures"] = []          # la cible a été déplacée : on oublie les vieilles mesures
        piste["boite"] = det["boite"]
        piste["x"], piste["y"] = m["x"], m["y"]
        piste["mesures"] = (piste["mesures"] + [m])[-self.memoire:]
        piste["rates"] = 0
        piste["vide"] = 0
        piste["verdict"] = juger(mediane_mesures(piste["mesures"]), self.refs)

    def _piste(self, pid):
        return next((p for p in self.pistes if p["id"] == pid), None) if pid is not None else None

    def _correspond(self, p):
        v = p["verdict"]
        if self.mode == "defaut":
            return not v["conforme"]
        return v["conforme"] and v["forme"] == self.mode

    def _choisir(self):
        zone_ok = self._unite() == "mm"
        candidats = [p for p in self.pistes
                     if p["rates"] == 0 and len(p["mesures"]) >= self.stable
                     and p["vue_immobile"] >= self.stable and self._correspond(p)
                     and (not zone_ok or self.calib.dans_zone((p["x"], p["y"])))]
        if not candidats:
            return

        def isolement(p):
            autres = [np.hypot(p["x"] - o["x"], p["y"] - o["y"]) for o in self.pistes if o is not p]
            return min(autres, default=1e9)

        cible = max(candidats, key=isolement)
        self.cible_id = cible["id"]
        self.verrouille = True
        for p in self.pistes:
            p["connue"] = True
        v = cible["verdict"]
        etat = "OK" if v["conforme"] else "défaut : " + "; ".join(v["raisons"])
        self.evenements.append(f"cible : {v['forme']} #{cible['id']} en ({cible['x']:.0f}, "
                               f"{cible['y']:.0f}) {self._unite()} [{etat}]")

    # ---- consignes d'effacement ----------------------------------------------
    def consigne(self, camera, frame):
        """Ce qu'il faut faire sur cette image. Pour la caméra de référence, met aussi à jour le
        suivi. Renvoie {"cible": boîte à protéger ou None, "effacer": [boîtes],
        "annotations": [{"boite", "texte", "role"}]}  (role : cible / effacee / visible)."""
        if camera == self.camera_ref:
            self.maj_reference(frame)
            with self.verrou:
                return self._consigne_reference()
        pieces = self.masqueur.pieces(camera, frame)
        with self.verrou:
            return self._consigne_autre(camera, pieces, (frame.shape[1], frame.shape[0]))

    def _effacable(self, p):
        return p["id"] != self.cible_id and (p["connue"] or not self.verrouille)

    def _texte(self, p):
        v = p["verdict"]
        t = f"#{p['id']} {v['forme']} {'OK' if v['conforme'] else 'DEF'}"
        if v.get("ecart_taille_pct") is not None:
            t += f" {v['ecart_taille_pct']:+.1f}%"
        return t

    def _consigne_reference(self):
        cible = self._piste(self.cible_id)
        effacer, annotations = [], []
        for p in self.pistes:
            if p["rates"] > 0 and p is not cible and not self._effacable(p):
                continue
            if p is cible:
                role = "cible"
            elif self._effacable(p):
                role = "effacee"
                effacer.append(p["boite"])
            else:
                role = "visible"
            annotations.append({"boite": p["boite"], "texte": self._texte(p), "role": role})
        return {"cible": cible["boite"] if cible is not None else None, "effacer": effacer,
                "annotations": annotations}

    def _consigne_autre(self, camera, pieces, taille):
        pistes = [p for p in self.pistes if p["mesures"]]
        cible = self._piste(self.cible_id)
        rattache = {}          # index de la pièce -> piste
        ambigu = set()
        calibre = (self.calib is not None and self.calib.a(camera)
                   and self.calib.a(self.camera_ref) and self._unite() == "mm")
        if calibre and pistes:
            proj = self.calib.vers_image(camera, [(p["x"], p["y"]) for p in pistes], taille)
            couts = []
            for i, p in enumerate(pistes):
                for j, piece in enumerate(pieces):
                    d = _distance_boite(proj[i], piece["boite"])
                    if d <= self.porte_image:
                        x1, y1, x2, y2 = piece["boite"]
                        dc = float(np.hypot(proj[i][0] - (x1 + x2) / 2, proj[i][1] - (y1 + y2) / 2))
                        # la cible passe en premier : si deux pièces se chevauchent sur cette
                        # caméra, mieux vaut laisser voir une voisine qu'effacer la cible
                        couts.append((p is not cible, d, dc, i, j))
            pris_i = set()
            for _, _, _, i, j in sorted(couts):
                if i in pris_i or j in rattache:
                    continue
                rattache[j] = pistes[i]
                pris_i.add(i)
        else:
            # Sans calibration : rattachement par couleur, valable seulement si elle est unique
            for j, piece in enumerate(pieces):
                c = couleur_par_teinte(piece["teinte"])
                memes = [p for p in pistes if p["verdict"]["couleur"] == c]
                if len(memes) == 1:
                    rattache[j] = memes[0]
                elif len(memes) > 1:
                    ambigu.add(j)
        effacer, annotations, boite_cible = [], [], None
        for j, piece in enumerate(pieces):
            p = rattache.get(j)
            if p is not None and p is cible:
                role, boite_cible = "cible", piece["boite"]
            elif not self.verrouille:
                role = "effacee"                              # pas de cible : tout s'efface
            elif p is not None:
                role = "effacee" if self._effacable(p) else "visible"
            elif j in ambigu:
                c = couleur_par_teinte(piece["teinte"])
                memes = [q for q in pistes if q["verdict"]["couleur"] == c]
                role = "effacee" if all(self._effacable(q) for q in memes) else "visible"
            else:
                role = "visible"                              # inconnue : pince, câbles...
            if role == "effacee":
                effacer.append(piece["boite"])
            texte = self._texte(p) if p is not None else ("?" if j in ambigu else "non rattachee")
            annotations.append({"boite": piece["boite"], "texte": texte, "role": role})
        return {"cible": boite_cible, "effacer": effacer, "annotations": annotations}

    # ---- pour l'orchestrateur (P-Robo) ----------------------------------------
    def inventaire(self):
        """Pièces vues par la caméra du dessus : [{"id", "forme", "couleur", "conforme",
        "raisons", "x", "y", "unite", "cible"}]."""
        with self.verrou:
            return [{"id": p["id"], "forme": p["verdict"]["forme"], "couleur": p["verdict"]["couleur"],
                     "conforme": p["verdict"]["conforme"], "raisons": list(p["verdict"]["raisons"]),
                     "x": p["x"], "y": p["y"], "unite": self._unite(), "cible": p["id"] == self.cible_id}
                    for p in self.pistes if p["rates"] == 0]

    def cible(self):
        """La piste cible (dict de inventaire()) ou None."""
        return next((p for p in self.inventaire() if p["cible"]), None)
