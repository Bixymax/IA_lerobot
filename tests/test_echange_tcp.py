"""Tests du dialogue avec le Stäubli (sockets locales, sans matériel) :  python -m pytest -q"""
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import echange_tcp as E  # noqa: E402


# --------------------------------------------------------------------------- #
# Trames
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("texte, attendu", [
    ("GET-Query,Etoile", ("GET-Query", "Etoile")),
    ("ACK-Done,Cercle", ("ACK-Done", "Cercle")),
    ("ACK-NotDone,Hexagone", ("ACK-NotDone", "Hexagone")),
])
def test_trames_valides(texte, attendu):
    assert E.decoder(texte) == attendu


@pytest.mark.parametrize("texte", [
    "", "Bonjour", "GET-Query", "GET-Query,", "GET-Query,etoile", "GET-Query,Étoile",
    "GET-Query,Rond", "GET-Query,Etoile,3", "get-query,Etoile", "ACK-End",
    "GET-Respond,Etoile,NONE", "GET-Query, Etoile",
])
def test_trames_douteuses_refusees(texte):
    with pytest.raises(E.TrameInvalide):
        E.decoder(texte)


def test_format_des_nombres():
    assert E.nombre(130.5) == "130.5" and E.nombre(30) == "30.0"
    assert E.nombre(-0.04) == "0.0" and E.nombre(-12.35001) == "-12.4"
    for v in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            E.nombre(v)


def test_decoupage_des_paquets():
    d = E.Decoupeur()
    assert d.ajouter(b"GET-Qu") == []
    assert d.ajouter(b"ery,Etoile@ACK-Done,Eto") == ["GET-Query,Etoile"]
    assert d.ajouter(b"ile@\r\n") == ["ACK-Done,Etoile"]
    assert d.ajouter(b"GET-Query,Cercle@\n") == ["GET-Query,Cercle"]      # le \n précédent est ôté
    trop = d.ajouter(b"x" * 500)
    assert len(trop) == 1 and "trop longue" in trop[0] and d.tampon == b""


# --------------------------------------------------------------------------- #
# Déroulement
# --------------------------------------------------------------------------- #
class Robot:
    """Connexion factice : mémorise ce que la vision envoie."""

    def __init__(self, echange):
        self.echange, self.recu, self.panne = echange, [], False
        self.jeton = echange.connexion(self._emettre)

    def _emettre(self, octets):
        if not self.panne:
            self.recu.append(octets.decode())
        return not self.panne

    def dit(self, texte):
        self.echange.recevoir(self.jeton, texte)

    def coupe(self):
        self.echange.deconnexion(self.jeton)


def libre():
    e = E.Echange(confirmer_au_demarrage=False)
    return e, Robot(e)


def etat(e):
    return e.photo()["etat"]


def test_cycle_normal_t1_t2_du_cahier_des_charges():
    e, r = libre()
    r.dit("GET-Query,Etoile")
    p = e.photo()
    assert p["etat"] == E.PREPARATION and p["mouvement_autorise"] and r.recu == []
    assert e.envoyer_coordonnees(p["numero"], 130.5, 46.2, 30)
    assert r.recu == ["GET-Respond,Etoile,130.5,46.2,30.0@"]
    assert etat(e) == E.STAUBLI and not e.photo()["mouvement_autorise"]
    r.dit("ACK-Done,Etoile")
    assert r.recu[-1] == "ACK-End@" and etat(e) == E.LIBRE


def test_none_ne_donne_pas_la_zone_et_tolere_un_ack():
    e, r = libre()
    r.dit("GET-Query,Cercle")
    assert e.envoyer_none(e.numero)
    assert r.recu == ["GET-Respond,Cercle,NONE@"] and etat(e) == E.LIBRE
    r.dit("ACK-NotDone,Triangle")                 # autre forme : ignoré
    assert len(r.recu) == 1
    r.dit("ACK-NotDone,Cercle")
    assert r.recu[-1] == "ACK-End@" and etat(e) == E.LIBRE


def test_au_demarrage_rien_sans_l_operateur():
    e = E.Echange()
    r = Robot(e)
    r.dit("GET-Query,Etoile")
    assert etat(e) == E.BLOQUE and not e.photo()["mouvement_autorise"]
    assert not e.envoyer_coordonnees(e.numero, 1, 2, 3) and r.recu == []
    assert e.confirmer_zone_libre()
    assert etat(e) == E.PREPARATION and e.photo()["forme"] == "Etoile"
    assert not e.confirmer_zone_libre()


def test_ack_apres_redemarrage_confirme_par_l_operateur():
    e = E.Echange()
    r = Robot(e)
    r.dit("ACK-Done,Etoile")
    assert r.recu == []
    e.confirmer_zone_libre()
    assert r.recu == ["ACK-End@"] and etat(e) == E.LIBRE


def test_coordonnees_perimees_refusees():
    e, r = libre()
    r.dit("GET-Query,Etoile")
    ancien = e.numero
    r.dit("GET-Query,Cercle")                     # remplacée
    assert not e.envoyer_coordonnees(ancien, 1, 2, 3) and not e.envoyer_none(ancien)
    assert r.recu == [] and e.envoyer_coordonnees(e.numero, 1, 2, 0)
    assert not e.envoyer_coordonnees(e.numero, 1, 2, 0)            # jamais deux fois
    assert len(r.recu) == 1


def test_trame_invalide_ne_change_rien():
    e, r = libre()
    r.dit("GET-Query,Etoile")
    e.envoyer_coordonnees(e.numero, 1, 2, 3)
    r.dit("Bonjour")
    assert etat(e) == E.STAUBLI and len(r.recu) == 1


@pytest.mark.parametrize("message", ["ACK-Done,Cercle", "GET-Query,Cercle"])
def test_incoherence_pendant_la_zone_bloque(message):
    e, r = libre()
    r.dit("GET-Query,Etoile")
    e.envoyer_coordonnees(e.numero, 1, 2, 3)
    r.dit(message)
    assert etat(e) == E.BLOQUE and len(r.recu) == 1
    e.confirmer_zone_libre()
    if message.startswith("ACK"):
        assert r.recu[-1] == "ACK-End@" and etat(e) == E.LIBRE
    else:
        assert etat(e) == E.PREPARATION and e.photo()["forme"] == "Cercle"


def test_liaison_perdue_pendant_la_zone():
    e, r = libre()
    r.dit("GET-Query,Etoile")
    e.envoyer_coordonnees(e.numero, 1, 2, 3)
    r.coupe()
    assert etat(e) == E.BLOQUE
    r2 = Robot(e)                                 # la reconnexion seule ne débloque rien
    assert etat(e) == E.BLOQUE
    e.confirmer_zone_libre()
    r2.dit("ACK-Done,Etoile")                     # l'ACK arrive après le déblocage
    assert r2.recu == ["ACK-End@"] and etat(e) == E.LIBRE


def test_liaison_perdue_pendant_la_preparation_annule():
    e, r = libre()
    r.dit("GET-Query,Etoile")
    numero = e.numero
    r.coupe()
    assert etat(e) == E.LIBRE
    r2 = Robot(e)
    assert not e.envoyer_coordonnees(numero, 1, 2, 3) and r2.recu == []
    r.dit("GET-Query,Etoile")                     # ancienne connexion : ignorée
    assert etat(e) == E.LIBRE


def test_envoi_incertain_bloque():
    e, r = libre()
    r.dit("GET-Query,Etoile")
    r.panne = True
    assert not e.envoyer_coordonnees(e.numero, 1, 2, 3)
    assert etat(e) == E.BLOQUE


def test_prises_ratees_comptees_et_signalees():
    e, r = libre()
    for _ in range(E.ESSAIS_MAX):
        r.dit("GET-Query,Etoile")
        e.envoyer_coordonnees(e.numero, 1, 2, 3)
        r.dit("ACK-NotDone,Etoile")
    e.lire_evenements()
    r.dit("GET-Query,Etoile")
    assert any("ALERTE" in ligne for ligne in e.lire_evenements())
    e.envoyer_coordonnees(e.numero, 1, 2, 3)
    r.dit("ACK-Done,Etoile")
    assert e.echecs["Etoile"] == 0


# --------------------------------------------------------------------------- #
# Réseau
# --------------------------------------------------------------------------- #
@pytest.fixture
def srv():
    s = E.ServeurEchange("127.0.0.1", 0, E.Echange(confirmer_au_demarrage=False)).demarrer()
    yield s
    s.arreter()


def attendre(condition, duree=3.0):
    fin = time.monotonic() + duree
    while not condition():
        assert time.monotonic() < fin, "délai dépassé"
        time.sleep(0.01)


def client(srv):
    return socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=3)


def lire(s):
    recu = b""
    while not recu.endswith(b"@"):
        morceau = s.recv(100)
        assert morceau, "liaison fermée"
        recu += morceau
    return recu


def test_reseau_cycle_complet_sans_retour_a_la_ligne(srv):
    with client(srv) as c:
        c.sendall(b"GET-Query,Etoile@")
        attendre(lambda: srv.echange.photo()["etat"] == E.PREPARATION)
        srv.echange.envoyer_coordonnees(srv.echange.numero, 74, 105.04, 30)
        assert lire(c) == b"GET-Respond,Etoile,74.0,105.0,30.0@"
        c.sendall(b"ACK-Done,Etoile@")
        assert lire(c) == b"ACK-End@"
    attendre(lambda: not srv.echange.photo()["connecte"])
    assert srv.echange.photo()["etat"] == E.LIBRE


def test_reseau_nouvelle_connexion_remplace_l_ancienne(srv):
    with client(srv) as c1:
        c1.sendall(b"GET-Query,Etoile@")
        attendre(lambda: srv.echange.photo()["etat"] == E.PREPARATION)
        srv.echange.envoyer_coordonnees(srv.echange.numero, 1, 2, 3)
        lire(c1)
        with client(srv) as c2:
            assert c1.recv(10) == b""                        # l'ancienne est fermée
            assert srv.echange.photo()["etat"] == E.BLOQUE   # la zone était donnée
            c2.sendall(b"ACK-Done,Etoile@")
            time.sleep(0.2)
            srv.echange.confirmer_zone_libre()
            assert lire(c2) == b"ACK-End@"
