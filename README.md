# PIA – Zone d'alimentation et d'échange (SO-101 + LeRobot)

Pôle IA du projet : un bras SO-101 piloté par un modèle d'imitation (LeRobot) prend dans la zone
d'alimentation la pièce demandée et la dépose dans la zone d'échange (récupérée ensuite par P-Robo).
Les pièces défectueuses vont à la zone de déchets. Consignes : `consignes/`.

## Principe de la vision

Le modèle a été entraîné avec une seule pièce sur la table. Avec plusieurs pièces, il vise « le
milieu ». On efface donc les pièces non ciblées des images avant de les donner au modèle, en les
remplaçant par une photo de la table vide (le *fond*). Détails : `docs/architecture.md`.

## Contenu

| Fichier | Rôle |
|---|---|
| `setup_local.sh` | **À lancer en arrivant au local** : vérifie le PC, charge les caméras virtuelles, relève caméras et ports |
| `local.env.example` | Modèle de `local.env` (index caméras, ports des bras ; propre au poste, non versionné) |
| `masquage.py` | Réglage des caméras, capture du fond, effacement, détecteur provisoire, choix de la cible |
| `calibration.py` | Pixels ↔ mm sur la table pour chaque caméra (clic de 4 coins de la nappe) |
| `conformite.py` | Forme, taille (mm) et couleur de chaque pièce, verdict OK / défaut ; apprentissage sur les pièces OK |
| `selection.py` | Choix de la pièce montrée (conforme d'une forme, ou défectueuse), retrouvée sur les autres caméras |
| `flux_masque.py` | Caméras virtuelles masquées pour LeRobot (`docs/flux_masque.md`) |
| `echange_tcp.py` | Serveur du protocole TCP avec P-Robo, verrou de la zone d'échange (`docs/protocole_tcp.md`) |
| `detection.py` | Démo : garder une forme visible, effacer les autres (ancien détecteur par couleur) |
| `capture_dataset.py` | Constitution d'un jeu d'images étiquetées depuis la caméra du dessus |
| `record_dataset.py`, `lerobot_recorder/` | Menu interactif d'enregistrement LeRobot (voir plus bas) |
| `scripts/record_triangle.sh` | Commande `lerobot-record` du premier jeu de données |
| `manuel.md` | Aide-mémoire des commandes LeRobot (calibration, téléopération, enregistrement, test d'un modèle) |
| `tests/` | Tests sur images synthétiques et sockets locales (pas besoin de matériel) |
| `docs/` | `architecture.md`, `conformite.md`, `flux_masque.md`, `protocole_tcp.md` |

## Installation (une seule fois par PC)

```bash
conda activate lerobot
pip install -r requirements.txt pyvirtualcam
sudo apt install v4l-utils v4l2loopback-dkms v4l2loopback-utils
hf auth login --force            # token Hugging Face (jamais dans le code)
```

Secure Boot activé : au premier `v4l2loopback`, créer le mot de passe MOK puis confirmer au
redémarrage (voir `docs/flux_masque.md`).

## Arrivée au local (à chaque séance)

On réinstalle tout le poste à chaque séance : **index des caméras et ports des bras changent**.

```bash
cd ~/projetIArobot && conda activate lerobot
./setup_local.sh                 # contrôle tout, charge v4l2loopback (sudo), relève caméras et ports
nano local.env                   # SIDE, TOP, ANGLE45, PORT_FOLLOWER, PORT_LEADER
source local.env
```

Les commandes de toute la doc utilisent ces variables. Ensuite, dans l'ordre :

1. **Bras** : `lerobot-find-port` pour savoir quel port est le leader et lequel est le follower
   (débrancher/rebrancher un bras). Les calibrations LeRobot (`manuel.md`) restent valables si les
   bras portent les mêmes `id`.
2. **Caméras** : identifier à l'écran laquelle est `side`, `top`, `angle45` :
   `python masquage.py voir --cams side=$SIDE top=$TOP angle45=$ANGLE45`
3. **Caméras ont bougé ou éclairage changé ?** Refaire dans l'ordre (table vide, bras au repos) :
   ```bash
   python masquage.py reglages --cams side=$SIDE top=$TOP angle45=$ANGLE45 --out fonds/   # fige exposition/balance
   python masquage.py capture  --cams side=$SIDE top=$TOP angle45=$ANGLE45 --out fonds/   # fond
   python calibration.py cliquer --cams top=$TOP side=$SIDE angle45=$ANGLE45               # coins de la nappe
   python calibration.py voir    --cams top=$TOP side=$SIDE angle45=$ANGLE45               # la grille colle à la nappe ?
   ```
   Sinon, les `fonds/` de la dernière séance suffisent (vérifier à l'écran avec `masquage.py voir`).
4. **Pièces OK** : `fonds/references.json` (une fois, avec les vraies pièces, puis tant que la nappe et
   la caméra `top` ne bougent pas) :
   ```bash
   python conformite.py apprendre --cam top=$TOP --forme etoile      # idem hexagone, triangle, rond
   python conformite.py verifier  --cam top=$TOP                      # pièces OK et défectueuses
   ```
5. **Flux masqué** (terminal 1, à laisser tourner) :
   ```bash
   python flux_masque.py --cams side=$SIDE top=$TOP angle45=$ANGLE45 --forme triangle --apercu --diagnostic
   ```
6. **LeRobot** (terminal 2) sur les caméras virtuelles 10, 11, 12 : commandes dans `docs/flux_masque.md`
   (téléopération, enregistrement, inférence).

Détail des réglages (`TEINTES`, `SEUIL_DIFF`, `SEUIL_CHROMA` en haut de `masquage.py`) et dépannage :
`docs/flux_masque.md`. Les messages `Corrupt JPEG data` sont masqués par défaut (`--verbeux` les
réaffiche ; pour LeRobot : `lerobot-record ... 2> >(grep -v "Corrupt JPEG" >&2)`).

## Caméras

Trois Logitech C310, nommées comme dans LeRobot : `side` (côté, rase la table), `top` (dessus),
`angle45` (oblique). MJPG 640×480 30 fps pour les vraies caméras. Les fonds, réglages et calibrations
sont rangés **par nom** : seuls les index changent. Les caméras virtuelles du flux (10, 11, 12) n'ont pas
de MJPG : pas de `fourcc` dans les commandes LeRobot qui les lisent.

## Enregistrement (menu interactif)

```bash
python record_dataset.py --find-ports     # PORT_FOLLOWER / PORT_LEADER
python record_dataset.py --find-cameras
python record_dataset.py                  # menu : tester bras, prévisualiser, enregistrer
python record_dataset.py --task "..." --episodes 30 --dry-run
```

Réglages par défaut dans `lerobot_recorder/config.py` (variables `PORT_FOLLOWER`, `PORT_LEADER`,
`FOLLOWER_ID`, `LEADER_ID`) ; l'enregistrement avec masquage se lance avec les commandes de
`docs/flux_masque.md`. Sources : <https://huggingface.co/docs/lerobot/en/il_robots>.

```
lerobot_recorder/  config.py (réglages) · commands.py (commandes lerobot-*, testables avec --dry-run)
                   system.py (vérifs, exécution) · actions.py / session.py (menu) · cli.py (arguments)
```

## Communication avec P-Robo

Protocole TCP/JSON proposé dans `docs/protocole_tcp.md` (**à faire valider par P-Robo**). Essai à la main :
`python echange_tcp.py --port 5050` puis `nc 127.0.0.1 5050`.

## Tests

```bash
python -m pytest -q
```

## État

- [x] Réglage des caméras, capture du fond, effacement des pièces non ciblées
- [x] Conformité : forme au contour, taille en mm et couleur comparées aux pièces OK apprises
- [x] Correspondance entre caméras par homographie de la table
- [x] Flux masqué : mode « pièce défectueuse » (modèle poubelle), cible verrouillée pendant l'épisode
- [x] Protocole TCP : proposition + serveur de référence + tests (`docs/protocole_tcp.md`)
- [ ] **Au local** : mesurer le rectangle repère à la règle, définir `zone_alimentation`, apprendre
      les pièces OK (`references.json`) et mesurer la dispersion réelle avec les pièces défectueuses
- [ ] Faire valider le protocole par P-Robo ; mettre la zone d'échange dans la calibration
- [ ] Nouveaux enregistrements avec plusieurs pièces, réglages caméra figés et flux masqué
- [ ] Modèle « poubelle » (pièces défectueuses)
- [ ] Orchestrateur : demandes, choix de la cible, verrou, nouvelles tentatives, boucle d'inférence avec masquage
- [ ] Documentation finale (structure, ordinogramme, justification des choix) et manuel d'intégration
      pour l'opérateur : livrables du cahier des charges, à déposer sur LEARN
