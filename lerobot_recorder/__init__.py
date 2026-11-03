"""lerobot_recorder — outils pour enregistrer un dataset LeRobot (bras SO101, 3 caméras).

Organisation du package :
  config.py    -> réglages par défaut (bras, caméras, dataset)
  system.py    -> utilitaires bas niveau (vérifs, exécution de commandes, Hugging Face)
  commands.py  -> construction des commandes lerobot-teleoperate / lerobot-record
  ui.py        -> petits helpers d'affichage terminal
  actions.py   -> actions ponctuelles (find-ports, find-cameras, test des bras, preview, record direct)
  session.py   -> menu interactif (enchaînement rapide des prises)
  cli.py       -> argparse + point d'entrée `main()`
"""

__version__ = "1.0.0"
