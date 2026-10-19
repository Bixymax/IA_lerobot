# Projet LeRobot

## Initialisation

Activation de l'environnement virtuel et recherche des ports connectés :

```bash
conda activate lerobot
```

```bash
lerobot-find-port
```

### Variables et Identifiants

```bash
PORT_FOLLOWER = /dev/ttyACM1

PORT_LEADER = /dev/ttyACM0

TOKEN_huggingface = `<VOTRE_TOKEN>`
```

---

## CALIBRATION

### LEADER

```bash
sudo chmod 666 /dev/ttyACM1
```

```bash
lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/ttyACM0 --teleop.id=my_awesome_leader_arm
```

### FOLLOWER

```bash
sudo chmod 666 /dev/ttyACM0
```

```bash
lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/ttyACM1 --robot.id=my_awesome_follower_arm
```

---

## Teleoperate

### Sans camera

```bash
lerobot-teleoperate \
    --robot.type=so101_follower \
    --robot.port=/dev/ttyACM1 \
    --robot.id=my_awesome_follower_arm \
    --teleop.type=so101_leader \
    --teleop.port=/dev/ttyACM0 \
    --teleop.id=my_awesome_leader_arm
```

### Avec 1 camera

```bash
lerobot-teleoperate \
    --robot.type=so101_follower \
    --robot.port=/dev/ttyACM1 \
    --robot.id=my_awesome_follower_arm \
    --robot.cameras="{front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}}" \
    --teleop.type=so101_leader \
    --teleop.port=/dev/ttyACM0 \
    --teleop.id=my_awesome_leader_arm \
    --display_data=true
```

### Avec 2 cameras

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM1 \
  --robot.id=my_awesome_follower_arm \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, side: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30} }" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM0 \
  --teleop.id=my_awesome_leader_arm \
  --display_data=true
```

### Avec 3 cameras

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_awesome_follower_arm \
  --robot.cameras='{ side: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30, fourcc: MJPG}, top: {type: opencv, index_or_path: 4, width: 640, height: 480, fps: 30, fourcc: MJPG}, angle45: {type: opencv, index_or_path: 6, width: 640, height: 480, fps: 30, fourcc: MJPG} }' \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=my_awesome_leader_arm \
  --display_data=true
```

---

## Record DATASET

### Commande 1 :

```bash
lerobot-record \
    --robot.type=so101_follower \
    --robot.port=/dev/ttyACM0 \
    --robot.id=my_awesome_follower_arm \
    --robot.cameras='{ side: {type: opencv, index_or_path: 4, width: 640, height: 480, fps: 30, fourcc: MJPG}, top: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30, fourcc: MJPG}, angle45: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30, fourcc: MJPG} }' \
    --teleop.type=so101_leader \
    --teleop.port=/dev/ttyACM1 \
    --teleop.id=my_awesome_leader_arm \
    --dataset.repo_id=Bixymax/so101_dataset_triangle \
    --dataset.num_episodes=80 \
    --dataset.episode_time_s=20 \
    --dataset.reset_time_s=5 \
    --dataset.single_task="Prendre le triangle puis le mettre dans la zone d'échange" \
    --dataset.streaming_encoding=true \
    --dataset.encoder_threads=2 \
    --dataset.push_to_hub=true \
    --display_data=true
```

# Tester un modèle

```bash
lerobot-rollout \
  --strategy.type=base \
  --policy.path=Bixymax/act_so101_all_shapes_060000 \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_awesome_follower_arm \
  --robot.cameras='{ side: {type: opencv, index_or_path: 4, width: 640, height: 480, fps: 30, fourcc: MJPG}, top: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30, fourcc: MJPG}, angle45: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30, fourcc: MJPG} }' \
  --robot.max_relative_target=10 \
  --task="Prendre une forme puis la mettre dans la zone d'échange" \
  --duration=30
``` 