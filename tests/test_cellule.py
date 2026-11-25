"""Tests de mesure_echange.py et cellule.py sur images synthétiques :  python -m pytest -q"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cellule as K  # noqa: E402
import echange_tcp as E  # noqa: E402
import mesure_echange as M  # noqa: E402
from calibration import Calibration  # noqa: E402
from flux_masque import FluxMasque  # noqa: E402
from masquage import Masqueur  # noqa: E402
from selection import Selection  # noqa: E402
from test_conformite import OK, H, W, _scene, _table, refs  # noqa: E402,F401

# caméra « top » synthétique à 1 mm par pixel (comme au local) ; pièces de 28 mm
R = 14
ZONE = (400, 130, 548, 340)             # x gauche, y haut, x droite, y bas (px = mm) : 148 x 210
ALIMENTATION = [(20, 40), (250, 40), (250, 440), (20, 440)]
POINTS = {"bleu_bas_gauche": [ZONE[0], ZONE[3]], "bleu_bas_droite": [ZONE[2], ZONE[3]],
          "bleu_haut_gauche": [ZONE[0], ZONE[1]]}


def calib():
    return Calibration({"top": {"H": np.eye(3), "taille": (W, H)}}, zone=ALIMENTATION)


def repere():
    return M.RepereEchange.depuis_points(POINTS)


def vision(refs_, **options):
    return M.VisionEchange(Masqueur({"top": _table(0)}), calib(), refs_, repere(), **options)


@pytest.fixture(scope="module")
def refs_1mm():
    """Références apprises à 1 mm/px, pièces de la taille réelle."""
    import conformite as C
    r = C.References()
    m = Masqueur({"top": _table(0)})
    for k, (x, y) in enumerate([(60, 80), (200, 90), (120, 200), (60, 330), (220, 360),
                                (130, 400), (180, 250), (90, 140)]):
        for forme, couleur in OK.items():
            mes = C.analyser(m, "top", _scene([(forme, couleur, x, y, R, 0.4 * k)], seed=k + 10),
                             calib())
            r.ajouter(forme, [mes[0][1]])
    return r


def piece(forme, x_ech, y_ech, angle=0.0, couleur=None):
    """Pièce posée à (x, y) dans fEchange."""
    return (forme, couleur or OK[forme], ZONE[0] + x_ech, ZONE[3] - y_ech, R, angle)


def releve(v, forme, scenes):
    r = M.Releve(forme, n=len(scenes))
    for s in scenes:
        r.ajouter(v.observer(s))
    return r.resultat()


def images(pieces, n=6):
    return [_scene(pieces, seed=40 + k) for k in range(n)]


# --------------------------------------------------------------------------- #
# Repère et orientation
# --------------------------------------------------------------------------- #
def test_repere_direct_origine_en_bas_a_gauche():
    r = repere()
    assert (r.largeur, r.hauteur) == (148, 210)
    assert r.vers_echange([(400, 340)])[0] == pytest.approx([0, 0])
    assert r.vers_echange([(410, 320)])[0] == pytest.approx([10, 20])    # Y vers le haut de l'image
    assert r.vers_table([(10, 20)])[0] == pytest.approx([410, 320])
    # repère direct vu de dessus : la table a y vers le bas, donc déterminant négatif
    assert np.linalg.det(np.stack([r.ex, r.ey])) == pytest.approx(-1)


def test_repere_incline_et_coins_inverses():
    a = np.radians(5)
    o = np.array([232.0, 250.0])
    x = o + 148 * np.array([np.cos(a), np.sin(a)])
    y = o + 210 * np.array([np.sin(a), -np.cos(a)])
    r = M.RepereEchange(o, x, y)
    assert r.vers_echange([x, y]) == pytest.approx(np.array([[148, 0], [0, 210]]), abs=1e-9)
    with pytest.raises(ValueError):
        M.RepereEchange((0, 0), (100, 0), (0, 100))          # « haut » placé en bas
    with pytest.raises(ValueError, match="manquants"):
        M.RepereEchange.depuis_points({})


def test_points_du_projet():
    import json
    f = Path(__file__).resolve().parents[1] / "fonds" / "points_table.json"
    if not f.exists():
        pytest.skip("pas de points_table.json")
    r = M.RepereEchange.depuis_points(json.loads(f.read_text())["points"])
    assert r.largeur > 100 and r.hauteur > 100


@pytest.mark.parametrize("forme", ["triangle", "etoile", "hexagone"])
def test_orientation_et_position(refs_1mm, forme):
    """_polygone : angle 0 = une pointe vers le haut de l'image (+Y), angle positif horaire."""
    v = vision(refs_1mm)
    periode = 360 / M.SYMETRIE[forme]
    for angle in (0.0, 0.3, 1.0, 2.2, 4.0):
        r = releve(v, forme, images([piece(forme, 70.0, 110.0, angle)]))
        assert r.ok, (forme, angle, r.raison)
        attendu = (-np.degrees(angle)) % periode
        ecart = (r.rz - attendu + periode / 2) % periode - periode / 2
        assert abs(ecart) < 2.5 and 0 <= r.rz < periode, (forme, angle, r.rz, attendu)
        assert (r.x, r.y) == (pytest.approx(70, abs=1), pytest.approx(110, abs=1))


def test_rond_rz_nul(refs_1mm):
    r = releve(vision(refs_1mm), "rond", images([piece("rond", 40, 60, 0.7)]))
    assert r.ok and r.rz == 0.0


def test_correction_de_hauteur(refs_1mm):
    img = images([piece("rond", 140, 200)])
    brut = releve(vision(refs_1mm), "rond", img)
    corrige = releve(vision(refs_1mm, hauteur_camera=500, epaisseur=10), "rond", img)
    pied = repere().vers_echange([(W / 2, H / 2)])[0]
    attendu = pied + (np.array([brut.x, brut.y]) - pied) * 0.98
    assert (corrige.x, corrige.y) == pytest.approx(tuple(attendu), abs=0.05)
    with pytest.raises(ValueError):
        vision(refs_1mm, epaisseur=10)


# --------------------------------------------------------------------------- #
# Refus de mesure
# --------------------------------------------------------------------------- #
def test_zone_vide_ou_mauvaise_piece(refs_1mm):
    v = vision(refs_1mm)
    r = releve(v, "etoile", images([]))
    assert not r.ok and r.absente
    r = releve(v, "etoile", images([piece("triangle", 70, 100)]))
    assert not r.ok and r.absente and "triangle" in r.raison
    # étoile rouge (défectueuse) : pas la pièce demandée
    assert not releve(v, "etoile", images([piece("etoile", 70, 100, couleur="rouge")])).ok
    # étoile restée dans l'alimentation : elle n'est pas dans la zone
    assert releve(v, "etoile", images([("etoile", "vert", 100, 200, R, 0)])).absente


def test_bras_au_dessus_de_la_zone(refs_1mm):
    scenes = images([piece("etoile", 40, 60)])
    for s in scenes:
        cv2.rectangle(s, (470, 140), (540, 230), (40, 40, 40), -1)       # bras (non coloré)
    r = releve(vision(refs_1mm), "etoile", scenes)
    assert not r.ok and not r.absente and "zone" in r.raison


def test_piece_qui_bouge_ou_en_double(refs_1mm):
    v = vision(refs_1mm)
    r = releve(v, "etoile", [_scene([piece("etoile", 40 + 3 * k, 60)], seed=k) for k in range(6)])
    assert not r.ok and "bouge" in r.raison
    r = releve(v, "triangle", [_scene([piece("triangle", 70, 100, 0.1 * k)], seed=k)
                               for k in range(6)])
    assert not r.ok and "orientation" in r.raison
    r = releve(v, "rond", images([piece("rond", 40, 60), piece("rond", 100, 150)]))
    assert not r.ok and "plusieurs" in r.raison


def test_moyenne_des_angles_autour_de_zero(refs_1mm):
    # hexagone à cheval sur 0 / 60 degrés : la moyenne ne doit pas tomber à 30
    scenes = [_scene([piece("hexagone", 70, 100, a)], seed=k)
              for k, a in enumerate((0.012, -0.012, 0.012, -0.012))]
    r = releve(vision(refs_1mm), "hexagone", scenes)
    assert r.ok and min(r.rz, 60 - r.rz) < 2


# --------------------------------------------------------------------------- #
# Programmes LeRobot en cours
# --------------------------------------------------------------------------- #
def test_processus_bras(tmp_path):
    lignes = {1: ["/env/bin/python3.12", "/env/bin/lerobot-rollout", "--x"],
              2: ["nano", "lerobot-record"],
              3: ["python", "-m", "lerobot.scripts.lerobot_teleoperate"],
              4: ["/usr/bin/bash", "-c", "echo lerobot-record"],
              5: ["lerobot-record"]}
    for pid, args in lignes.items():
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "cmdline").write_bytes("\0".join(args).encode() + b"\0")
    assert K.processus_bras(tmp_path) == ["lerobot-record", "lerobot-rollout", "lerobot-teleoperate"]


# --------------------------------------------------------------------------- #
# Cellule complète : vrai flux, vraie vision, vrai dialogue ; caméra et robot simulés
# --------------------------------------------------------------------------- #
class Banc:
    def __init__(self, refs_, pieces, **options):
        m = Masqueur({"top": _table(0)})
        cal = calib()
        sel = Selection(m, cal, refs_)
        self.flux = FluxMasque(m, [("top", 0)], {"top": 11}, forme=None, detection_hz=0,
                               selection=sel)
        self.echange = E.Echange(confirmer_au_demarrage=False)
        self.recu, self.procs, self.t, self.seq = [], [], 0.0, 0
        self.jeton = self.echange.connexion(lambda b: self.recu.append(b.decode()) or True)
        self.cellule = K.Cellule(self.echange, self.flux, vision(refs_, ),
                                 processus=lambda: list(self.procs), horloge=lambda: self.t,
                                 **options)
        self.pieces = pieces

    def tourner(self, secondes):
        for _ in range(int(round(secondes / 0.2))):
            self.t += 0.2
            self.seq += 1
            image = _scene(self.pieces, seed=self.seq % 7)
            self.flux.etat["top"]["brute"] = (self.seq, image)
            self.flux.etat["top"]["image"] = self.flux.traiter("top", image)
            self.cellule.tick()

    def robot(self, texte):
        self.echange.recevoir(self.jeton, texte)


ALIM = ("etoile", "vert", 100, 200, R, 0.0)


def test_cycle_en_deux_etapes(refs_1mm):
    b = Banc(refs_1mm, [ALIM])
    b.tourner(1)
    b.robot("GET-Query,Etoile")
    b.tourner(2)
    assert b.flux.forme == "etoile" and b.flux.selection.verrouille and b.recu == []
    # le modèle tourne : v est refusé
    b.procs = ["lerobot-rollout"]
    b.tourner(1)
    b.cellule.touche("v")
    assert "REFUSÉ" in b.cellule.message and not b.cellule.mesure_en_cours
    # le modèle a posé la pièce dans la zone et s'est arrêté
    b.pieces = [piece("etoile", 70, 110, 0.3)]
    b.procs = []
    b.tourner(1)
    assert b.recu == []                                   # rien sans la validation
    b.cellule.touche("v")
    b.tourner(3)
    assert len(b.recu) == 1, b.cellule.message
    champs = b.recu[0].rstrip("@").split(",")
    assert champs[:2] == ["GET-Respond", "Etoile"]
    x, y, rz = map(float, champs[2:])
    assert x == pytest.approx(70, abs=1) and y == pytest.approx(110, abs=1)
    assert rz == pytest.approx((-np.degrees(0.3)) % 72, abs=2.5)
    assert b.echange.photo()["etat"] == E.STAUBLI and b.flux.forme is None
    assert b.cellule.alerte == ""
    b.procs = ["lerobot-teleoperate"]                     # interdit maintenant
    b.tourner(1)
    assert "ARRÊTEZ" in b.cellule.alerte
    b.procs = []
    b.robot("ACK-Done,Etoile")
    b.tourner(1)
    assert b.recu[-1] == "ACK-End@" and b.echange.photo()["etat"] == E.LIBRE
    # l'aperçu se compose sans erreur
    assert K.composer(b.flux, b.cellule, ["une ligne"]).ndim == 3


def test_modele_demarre_pendant_la_mesure(refs_1mm):
    b = Banc(refs_1mm, [piece("etoile", 70, 110)])
    b.robot("GET-Query,Etoile")
    b.tourner(1)
    b.cellule.touche("v")
    b.tourner(0.4)
    b.procs = ["lerobot-rollout"]
    b.tourner(3)
    assert b.recu == [] and not b.cellule.mesure_en_cours


def test_none_automatique_si_aucune_piece(refs_1mm):
    b = Banc(refs_1mm, [("triangle", "rouge", 100, 200, R, 0)], delai_none=3.0)
    b.robot("GET-Query,Etoile")
    b.tourner(2)
    assert b.recu == []
    b.tourner(3)
    assert b.recu == ["GET-Respond,Etoile,NONE@"] and "triangle" in b.cellule.message


def test_none_desactive_ou_manuel(refs_1mm):
    b = Banc(refs_1mm, [], delai_none=0)
    b.robot("GET-Query,Etoile")
    b.tourner(8)
    assert b.recu == []
    b.cellule.touche("x")
    assert b.recu == ["GET-Respond,Etoile,NONE@"]


def test_piece_deja_dans_la_zone(refs_1mm):
    b = Banc(refs_1mm, [piece("etoile", 70, 110)], delai_none=2.0)
    b.robot("GET-Query,Etoile")
    b.tourner(5)
    assert b.recu == [] and b.cellule.deja_dans_zone       # pas de NONE, pas d'envoi seul
    assert "déjà dans la zone" in b.cellule.consigne()
    b.cellule.touche("v")
    b.tourner(3)
    assert b.recu[0].startswith("GET-Respond,Etoile,")


def test_deux_essais_puis_alerte_sans_coordonnees(refs_1mm):
    b = Banc(refs_1mm, [ALIM])
    b.robot("GET-Query,Etoile")
    b.tourner(2)
    b.cellule.touche("v")
    b.tourner(3)
    assert "Second essai" in b.cellule.message
    b.cellule.touche("n")
    b.tourner(1)
    b.cellule.touche("v")
    b.tourner(3)
    assert "ALERTE" in b.cellule.message
    b.tourner(10)
    assert b.recu == [] and b.echange.photo()["etat"] == E.PREPARATION


def test_images_inchangees_pendant_que_le_modele_tourne(refs_1mm):
    b = Banc(refs_1mm, [ALIM])
    b.robot("GET-Query,Etoile")
    b.tourner(1)
    b.procs = ["lerobot-rollout"]
    b.tourner(1)
    b.echange.deconnexion(b.jeton)                         # liaison perdue en plein geste
    b.tourner(1)
    assert b.flux.forme == "etoile"
    b.procs = []
    b.tourner(1)
    assert b.flux.forme is None


def test_camera_figee(refs_1mm):
    b = Banc(refs_1mm, [piece("etoile", 70, 110)])
    b.robot("GET-Query,Etoile")
    b.tourner(1)
    b.cellule.touche("v")
    for _ in range(40):                                    # plus aucune image
        b.t += 0.2
        b.cellule.tick()
    assert b.recu == [] and "figée" in b.cellule.message
