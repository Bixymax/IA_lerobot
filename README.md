<<<<<<< HEAD
# PIA – Zone d'alimentation et d'échange (SO-101 + LeRobot)

Pôle IA du projet : un bras SO-101 piloté par un modèle d'imitation (LeRobot) prend dans la
zone d'alimentation la pièce demandée par l'équipe robotique (P-Robo) et la dépose dans la zone
d'échange. Sans demande, il trie les pièces défectueuses vers la zone de déchets.

Ce dépôt contient la partie **vision** : préparer les images pour que le modèle ne voie que la
pièce à prendre.

## Principe

Le modèle a été entraîné avec une seule pièce sur la table. Avec plusieurs pièces, il vise « le
milieu ». On efface donc les pièces non ciblées des images avant de les donner au modèle, en les
remplaçant par une photo de la table vide (le *fond*). Détails et choix : `docs/architecture.md`.

## Contenu

| Fichier | Rôle |
|---|---|
| `masquage.py` | Réglage des caméras, capture du fond, effacement, détecteur provisoire, choix de la cible |
| `detection.py` | Démo : garder une forme visible et effacer les autres, en direct sur les 3 caméras |
| `scripts/record_triangle.sh` | Commande `lerobot-record` utilisée pour le premier jeu de données |
| `tests/test_vision.py` | Tests sur images synthétiques (pas besoin de caméra) |
| `docs/architecture.md` | Architecture, décisions, points ouverts |

## Installation

```bash
pip install -r requirements.txt
sudo apt install v4l-utils      # v4l2-ctl, pour figer exposition et balance des blancs
```

## Caméras

Trois Logitech C310, nommées comme dans LeRobot : `side`, `top`, `angle45`.
**Les index `/dev/videoN` changent d'une installation à l'autre** : vérifiez-les à chaque fois
(`v4l2-ctl --list-devices` ou `lerobot-find-cameras opencv`) et passez-les en `nom=index`.
Les fonds et réglages sont rangés par nom, donc ils restent valables.

## Procédure

```bash
# 0. Figer exposition et balance des blancs (une fois, éclairage définitif)
#    -> cliquer sur une fenêtre d'image, 's' = sauver, 'q' = sauver et quitter
python masquage.py reglages --cams side=4 top=2 angle45=0 --out fonds/

# 1. Table vide, bras au repos : photographier le fond
python masquage.py capture --cams side=4 top=2 angle45=0 --out fonds/

# 2. Vérifier l'effacement (toutes les pièces doivent disparaître, pas le bras)
python masquage.py voir --cams side=4 top=2 angle45=0

# 3. Démo : ne montrer qu'une forme (t/r/h/e pour changer, a = aucune, q = quitter)
python detection.py --cams side=4 top=2 angle45=0 --forme triangle
```

Refaire l'étape 1 si une caméra bouge ou si l'éclairage change.

Réglages utiles en haut de `masquage.py` :
- `TEINTES` : plage de teinte de chaque forme (la démo affiche `h=` pour chaque pièce) ;
- `SEUIL_DIFF` : à baisser si des morceaux de pièce restent, à monter si la table est effacée ;
- `SEUIL_CHROMA` : écart de couleur minimal avec la table pour qu'une zone soit une pièce.

Les messages `Corrupt JPEG data` (décodeur MJPG, sans gravité) sont masqués ; `--verbeux` les
réaffiche. Pour LeRobot : `lerobot-record ... 2> >(grep -v "Corrupt JPEG" >&2)`.

## Tests

```bash
python -m pytest -q
```

## État

- [x] Réglage des caméras, capture du fond, effacement des pièces non ciblées
- [x] Démo « une forme visible » avec détecteur provisoire par couleur
- [ ] Détecteur YOLO (formes + défauts) à la place du détecteur par couleur
- [ ] Correspondance entre caméras (homographie / ArUco) quand plusieurs pièces ont la même forme
- [ ] Boucle d'inférence LeRobot avec masquage
- [ ] Protocole TCP avec P-Robo (verrou de la zone d'échange, coordonnées)
- [ ] Nouveaux enregistrements avec plusieurs pièces et réglages caméra figés
=======
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
>>>>>>> b6312d621702b64155d282cad39ac6c3a9c93cf1
