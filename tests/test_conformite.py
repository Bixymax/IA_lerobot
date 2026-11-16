"""Tests de calibration.py, conformite.py, selection.py et du flux avec sélection, sur images
synthétiques (aucune caméra) :  python -m pytest -q"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conformite as C  # noqa: E402
from calibration import Calibration, calculer_homographie  # noqa: E402
from flux_masque import FluxMasque  # noqa: E402
from masquage import Masqueur  # noqa: E402
from selection import Selection  # noqa: E402

H, W = 480, 640
COULEURS = {"rouge": (45, 45, 200), "orange": (30, 130, 240), "jaune": (40, 205, 225),
            "vert": (60, 170, 50)}
OK = {"triangle": "rouge", "rond": "orange", "hexagone": "jaune", "etoile": "vert"}
R = 28            # rayon en px ; avec 0.5 mm/px : pièce de 28 mm de diamètre
ECHELLE = 0.5     # mm par pixel de la caméra « top » synthétique


def _table(seed):
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), (200, 192, 182), np.float32)
    return np.clip(base + rng.normal(0, 2, base.shape), 0, 255).astype(np.uint8)


def _polygone(forme, cx, cy, r, ang=0.0):
    n, rayons = {"rond": (64, None), "hexagone": (6, None), "triangle": (3, None),
                 "etoile": (10, "etoile")}[forme]
    rs = np.array([r if (rayons is None or i % 2 == 0) else 0.45 * r for i in range(n)])
    a = ang + np.arange(n) * 2 * np.pi / n - np.pi / 2
    return np.stack([cx + rs * np.cos(a), cy + rs * np.sin(a)], 1)


def _scene(pieces, seed=1):
    """pieces : [(forme, couleur, cx, cy, rayon_px, angle)]. Dessin sur-échantillonné puis
    réduit (bords anti-crénelés), léger flou d'objectif et bruit capteur."""
    grand = cv2.resize(_table(seed), None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    for forme, couleur, cx, cy, r, ang in pieces:
        pts = np.round(_polygone(forme, cx * 4, cy * 4, r * 4, ang)).astype(np.int32)
        cv2.fillPoly(grand, [pts], COULEURS[couleur], lineType=cv2.LINE_AA)
    img = cv2.GaussianBlur(cv2.resize(grand, (W, H), interpolation=cv2.INTER_AREA), (3, 3), 0.8)
    rng = np.random.default_rng(seed + 100)
    return np.clip(img.astype(np.float32) + rng.normal(0, 1.5, img.shape), 0, 255).astype(np.uint8)


def _calib():
    return Calibration({"top": {"H": np.diag([ECHELLE, ECHELLE, 1.0]), "taille": (W, H)}})


def _masqueur():
    return Masqueur({"top": _table(0)})


def _mesures(scene, calib=None):
    return [m for _, m, _ in C.analyser(_masqueur(), "top", scene, calib or _calib())]


@pytest.fixture(scope="module")
def refs():
    """Références apprises sur des pièces OK posées à 8 endroits."""
    r = C.References()
    positions = [(120, 120), (320, 110), (520, 130), (110, 360), (330, 370), (530, 350),
                 (220, 240), (430, 250)]
    for k, (x, y) in enumerate(positions):
        for forme, couleur in OK.items():
            m = _mesures(_scene([(forme, couleur, x, y, R, 0.4 * k)], seed=k + 10))
            assert len(m) == 1
            r.ajouter(forme, m)
    return r


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #
def test_calibration_aller_retour_et_resolution():
    pts_px = [(100, 80), (540, 90), (560, 420), (90, 400)]
    pts_mm = [(0, 0), (210, 0), (210, 148), (0, 148)]
    Hm, err = calculer_homographie(pts_px, pts_mm)
    assert err.max() < 1e-6
    cal = Calibration({"top": {"H": Hm, "taille": (W, H)}})
    assert np.allclose(cal.vers_table("top", pts_px), pts_mm, atol=1e-6)
    assert np.allclose(cal.vers_image("top", pts_mm), pts_px, atol=1e-6)
    # image deux fois plus grande : mêmes mm pour les mêmes points physiques
    double = np.array(pts_px) * 2
    assert np.allclose(cal.vers_table("top", double, (2 * W, 2 * H)), pts_mm, atol=1e-6)
    assert _calib().mm2_par_pixel("top", (300, 200)) == pytest.approx(ECHELLE ** 2)


def test_zone_alimentation():
    cal = Calibration({}, zone=[(0, 0), (100, 0), (100, 100), (0, 100)])
    assert cal.dans_zone((50, 50)) and not cal.dans_zone((150, 50))
    assert Calibration().dans_zone((1e6, 1e6))          # pas de zone : partout


# --------------------------------------------------------------------------- #
# Mesure et verdict
# --------------------------------------------------------------------------- #
def test_taille_en_mm_precise():
    d = _mesures(_scene([("rond", "orange", 300, 220, R, 0)]))[0]["diametre"]
    assert d == pytest.approx(2 * R * ECHELLE, abs=0.5)
    d_petit = _mesures(_scene([("rond", "orange", 300, 220, R * 0.96, 0)]))[0]["diametre"]
    assert d - d_petit == pytest.approx(2 * R * ECHELLE * 0.04, abs=0.3)      # 4 % = 1,1 mm


def test_forme_lue_au_contour_pas_a_la_couleur(refs):
    for forme in OK:
        for couleur in COULEURS:
            m = _mesures(_scene([(forme, couleur, 300, 230, R, 1.0)], seed=3))[0]
            assert C.classer_forme(m, refs)[0] == forme, (forme, couleur)


def test_pieces_ok_conformes(refs):
    for forme, couleur in OK.items():
        m = _mesures(_scene([(forme, couleur, 260, 300, R, 2.0)], seed=5))[0]
        v = C.juger(m, refs)
        assert v["conforme"], (forme, v)


def test_mauvaise_taille_defectueuse(refs):
    for forme, couleur in OK.items():
        for facteur in (0.93, 1.07):
            m = _mesures(_scene([(forme, couleur, 260, 300, R * facteur, 2.0)], seed=6))[0]
            v = C.juger(m, refs)
            assert not v["conforme"] and "taille" in v["raisons"][0], (forme, facteur, v)


def test_mauvaise_couleur_defectueuse(refs):
    for forme, bonne in OK.items():
        for couleur in COULEURS:
            if couleur == bonne:
                continue
            m = _mesures(_scene([(forme, couleur, 260, 300, R, 2.0)], seed=7))[0]
            v = C.juger(m, refs)
            assert not v["conforme"] and any("couleur" in r for r in v["raisons"]), (forme, couleur)


def test_sans_apprentissage_couleur_par_teinte():
    m = _mesures(_scene([("triangle", "vert", 300, 230, R, 0)]))[0]
    m["solidite"], m["remplissage"] = C.PROTOTYPES_FORME["triangle"]   # forme sûre
    v = C.juger(m, None)
    assert v["forme"] == "triangle" and not v["conforme"]
    assert any("taille non vérifiée" in r for r in v["remarques"])


def test_references_sauvegarde(tmp_path, refs):
    refs.sauver(tmp_path)
    r2 = C.References.charger(tmp_path)
    assert r2.nombre("etoile") == refs.nombre("etoile") == 8
    assert r2.taille_attendue("rond", 300, 200) == pytest.approx(refs.taille_attendue("rond", 300, 200))


# --------------------------------------------------------------------------- #
# Sélection multi-caméras
def test_zones_pieces():
    carre = [(0, 0), (100, 0), (100, 100), (0, 100)]
    cal = Calibration({}, zones_pieces=[carre, [(300, 0), (400, 0), (400, 100), (300, 100)]])
    assert cal.dans_zones_pieces((50, 50)) and cal.dans_zones_pieces((350, 50))
    assert cal.dans_zones_pieces((120, 50))                   # dans la marge de 30 mm
    assert not cal.dans_zones_pieces((200, 50))               # entre les zones
    assert not cal.dans_zones_pieces((50, 400))
    assert Calibration().dans_zones_pieces((1e6, 1e6))        # pas de zones : aucun filtre


# --------------------------------------------------------------------------- #
# Caméra « side » synthétique : l'image de top retournée gauche-droite, avec sa calibration.
def _side(img):
    return np.ascontiguousarray(img[:, ::-1])


def _calib2():
    flip = np.array([[-1.0, 0, W - 1], [0, 1, 0], [0, 0, 1]])
    return Calibration({"top": {"H": np.diag([ECHELLE, ECHELLE, 1.0]), "taille": (W, H)},
                        "side": {"H": np.diag([ECHELLE, ECHELLE, 1.0]) @ flip, "taille": (W, H)}})


SCENE = [("triangle", "rouge", 150, 150, R, 0.2),          # OK, isolé
         ("triangle", "rouge", 420, 300, R * 0.9, 0.5),    # trop petit
         ("etoile", "vert", 500, 330, R, 0.0)]


def _selection(refs, mode, calib=None):
    fond = _table(0)
    m = Masqueur({"top": fond, "side": _side(fond)})
    return Selection(m, calib or _calib2(), refs, mode=mode)


def _ecart(a, b, box):
    x1, y1, x2, y2 = box
    d = np.abs(a[y1:y2, x1:x2].astype(int) - b[y1:y2, x1:x2].astype(int)).max(axis=2)
    return float((d > 25).mean())


def _centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def test_selection_forme_ok_et_correspondance_side(refs):
    sel = _selection(refs, "triangle")
    img = _scene(SCENE)
    for _ in range(4):
        sel.consigne("top", img)
    cible = sel.cible()
    assert cible is not None and cible["forme"] == "triangle" and cible["conforme"]
    assert cible["x"] == pytest.approx(150 * ECHELLE, abs=2)
    inv = {p["id"]: p for p in sel.inventaire()}
    petit = next(p for p in inv.values() if p["forme"] == "triangle" and not p["cible"])
    assert not petit["conforme"]
    # sur side, deux triangles rouges : la cible est bien celle de gauche sur top (droite sur side)
    c = sel.consigne("side", _side(img))
    assert c["cible"] is not None and _centre(c["cible"])[0] == pytest.approx(W - 1 - 150, abs=5)
    assert len(c["effacer"]) == 2


def test_analyser_ignore_hors_zones():
    cal, img = _calib(), _scene(SCENE)
    assert len(_mesures(img, cal)) == 3                       # sans zones : tout est une pièce
    cal.zones_pieces = [np.array([(0, 0), (300 * ECHELLE, 0), (300 * ECHELLE, 250 * ECHELLE),
                                  (0, 250 * ECHELLE)], np.float32)]
    assert len(_mesures(img, cal)) == 1                       # apprendre / verifier : idem


def test_selection_ignore_les_objets_hors_des_zones(refs):
    # le triangle OK est à (150, 150) px, le petit triangle à (420, 300), l'étoile à (500, 330)
    cal = _calib2()
    cal.zones_pieces = [np.array([(0, 0), (300 * ECHELLE, 0), (300 * ECHELLE, 250 * ECHELLE),
                                  (0, 250 * ECHELLE)], np.float32)]
    sel = _selection(refs, "triangle", cal)
    img = _scene(SCENE)
    for _ in range(4):
        c = sel.consigne("top", img)
    inv = sel.inventaire()
    assert len(inv) == 1 and inv[0]["cible"]                 # seul le triangle de la zone est suivi
    boites_effacees = [a["boite"] for a in c["annotations"] if a["role"] == "effacee"]
    assert boites_effacees == []                            # les objets hors zone ne sont pas effacés


def test_piece_partie_oubliee_vite_mais_pas_sous_le_bras(refs):
    # deux triangles : le OK en (150, 150) px et le petit en (420, 300)
    scene2 = [SCENE[0], SCENE[1]]
    sel = _selection(refs, "triangle")
    img = _scene(scene2)
    for _ in range(4):
        sel.consigne("top", img)
    assert len(sel.inventaire()) == 2
    # le bras (gris sombre, non coloré) passe sur le petit triangle : on le garde en mémoire
    sous_bras = img.copy()
    sous_bras[300 - 50:300 + 50, 420 - 50:420 + 50] = 40
    for _ in range(8):
        sel.consigne("top", sous_bras)
    assert len(sel.pistes) == 2                       # toujours en mémoire (pas vue, mais recouverte)
    # le petit triangle est vraiment parti : table vide à cet endroit -> oublié en quelques détections
    parti = _scene([SCENE[0]])
    for _ in range(sel.oubli_libre + 1):
        sel.consigne("top", parti)
    assert len(sel.pistes) == 1 and sel.inventaire()[0]["cible"]


def test_teinte_par_canal_refuse_un_rond_jaune():
    # rond orange très variable en clarté (reflets) : l'écart global le tolérait ; la teinte, non
    rng = np.random.default_rng(3)

    def lot(lab, sig, n=40):
        return [{"x": float(rng.uniform(-150, -40)), "y": float(rng.uniform(60, 230)),
                 "diametre": 32.5 + float(rng.normal(0, 0.3)), "unite": "mm",
                 "lab": [lab[i] + float(rng.normal(0, sig[i])) for i in range(3)],
                 "solidite": 0.974, "remplissage": 0.856} for _ in range(n)]
    refs = C.References()
    refs.ajouter("rond", lot((43, 16, 41), (7, 4, 7)))
    refs.ajouter("hexagone", lot((57, -5, 36), (3, 0.5, 4)))

    def juger(lab, couleur):
        return C.juger({"solidite": 0.974, "remplissage": 0.856, "lab": lab, "couleur": couleur,
                        "x": -100.0, "y": 140.0, "diametre": 32.5, "unite": "mm"}, refs)
    orange = juger([44, 17, 40], "orange")
    jaune = juger([57, -5, 36], "jaune")
    assert orange["forme"] == "rond" and orange["conforme"]
    assert jaune["forme"] == "rond" and not jaune["conforme"]
    assert any("teinte" in r for r in jaune["raisons"])


def test_gain_local_dégradé_de_lumière():
    # la lumière baisse de 38 % sur le côté gauche (soleil, store) : sans correction locale, tout ce
    # côté « diffère du fond » (écart > seuil), forme une zone immense et les pièces sont perdues
    img = _scene(SCENE).astype(np.float32)
    rampe = np.linspace(0.62, 1.0, W, dtype=np.float32)[None, :, None]
    sombre = np.clip(img * rampe, 0, 255).astype(np.uint8)
    assert len(_mesures(sombre)) == 3
    # et une pièce n'est pas confondue avec le gradient : sa position reste juste
    xs = sorted(m["x"] for m in _mesures(sombre))
    attendu = sorted(c * ECHELLE for c in (150, 420, 500))
    assert xs == pytest.approx(attendu, abs=3)


def test_taille_non_jugee_hors_de_la_zone_apprise():
    rng = np.random.default_rng(5)
    refs = C.References()
    refs.ajouter("triangle", [{"x": float(rng.uniform(-150, -40)), "y": float(rng.uniform(60, 230)),
                               "diametre": 27.0 + float(rng.normal(0, 0.2)), "unite": "mm",
                               "lab": [20, 30, 19], "solidite": 0.948, "remplissage": 0.489}
                              for _ in range(30)])

    def juger(x, y, d):
        return C.juger({"solidite": 0.948, "remplissage": 0.489, "lab": [20, 30, 19], "couleur": "rouge",
                        "x": x, "y": y, "diametre": d, "unite": "mm"}, refs)
    assert juger(-100, 140, 27.0)["conforme"]                      # dans la zone apprise
    assert not juger(-100, 140, 22.0)["conforme"]                  # trop petit : défaut
    hors = juger(300, 100, 22.0)                                    # zone bleue : taille non jugée
    assert hors["conforme"] and any("zone apprise" in r for r in hors["remarques"])


def test_selection_defaut(refs):
    sel = _selection(refs, "defaut")
    img = _scene(SCENE)
    for _ in range(4):
        sel.consigne("top", img)
    cible = sel.cible()
    assert cible is not None and not cible["conforme"]
    assert cible["x"] == pytest.approx(420 * ECHELLE, abs=2)


def test_selection_aucune_piece_indisponible(refs):
    sel = _selection(refs, "hexagone")
    img = _scene(SCENE)
    for _ in range(4):
        c = sel.consigne("top", img)
    assert sel.cible() is None and c["cible"] is None and len(c["effacer"]) == 3


def test_verrou_cible_deplacee_et_piece_nouvelle(refs):
    sel = _selection(refs, "triangle")
    for _ in range(4):
        sel.consigne("top", _scene(SCENE))
    id_cible = sel.cible()["id"]
    # le bras déplace la cible de 60 px (30 mm) et une pièce apparaît (posée pendant l'épisode)
    bouge = [("triangle", "rouge", 210, 150, R, 0.2)] + SCENE[1:] + [("rond", "orange", 300, 400, R, 0)]
    c = sel.consigne("top", _scene(bouge, seed=2))
    assert sel.cible()["id"] == id_cible
    roles = {_centre(a["boite"]): a["role"] for a in c["annotations"]}
    rond = next(r for (x, y), r in roles.items() if abs(x - 300) < 10 and abs(y - 400) < 10)
    assert rond == "visible"                       # apparue après le choix : pas effacée
    # nouvelle cible : tout ce qui est présent redevient « connu »
    sel.nouvelle_cible()
    for _ in range(4):
        c = sel.consigne("top", _scene(bouge, seed=2))
    assert all(a["role"] != "visible" for a in c["annotations"])


def test_sans_calibration_side_rattache_par_couleur(refs):
    """side non calibrée : l'étoile (seule verte) est retrouvée ; les deux triangles rouges sont
    ambigus et, la cible étant l'un d'eux, ils restent visibles plutôt que d'effacer la cible."""
    cal = Calibration({"top": {"H": np.diag([ECHELLE, ECHELLE, 1.0]), "taille": (W, H)}})
    sel = _selection(refs, "triangle", calib=cal)
    img = _scene(SCENE)
    for _ in range(4):
        sel.consigne("top", img)
    c = sel.consigne("side", _side(img))
    assert len(c["effacer"]) == 1                  # l'étoile seulement
    assert sum(a["role"] == "visible" for a in c["annotations"]) == 2


def test_flux_avec_selection(refs):
    fond = _table(0)
    m = Masqueur({"top": fond, "side": _side(fond)})
    sel = Selection(m, _calib2(), refs)
    flux = FluxMasque(m, [("top", 0), ("side", 1)], {"top": 10, "side": 11}, forme="triangle",
                      detection_hz=0, selection=sel)
    img = _scene(SCENE)
    for _ in range(4):
        out_top = flux.traiter("top", img)
    out_side = flux.traiter("side", _side(img))
    vide = _table(1)
    assert _ecart(out_top, img, (120, 120, 180, 180)) == 0.0      # cible intacte
    assert _ecart(out_top, vide, (395, 275, 445, 325)) == 0.0     # petit triangle effacé
    assert _ecart(out_top, vide, (470, 300, 530, 360)) == 0.0     # étoile effacée
    assert _ecart(out_side, _side(img), (W - 180, 120, W - 120, 180)) == 0.0
    assert _ecart(out_side, _side(vide), (W - 445, 275, W - 395, 325)) == 0.0
    flux.choisir_forme("defaut")
    for _ in range(4):
        out_top = flux.traiter("top", img)
    assert _ecart(out_top, img, (395, 275, 445, 325)) == 0.0      # le défaut est montré
    assert _ecart(out_top, vide, (120, 120, 180, 180)) == 0.0     # le triangle OK est effacé


def test_selection_manuelle_ignore_le_verdict(refs):
    """L'opérateur désigne le petit triangle (jugé défectueux) : lui seul reste visible."""
    sel = _selection(refs, "manuel")
    img = _scene(SCENE)
    for _ in range(4):
        sel.consigne("top", img)
    assert sel.cible_id is None                       # jamais de choix automatique
    petit = next(p for p in sel.pistes if p["verdict"]["forme"] == "triangle" and not p["verdict"]["conforme"])
    assert "introuvable" in sel.choisir_piece(999)
    assert "MANUELLE" in sel.choisir_piece(petit["id"])
    c = sel.consigne("top", img)
    assert c["cible"] == petit["boite"]
    assert len(c["effacer"]) == 2


def test_verdict_incertain_pres_de_la_tolerance(refs):
    """Une pièce à la limite de la tolérance de taille est « incertaine » : jamais choisie."""
    m = _mesures(_scene([("triangle", "rouge", 320, 240, R, 0.3)]))[0]
    sur = C.juger(m, refs)
    assert sur["conforme"] and not sur["incertain"]
    ref = refs.taille_attendue("triangle", m["x"], m["y"])
    tol = sur["tol_taille_pct"]
    for facteur, incertain in ((0.5, False), (0.95, True), (1.1, True), (1.6, False)):
        m2 = {**m, "diametre": ref * (1 + facteur * tol / 100)}
        assert C.juger(m2, refs)["incertain"] is incertain, facteur
    # une forme inconnue n'est pas un vrai défaut : incertaine aussi
    m3 = {**m, "solidite": 0.3, "remplissage": 0.1, "regularite": 0.2, "harmoniques": [0.5] * 5}
    v3 = C.juger(m3, refs)
    assert v3["forme"] == "inconnue" and v3["incertain"]


def test_rond_et_hexagone_reels_pas_ambigus():
    """Régression (2026-11-16) : avec l'ancien critère (moyenne quadratique des écarts), les 11 ronds
    OK mesurés étaient tous « ambigus » face à l'hexagone et jamais sélectionnés. Statistiques
    (moyenne, écart-type) des échantillons réels appris : solidité, remplissage, régularité, h3, h5, h6."""
    stats = {"rond": ([0.976, 0.846, 0.853, 0.005, 0.006, 0.006], [0.004, 0.016, 0.019, 0.003, 0.003, 0.004]),
             "hexagone": ([0.96, 0.782, 0.81, 0.01, 0.009, 0.035], [0.005, 0.025, 0.026, 0.005, 0.004, 0.006])}

    def mesure(v):
        return {"solidite": v[0], "remplissage": v[1], "regularite": v[2],
                "harmoniques": [0, v[3], 0, v[4], v[5]], "unite": "mm", "x": 0.0, "y": 0.0,
                "diametre": 30.0, "lab": [50.0, 0.0, 0.0], "couleur": "orange"}

    rng = np.random.default_rng(0)
    refs = C.References()
    for forme, (mu, sd) in stats.items():
        refs.ajouter(forme, [mesure(rng.normal(mu, sd)) for _ in range(40)])
    for forme in ("rond", "hexagone"):
        mu, sd = stats[forme]
        v = C.juger(mesure(np.array(mu) + 0.5 * np.array(sd)), refs)
        assert v["forme"] == forme and not v["forme_ambigue"]
    # entre les deux formes (35 % du chemin du rond vers l'hexagone) : vraiment ambigu
    a, b = np.array(stats["rond"][0]), np.array(stats["hexagone"][0])
    assert C.juger(mesure(a + 0.35 * (b - a)), refs)["forme_ambigue"]


def test_nouvelle_cible_change_de_piece():
    """Régression (2026-11-16) : `n` redonnait toujours la pièce la plus isolée. Maintenant les
    cibles tournent parmi les candidats, puis recommencent quand toutes ont été choisies."""
    sel = Selection(None, None, None, mode="defaut")
    verdict = {"conforme": False, "incertain": False, "forme": "etoile", "couleur": "rouge",
               "raisons": ["couleur"]}
    sel.pistes = [{"id": i, "x": 100.0 * i, "y": 0.0, "rates": 0, "mesures": [1, 2, 3],
                   "vue_immobile": 5, "connue": True, "verdict": verdict} for i in range(3)]
    choisies = []
    for _ in range(6):
        sel.nouvelle_cible()
        sel._choisir()
        choisies.append(sel.cible_id)
    assert set(choisies[:3]) == {0, 1, 2}              # les 3 pièces, chacune une fois
    assert choisies[3:] == choisies[:3]                # puis le cycle recommence
    sel.definir("manuel")
    assert sel.deja_choisies == set()
