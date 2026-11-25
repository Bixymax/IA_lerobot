#!/usr/bin/env bash
# Essai du modèle « zone d'échange » sur les caméras virtuelles masquées : cellule.py (ou
# flux_masque.py) doit déjà tourner.
# Partir bras AU REPOS : lerobot-rollout le ramène à sa position de départ à la fin.
# Usage : source local.env && ./scripts/rollout_echange.sh
#         DUREE=45 MODELE=Bixymax/autre_modele ./scripts/rollout_echange.sh
set -euo pipefail
: "${PORT_FOLLOWER:?PORT_FOLLOWER absent : lancer d abord : source local.env}"
MODELE="${MODELE:-Bixymax/act_so101_masque_echange_toutes_formes}"
DUREE="${DUREE:-30}"
CAMERAS='{ side: {type: opencv, index_or_path: 10, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: 11, width: 640, height: 480, fps: 30}, angle45: {type: opencv, index_or_path: 12, width: 640, height: 480, fps: 30} }'

exec lerobot-rollout \
  --strategy.type=base \
  --policy.path="$MODELE" \
  --robot.type=so101_follower \
  --robot.port="$PORT_FOLLOWER" \
  --robot.id=my_awesome_follower_arm \
  --robot.cameras="$CAMERAS" \
  --robot.max_relative_target=10 \
  --task="Prendre la pièce visible et la mettre dans la zone d'échange" \
  --duration="$DUREE" \
  "$@"
