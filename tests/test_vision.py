"""Tests sur images synthétiques (aucune caméra nécessaire) :  python -m pytest -q"""
import json
import sys
import types
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detection  # noqa: E402
import masquage  # noqa: E402

H, W = 480, 640
# couleurs BGR proches des vraies pièces
ROUGE, ORANGE, JAUNE, VERT = (45, 45, 200), (30, 130, 240), (40, 205, 225), (60, 170, 50)


def _table(seed=0, gain=1.0):
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), (200, 192, 152), np.float32) * gain
    return np.clip(base + rng.normal(0, 2, base.shape), 0, 255).astype(np.uint8)


def _ecart(a, b, box):
    x1, y1, x2, y2 = box
    d = np.abs(a[y1:y2, x1:x2].astype(int) - b[y1:y2, x1:x2].astype(int)).max(axis=2)
    return float((d > 25).mean())


def _scene():
    fond = _table(0)
    frame = _table(1, gain=1.03)
    cv2.fillPoly(frame, [np.array([[100, 180], [170, 180], [135, 120]], np.int32)], ROUGE)   # triangle
    cv2.circle(frame, (300, 150), 30, ORANGE, -1)                                              # rond
    cv2.circle(frame, (480, 150), 30, JAUNE, -1)                                               # "hexagone"
    cv2.circle(frame, (300, 350), 30, VERT, -1)                                                # "étoile"
    return fond, frame


def test_effacer_garde_cible_et_bras():
    fond = _table(0)
    frame = _table(1, gain=1.04)
    cv2.circle(frame, (150, 150), 28, ROUGE, -1)            # à effacer
    cv2.circle(frame, (450, 300), 25, JAUNE, -1)            # cible
    cv2.rectangle(frame, (200, 120), (240, 200), (25, 25, 25), -1)   # bras noir dans la boîte
    m = masquage.Masqueur({"top": fond})
    out = m.effacer("top", frame, [(115, 115, 245, 205)], boites_protegees=[(425, 275, 475, 325)])
    vide = _table(1, gain=1.04)
    assert _ecart(out, vide, (125, 125, 175, 175)) == 0.0
    assert np.array_equal(out[275:325, 425:475], frame[275:325, 425:475])
    assert np.array_equal(out[120:200, 200:240], frame[120:200, 200:240])


def test_table_vide_inchangee():
    fond = _table(0)
    frame = _table(3, gain=1.04)
    out = masquage.Masqueur({"top": fond}).effacer("top", frame, [(0, 0, W, H)])
    assert np.array_equal(out, frame)


def test_entree_rgb():
    fond = _table(0)
    frame = _table(1)
    cv2.circle(frame, (200, 200), 28, ROUGE, -1)
    m = masquage.Masqueur({"top": fond})
    box = [(165, 165, 235, 235)]
    bgr = m.effacer("top", frame, box)
    rgb = m.effacer("top", frame[..., ::-1].copy(), box, entree_rgb=True)
    assert np.array_equal(rgb[..., ::-1], bgr)


def test_choisir_cible():
    det = [
        {"forme": "triangle", "conforme": True, "boite": (0, 0, 10, 10)},
        {"forme": "triangle", "conforme": True, "boite": (300, 300, 310, 310)},
        {"forme": "etoile", "conforme": True, "boite": (20, 0, 30, 10)},
        {"forme": "triangle", "conforme": False, "boite": (600, 0, 610, 10)},
    ]
    cible, non = masquage.choisir_cible(det, "triangle")
    assert cible["boite"] == (300, 300, 310, 310)          # la plus isolée, conforme
    assert len(non) == 3
    assert masquage.choisir_cible(det, "hexagone")[0] is None
    assert masquage.choisir_cible([det[3]], "triangle")[0] is None   # défectueuse : jamais cible


def test_cameras_par_nom_et_migration(tmp_path, monkeypatch):
    assert masquage.parse_cams(["side=4", "top=2"]) == [("side", 4), ("top", 2)]
    for i in (0, 2, 4):
        cv2.imwrite(str(tmp_path / f"fond_cam{i}.png"), np.full((10, 10, 3), 100 + i, np.uint8))
    (tmp_path / "reglages.json").write_text(json.dumps({"2": {"exposition": 75, "balance": 3481}}))
    masquage.commande_migrer(types.SimpleNamespace(out=str(tmp_path),
                                                   cams=["side=4", "top=2", "angle45=0"]))
    assert sorted(masquage.Masqueur.charger(tmp_path).fonds) == ["angle45", "side", "top"]
    appels = []
    monkeypatch.setattr(masquage, "appliquer_reglages", lambda idx, r: appels.append(idx))
    masquage.appliquer_reglages_dossier(tmp_path, {"top": 5})
    assert appels == [5]


def test_detection_par_couleur():
    fond, frame = _scene()
    formes = sorted(d["forme"] for d in masquage.Masqueur({"top": fond}).detecter("top", frame))
    assert formes == ["etoile", "hexagone", "rond", "triangle"]


def test_montrer_forme_un_seul_triangle():
    fond, frame = _scene()
    m = masquage.Masqueur({"top": fond})
    image, pieces, cible = detection.montrer_forme(m, "top", frame, "triangle")
    assert cible is not None and cible["forme"] == "triangle"
    x1, y1, x2, y2 = cible["boite"]
    assert np.array_equal(image[y1:y2, x1:x2], frame[y1:y2, x1:x2])     # triangle intact
    vide = _table(1, gain=1.03)
    for box in [(275, 125, 325, 175), (455, 125, 505, 175), (275, 325, 325, 375)]:
        assert _ecart(image, vide, box) == 0.0                            # les autres effacées


def test_forme_absente_tout_efface():
    fond = _table(0)
    frame = _table(1, gain=1.03)
    cv2.circle(frame, (300, 150), 30, ORANGE, -1)            # seulement un rond
    m = masquage.Masqueur({"top": fond})
    image, _, cible = detection.montrer_forme(m, "top", frame, "triangle")
    assert cible is None                                      # -> "indisponible" pour P-Robo
    assert _ecart(image, _table(1, gain=1.03), (275, 125, 325, 175)) == 0.0


def test_piece_pale_sur_table_teintee():
    """Triangle rouge peu saturé (S ~ 80) sur une table bleutée (S ~ 60), avec face sombre."""
    fond = _table(0)
    frame = _table(1, gain=1.03)
    cv2.fillPoly(frame, [np.array([[230, 280], [295, 280], [262, 225]], np.int32)], (120, 120, 195))
    cv2.rectangle(frame, (230, 280), (295, 290), (50, 55, 110), -1)
    m = masquage.Masqueur({"top": fond})
    det = m.detecter("top", frame)
    assert [d["forme"] for d in det] == ["triangle"]
    out = m.effacer("top", frame, [det[0]["boite"]])
    assert _ecart(out, _table(1, gain=1.03), (228, 222, 298, 292)) == 0.0
