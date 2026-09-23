# LeRobot Recorder

Outils pour enregistrer facilement un dataset LeRobot (bras SO101 unique,
follower + leader) avec 3 caméras (`front`, `wrist`, `side`), en s'appuyant
sur `lerobot-teleoperate` / `lerobot-record`.

Sources :
- https://huggingface.co/docs/lerobot/en/il_robots
- https://xlerobot.readthedocs.io/en/latest/software/getting_started/VLA_smol.html

## Structure du projet

```
.
├── record_dataset.py           # point d'entrée pratique
└── lerobot_recorder/
    ├── __init__.py
    ├── __main__.py              # permet `python -m lerobot_recorder`
    ├── config.py                # réglages par défaut (bras / caméras / dataset)
    ├── system.py                # vérifs système, exécution de commandes, Hugging Face
    ├── commands.py               # construction des commandes lerobot-*
    ├── ui.py                     # affichage terminal (bannières, rappels clavier)
    ├── actions.py                 # actions ponctuelles (test bras, preview, record direct)
    ├── session.py                 # menu interactif (enchaînement rapide des prises)
    └── cli.py                     # argparse + dispatch
```

Chaque fichier a une seule responsabilité : `config.py` ne fait que décrire
les réglages, `commands.py` ne fait qu'assembler des listes d'arguments
(testable sans matériel via `--dry-run`), `system.py` gère l'exécution et les
vérifications, `actions.py`/`session.py` orchestrent, `cli.py` fait le lien
avec la ligne de commande.

## Installation

Aucune dépendance en dehors de LeRobot lui-même :

```bash
conda activate lerobot
```

Place `record_dataset.py` et le dossier `lerobot_recorder/` dans le même
répertoire (ex: `~/projetIArobot/`).

## Démarrage rapide

```bash
cd ~/projetIArobot
conda activate lerobot

python record_dataset.py --find-ports     # trouver PORT_FOLLOWER / PORT_LEADER
python record_dataset.py --find-cameras   # trouver les index des 3 caméras

python record_dataset.py                  # menu interactif
```

Le menu interactif :

```
[1] Tester les bras (téléopération simple, sans caméras)
[2] Prévisualiser les caméras (téléopération + caméras)
[3] Enregistrer une série d'épisodes
[4] Quitter
```

- **[1]** lance `lerobot-teleoperate` sans caméras : bouge le bras leader et
  vérifie que le follower suit bien, avant même de brancher les caméras.
- **[2]** lance `lerobot-teleoperate` avec les 3 caméras et l'affichage live
  (Rerun), sans créer de dataset — pour vérifier le cadrage.
- **[3]** demande la tâche et le nombre d'épisodes, enregistre avec
  `lerobot-record`, puis revient au menu. Une nouvelle série ajoute
  automatiquement `--resume=true` pour continuer le même dataset au lieu
  d'en créer un nouveau — pratique pour enchaîner les prises rapidement.
- **[4]** quitte et affiche le total d'épisodes enregistrés + le lien du
  dataset.

## Mode direct (scriptable)

Pour un enregistrement unique, piloté entièrement par la ligne de commande :

```bash
python record_dataset.py --task "Attraper le cube rouge" --episodes 30 --dry-run
python record_dataset.py --task "Attraper le cube rouge" --episodes 30
```

Actions ponctuelles équivalentes aux options du menu :

```bash
python record_dataset.py --test-arms
python record_dataset.py --preview
```

## Configuration

Par défaut (adaptable en ligne de commande ou via variables d'environnement
`PORT_FOLLOWER`, `PORT_LEADER`, `FOLLOWER_ID`, `LEADER_ID`) :

| Réglage         | Valeur par défaut            |
|------------------|-------------------------------|
| Follower port    | `/dev/ttyACM0`                |
| Leader port      | `/dev/ttyACM1`                |
| Caméras          | `front=0`, `wrist=1`, `side=2`, 640x480@30fps |
| Episodes         | 10                             |
| Push vers le Hub | activé (`--no-push` pour désactiver) |

Toutes les options : `python record_dataset.py --help`

## Sécurité

Ne mets **jamais** ton token Hugging Face dans ce code ni en argument de
commande. Connecte-toi une fois pour toutes avec :

```bash
hf auth login --add-to-git-credential
```
