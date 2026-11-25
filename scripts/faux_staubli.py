"""Faux Stäubli : joue le rôle du robot (client TCP) pour essayer la cellule sans P-Robo.

    python scripts/faux_staubli.py                       # serveur sur ce PC
    python scripts/faux_staubli.py --hote 192.168.0.10

Taper une forme (e = Etoile, c = Cercle, t = Triangle, h = Hexagone). La réponse est attendue sans
limite de temps, comme sur le robot ; après des coordonnées, d = prise réussie, n = ratée.
"""
import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echange_tcp import ACK_DONE, ACK_END, ACK_NOTDONE, GET_QUERY, GET_RESPOND, PORT  # noqa: E402
from echange_tcp import Decoupeur, encoder  # noqa: E402

CHOIX = {"e": "Etoile", "c": "Cercle", "t": "Triangle", "h": "Hexagone"}


def zone_autorisee(trame, forme):
    """Même décision que le robot : True seulement pour 5 champs complets et valides."""
    champs = trame.split(",")
    if champs[:2] != [GET_RESPOND, forme] or len(champs) != 5:
        return False
    try:
        [float(v) for v in champs[2:]]
    except ValueError:
        return False
    return True


def lire(sock, decoupeur, attente):
    while not attente:
        donnees = sock.recv(1024)
        if not donnees:
            raise SystemExit("[robot] liaison fermée par la vision")
        attente += decoupeur.ajouter(donnees)
    trame = attente.pop(0)
    print(f"[robot] reçu    : {trame}@")
    return trame


def envoyer(sock, *champs):
    trame = encoder(*champs)
    sock.sendall(trame)
    print(f"[robot] envoyé  : {trame.decode()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hote", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    sock = socket.create_connection((a.hote, a.port), timeout=5)
    sock.settimeout(None)                       # pas d'expiration, comme le robot
    decoupeur, attente = Decoupeur(), []
    print(f"[robot] connecté à {a.hote}:{a.port}")
    try:
        while True:
            c = input("forme (e c t h, q) > ").strip().lower()
            if c == "q":
                break
            if c not in CHOIX:
                continue
            forme = CHOIX[c]
            envoyer(sock, GET_QUERY, forme)
            reponse = lire(sock, decoupeur, attente)
            if not zone_autorisee(reponse, forme):
                print("[robot] zone INTERDITE")
                continue
            print("[robot] zone AUTORISÉE : prise en cours")
            r = ""
            while r not in ("d", "n"):
                r = input("prise réussie (d) ou ratée (n) > ").strip().lower()
            envoyer(sock, ACK_DONE if r == "d" else ACK_NOTDONE, forme)
            if lire(sock, decoupeur, attente) != ACK_END:
                print("[robot] ERREUR : ACK-End attendu")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
