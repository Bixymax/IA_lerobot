#!/usr/bin/env python3
"""Bilan du logiciel de conformité sur vos pièces connues.

Lecture de fonds/mesures_v2.csv (écrit par `conformite.py verifier`, touche c). Avant de lancer :
remplir à la main les colonnes
  vraie_forme : triangle / rond / hexagone / etoile   (la vérité, connue de vous)
  vraie_etat  : ok / defaut                           (la vérité, connue de vous)
Usage : python scripts/bilan_formes.py [fonds/mesures_v2.csv]
"""
import csv
import sys
from collections import Counter
from pathlib import Path

FORMES = ["triangle", "rond", "hexagone", "etoile", "inconnue"]


def main(chemin):
    lignes = list(csv.DictReader(open(chemin)))
    etiquetees = [r for r in lignes if r.get("vraie_forme")]
    if not etiquetees:
        raise SystemExit("Aucune ligne avec vraie_forme : remplissez la colonne puis relancez.")
    print(f"{len(etiquetees)} mesures étiquetées sur {len(lignes)}\n")
    print("FORME (lignes = vraie forme, colonnes = forme trouvée par le logiciel)")
    conf = Counter((r["vraie_forme"], r["forme"]) for r in etiquetees)
    print(f"{'':10s}" + "".join(f"{f[:8]:>10s}" for f in FORMES) + f"{'ambigue':>10s}")
    for vf in FORMES[:4]:
        lot = [r for r in etiquetees if r["vraie_forme"] == vf]
        if not lot:
            continue
        amb = sum(r["forme_ambigue"] == "True" for r in lot)
        print(f"{vf:10s}" + "".join(f"{conf[(vf, f)]:10d}" for f in FORMES) + f"{amb:10d}")
    if any(r.get("vraie_etat") for r in etiquetees):
        print("\nBON / DÉFECTUEUX (lignes = vérité, colonnes = logiciel)")
        c = Counter()
        for r in etiquetees:
            if not r.get("vraie_etat"):
                continue
            verdict = ("incertain" if r["incertain"] == "True"
                       else "ok" if r["conforme"] == "True" else "defaut")
            c[(r["vraie_etat"], verdict)] += 1
        print(f"{'':10s}{'ok':>10s}{'defaut':>10s}{'incertain':>10s}")
        for v in ("ok", "defaut"):
            print(f"{v:10s}" + "".join(f"{c[(v, x)]:10d}" for x in ("ok", "defaut", "incertain")))
        print("\nLes cases dangereuses : vérité=defaut / logiciel=ok (une mauvaise pièce dans le "
              "dataset échange) et vérité=ok / logiciel=defaut (une bonne pièce à la poubelle).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path("fonds/mesures_v2.csv"))
