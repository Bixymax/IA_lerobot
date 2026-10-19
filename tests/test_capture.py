"""Tests de capture_dataset.py sur images synthétiques (sans caméra) :  python -m pytest -q"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_dataset as cd  # noqa: E402
import masquage  # noqa: E402

H, W = 480, 640


def _table(seed, gain=1.0):
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), (200, 192, 152), np.float32) * gain
    return np.clip(base + rng.normal(0, 2, base.shape), 0, 255).astype(np.uint8)


def test_camera_unique():
    assert cd.camera_unique("top=2") == ("top", 2)
    assert cd.camera_unique("4") == ("4", 4)


def test_ligne_label_normalisee():
    ligne = cd.ligne_label("hexagone", (100, 200, 140, 260), W, H)
    c, cx, cy, w, h = ligne.split()
    assert c == "2"
    assert np.allclose([float(cx), float(cy), float(w), float(h)],
                       [120 / W, 230 / H, 40 / W, 60 / H], atol=1e-5)


def test_boite_auto_une_seule_piece():
    fond, frame = _table(0), _table(1, 1.03)
    m = masquage.Masqueur({"top": fond})
    assert cd.boite_auto(m, "top", frame) is None                       # table vide
    cv2.circle(frame, (300, 200), 30, (30, 130, 240), -1)
    x1, y1, x2, y2 = cd.boite_auto(m, "top", frame)
    assert x1 < 275 and x2 > 325 and y1 < 175 and y2 > 225              # englobe la pièce
    cv2.circle(frame, (480, 300), 30, (45, 45, 200), -1)
    assert cd.boite_auto(m, "top", frame) is None                       # deux pièces : pas d'étiquette auto
    assert cd.boite_auto(None, "top", frame) is None                    # pas de fond


def test_sauver_annuler_compter(tmp_path):
    frame = _table(1)
    img, label = cd.sauver(tmp_path, frame, "triangle", False, (10, 20, 50, 60))
    assert img.exists() and label.exists()
    assert label.read_text().split()[0] == "0"
    img2, label2 = cd.sauver(tmp_path, frame, "etoile", True, None)      # défaut sans boîte auto
    assert img2.exists() and label2 is None
    cd.sauver(tmp_path, frame, None, False, None)                        # scène à plusieurs pièces
    assert cd.compter(tmp_path) == {("triangle", 0): 1, ("etoile", 1): 1}
    assert (tmp_path / "classes.txt").read_text().split() == cd.CLASSES
    cd.annuler(tmp_path, img, label)
    assert not img.exists() and not label.exists()
    assert cd.compter(tmp_path) == {("etoile", 1): 1}