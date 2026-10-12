#!/usr/bin/env bash
# Enregistrement du premier jeu de données (un triangle seul -> zone d'échange).
# ATTENTION : les index des caméras changent d'une installation à l'autre.
# Vérifier avec `lerobot-find-cameras opencv` et adapter SIDE / TOP / ANGLE45.
# Appliquer d'abord les réglages figés :
#   python -c 'from masquage import appliquer_reglages_dossier as a; a("fonds/", {"side": 4, "top": 2, "angle45": 0})'
set -euo pipefail

SIDE=${SIDE:-4}
TOP=${TOP:-2}
ANGLE45=${ANGLE45:-0}

lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_awesome_follower_arm \
  --robot.cameras="{ side: {type: opencv, index_or_path: ${SIDE}, width: 640, height: 480, fps: 30, fourcc: MJPG}, top: {type: opencv, index_or_path: ${TOP}, width: 640, height: 480, fps: 30, fourcc: MJPG}, angle45: {type: opencv, index_or_path: ${ANGLE45}, width: 640, height: 480, fps: 30, fourcc: MJPG} }" \
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
  --display_data=true \
  2> >(grep -v "Corrupt JPEG" >&2)
