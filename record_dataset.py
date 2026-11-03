#!/usr/bin/env python3
"""
record_dataset.py
------------------------------------------------------------------
Point d'entrée pratique — équivalent à `python -m lerobot_recorder`.

Tout le code vit dans le package lerobot_recorder/ à côté de ce fichier
(config, commandes, actions, session interactive, CLI). Voir README.md
pour la structure du projet et les exemples d'utilisation.

Lancement le plus simple (menu interactif : test des bras, aperçu caméras,
enregistrement en enchaînant rapidement les séries) :

    python record_dataset.py

Toutes les options : python record_dataset.py --help
------------------------------------------------------------------
"""

from lerobot_recorder.cli import main

if __name__ == "__main__":
    main()
