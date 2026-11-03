"""Tests du protocole d'échange (sockets locales, sans matériel) :  python -m pytest -q"""
import json
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echange_tcp import ServeurEchange  # noqa: E402


class Client:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.f = self.s.makefile("rwb")
        self.n = 0

    def envoyer(self, **msg):
        self.n += 1
        self.f.write((json.dumps({"v": 1, "id": self.n, **msg}) + "\n").encode())
        self.f.flush()

    def lire(self):
        return json.loads(self.f.readline())

    def appel(self, **msg):
        self.envoyer(**msg)
        return self.lire()


@pytest.fixture
def srv():
    s = ServeurEchange("127.0.0.1", 0).demarrer()
    yield s
    s.shutdown()
    s.server_close()


def connecte(srv):
    c = Client(srv.server_address[1])
    assert c.appel(type="HELLO", role="probo")["type"] == "HELLO_ACK"
    return c


def test_hello_obligatoire_et_version(srv):
    c = Client(srv.server_address[1])
    assert c.appel(type="PING")["code"] == "NO_HELLO"
    assert c.appel(type="HELLO", role="probo", **{"v": 1})["type"] == "HELLO_ACK"
    assert c.appel(type="PING")["type"] == "PONG"


def test_verrou_exclusif(srv):
    c = connecte(srv)
    assert c.appel(type="LOCK_REQUEST")["type"] == "LOCK_GRANTED"
    assert not srv.zone.prendre_pia(timeout=0)          # P-IA ne peut pas entrer
    assert c.appel(type="LOCK_RELEASE")["type"] == "LOCK_RELEASED"
    assert srv.zone.prendre_pia(timeout=0)
    r = c.appel(type="LOCK_REQUEST")
    assert r["type"] == "LOCK_DENIED" and r["holder"] == "pia"


def test_depot_pia_notifie_probo(srv):
    c = connecte(srv)
    assert srv.zone.prendre_pia()
    assert c.appel(type="GET_ZONE")["stable"] is False
    srv.zone.liberer_pia([{"id": 1, "forme": "etoile", "couleur": "vert", "x_mm": 12.0, "y_mm": 30.0}])
    types = {c.lire()["type"], c.lire()["type"]}
    assert types == {"ZONE_UPDATE", "LOCK_AVAILABLE"}
    z = c.appel(type="GET_ZONE")
    assert z["stable"] and z["pieces"][0]["forme"] == "etoile"


def test_piece_prise(srv):
    c = connecte(srv)
    srv.zone.pieces = [{"id": 7, "forme": "rond"}]
    assert c.appel(type="PIECE_TAKEN", piece_id=7)["code"] == "NOT_HOLDER"
    c.appel(type="LOCK_REQUEST")
    assert c.appel(type="PIECE_TAKEN", piece_id=99)["code"] == "UNKNOWN_PIECE"
    assert c.appel(type="PIECE_TAKEN", piece_id=7)["type"] == "TAKEN_ACK"
    assert srv.zone.inventaire() == []


def test_liaison_perdue_garde_le_verrou(srv):
    c = connecte(srv)
    c.appel(type="LOCK_REQUEST")
    c.s.close()
    time.sleep(0.3)
    assert not srv.zone.prendre_pia(timeout=0)          # pas de reprise automatique
    srv.zone.reinitialiser()                            # opérateur
    assert srv.zone.prendre_pia(timeout=0)


def test_json_invalide(srv):
    c = connecte(srv)
    c.f.write(b"pas du json\n")
    c.f.flush()
    assert c.lire()["code"] == "BAD_JSON"
