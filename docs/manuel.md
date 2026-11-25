# Aide-mémoire LeRobot

Les commandes se lancent depuis la racine du projet (`~/projetIArobot`), avec conda `lerobot` seul :
un `(.venv)` activé par-dessus masque `lerobot`.

## Initialisation

```bash
conda activate lerobot
./setup_local.sh        # contrôle le poste, charge les caméras virtuelles
lerobot-find-port       # débrancher / rebrancher un bras pour savoir lequel est lequel
nano local.env          # SIDE, TOP, ANGLE45, PORT_FOLLOWER, PORT_LEADER
source local.env        # à refaire dans chaque terminal
```

Les ports et les index de caméras changent à chaque installation.

Token Hugging Face : `hf auth login` (jamais dans un fichier du dépôt).

---

## Calibration des bras

À la question de LeRobot, **taper `c`** pour recalibrer (Entrée seul réutilise l'ancienne
calibration).

### Leader

```bash
sudo chmod 666 $PORT_LEADER
lerobot-calibrate --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm
```

### Follower

```bash
sudo chmod 666 $PORT_FOLLOWER
lerobot-calibrate --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm
```

---

## Téléopération

### Sans caméra

```bash
lerobot-teleoperate \
  --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm \
  --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm
```

### Avec les vraies caméras (flux masqué arrêté)

Pour contrôler le cadrage. Ne pas enregistrer ni tester un modèle ainsi.

```bash
lerobot-teleoperate \
  --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm \
  --robot.cameras="{ side: {type: opencv, index_or_path: $SIDE, width: 640, height: 480, fps: 30, fourcc: MJPG}, top: {type: opencv, index_or_path: $TOP, width: 640, height: 480, fps: 30, fourcc: MJPG}, angle45: {type: opencv, index_or_path: $ANGLE45, width: 640, height: 480, fps: 30, fourcc: MJPG} }" \
  --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm \
  --display_data=true
```

### Avec les caméras masquées (ce que voit le modèle)

Terminal 1, à laisser tourner :

```bash
python flux_masque.py --cams side=$SIDE top=$TOP angle45=$ANGLE45 --forme triangle --apercu
```

Terminal 2 (caméras virtuelles 10, 11, 12, **sans** `fourcc`) :

```bash
lerobot-teleoperate \
  --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm \
  --robot.cameras='{ side: {type: opencv, index_or_path: 10, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: 11, width: 640, height: 480, fps: 30}, angle45: {type: opencv, index_or_path: 12, width: 640, height: 480, fps: 30} }' \
  --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm \
  --display_data=true
```

---

## Enregistrer un dataset

Toujours à travers le flux masqué (terminal 1 ci-dessus). Avant de lancer : choisir la cible
(`t` `r` `h` `e` = pièce conforme, `d` = défectueuse, `n` = autre pièce) et vérifier `top` et `side`.
Détails : `flux_masque.md` et `checklist_enregistrement.md`.

Les commandes tiennent sur **une seule ligne** (collées sur plusieurs, elles ont déjà échoué).
LeRobot ajoute la date au nom du dataset.

### Modèle « zone d'échange » (remplacer `<forme>`)

```bash
lerobot-record --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm --robot.cameras='{ side: {type: opencv, index_or_path: 10, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: 11, width: 640, height: 480, fps: 30}, angle45: {type: opencv, index_or_path: 12, width: 640, height: 480, fps: 30} }' --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm --dataset.repo_id=Bixymax/so101_masque_echange_<forme> --dataset.num_episodes=50 --dataset.episode_time_s=20 --dataset.reset_time_s=10 --dataset.single_task="Prendre la pièce visible et la mettre dans la zone d'échange" --dataset.streaming_encoding=true --dataset.encoder_threads=2 --dataset.push_to_hub=true --display_data=true
```

### Modèle « poubelle » (flux avec `--forme defaut`)

```bash
lerobot-record --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm --robot.cameras='{ side: {type: opencv, index_or_path: 10, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: 11, width: 640, height: 480, fps: 30}, angle45: {type: opencv, index_or_path: 12, width: 640, height: 480, fps: 30} }' --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm --dataset.repo_id=Bixymax/so101_masque_poubelle_3 --dataset.num_episodes=50 --dataset.episode_time_s=20 --dataset.reset_time_s=10 --dataset.single_task="Prendre la pièce défectueuse visible et la mettre dans la zone poubelle" --dataset.streaming_encoding=true --dataset.encoder_threads=2 --dataset.push_to_hub=true --display_data=true
```

---

## Tester le modèle « zone d'échange »

Le modèle ne fonctionne qu'avec les caméras masquées : `cellule.py` (demande du Stäubli, voir
`essai_cellule.md`) ou `flux_masque.py` doit tourner dans le terminal 1.

Terminal 2, **bras au repos** (il y revient à la fin) :

```bash
source local.env
./scripts/rollout_echange.sh
```

Modèle par défaut : `Bixymax/act_so101_masque_echange_toutes_formes`, 30 s. Pour changer :

```bash
DUREE=45 MODELE=Bixymax/autre_modele ./scripts/rollout_echange.sh
```

> **Avant le premier essai** : le script bride le mouvement avec `--robot.max_relative_target=10`.
> 39 % des images d'entraînement dépassent cet écart ; la valeur proposée est 45.
