#!/usr/bin/env bash
# Mise en route au local robot : vérifie le PC, charge les caméras virtuelles, relève caméras et ports.
# Usage :   conda activate lerobot && ./setup_local.sh
#           ./setup_local.sh --sans-sudo      (ne tente pas de charger v4l2loopback ni de chmod les ports)
# Ne modifie rien d'autre que : module v4l2loopback, droits des /dev/ttyACM*, et local.env (créé s'il n'existe pas).
cd "$(dirname "$0")" || exit 1
SUDO=1; [[ "${1:-}" == "--sans-sudo" ]] && SUDO=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
ko()   { printf '  \033[31m✗\033[0m %s\n' "$*"; PB=$((PB+1)); }
info() { printf '  \033[33m•\033[0m %s\n' "$*"; }
PB=0

echo "== 1. Environnement"
if [[ "${CONDA_DEFAULT_ENV:-}" == "lerobot" ]]; then ok "conda lerobot actif"; else ko "faire d'abord : conda activate lerobot"; fi
PY=$(command -v python)
for mod in lerobot cv2 numpy pyvirtualcam; do
  if "$PY" -c "import $mod" 2>/dev/null; then ok "python : $mod"
  else
    case $mod in pyvirtualcam) ko "python : $mod manquant -> pip install pyvirtualcam";;
                 cv2) ko "python : cv2 manquant -> pip install opencv-python";;
                 *) ko "python : $mod manquant";; esac
  fi
done
"$PY" -c "import pytest" 2>/dev/null && ok "pytest" || info "pytest absent (tests : pip install pytest)"
for cmd in v4l2-ctl lerobot-record lerobot-rollout lerobot-find-cameras; do
  command -v $cmd >/dev/null && ok "$cmd" || ko "$cmd introuvable"
done

echo "== 2. Hugging Face"
if command -v hf >/dev/null && hf auth whoami >/dev/null 2>&1; then ok "connecté : $(hf auth whoami 2>/dev/null | head -1)"
else ko "token invalide ou absent -> hf auth login --force   (sinon le push du dataset échoue)"; fi

echo "== 3. Caméras virtuelles (v4l2loopback)"
if lsmod | grep -q '^v4l2loopback'; then ok "module chargé"
elif [[ $SUDO == 1 ]]; then
  info "chargement du module (sudo)"
  if sudo modprobe v4l2loopback devices=3 video_nr=10,11,12 card_label="side_masque,top_masque,angle45_masque" exclusive_caps=1; then ok "module chargé (/dev/video10,11,12)"
  else ko "modprobe a échoué (Secure Boot ? voir docs/flux_masque.md)"; fi
else ko "module non chargé (relancer sans --sans-sudo)"; fi

echo "== 4. Caméras (vraies, Logitech)"
mapfile -t CAMS < <(v4l2-ctl --list-devices 2>/dev/null | awk '
  /^[^ \t]/ {nom=$0; next}
  /\/dev\/video/ {gsub(/^[ \t]+/,""); print nom "|" $0}' | grep -iv "masque\|HP Wide\|Dummy" )
VRAIES=()
for e in "${CAMS[@]}"; do
  dev=${e#*|}
  v4l2-ctl -d "$dev" --all 2>/dev/null | grep -A4 "Device Caps" | grep -q "Video Capture" || continue
  VRAIES+=("${dev#/dev/video}")
  info "$dev  ${e%%|*}"
done
if [[ ${#VRAIES[@]} -ge 3 ]]; then ok "${#VRAIES[@]} caméras de capture : index ${VRAIES[*]}"
else ko "${#VRAIES[@]} caméra(s) trouvée(s) au lieu de 3 : vérifier les câbles USB"; fi
info "ordre suggéré (à CONFIRMER à l'écran : python masquage.py voir ...) : $(printf '%s ' "${VRAIES[@]}")"
[[ -d /dev/v4l/by-path ]] && info "astuce : /dev/v4l/by-path/ reste stable si les caméras restent sur les mêmes ports USB"

echo "== 5. Bras (ports série)"
PORTS=(/dev/ttyACM*)
if [[ -e ${PORTS[0]} ]]; then
  for p in "${PORTS[@]}"; do
    [[ $SUDO == 1 && ! -w $p ]] && sudo chmod 666 "$p"
    ok "$p"
  done
  [[ ${#PORTS[@]} -ge 2 ]] || ko "un seul bras détecté (il faut leader ET follower)"
  info "lequel est lequel : lerobot-find-port (débrancher/rebrancher un bras)"
else ko "aucun /dev/ttyACM* : bras non branchés ou non alimentés"; fi

echo "== 6. Fichiers propres à l'installation (fonds/)"
for f in reglages.json fond_top.png fond_side.png fond_angle45.png calibration.json points_table.json references.json; do
  [[ -f fonds/$f ]] && ok "fonds/$f" || ko "fonds/$f absent"
done
info "caméra déplacée ou éclairage changé : refaire réglages, fond et calibration (README, étape 2)"
"$PY" - <<'E' 2>/dev/null
import json
p = json.load(open("fonds/points_table.json"))
if p.get("zone_alimentation") is None: print("  \033[33m•\033[0m points_table.json : zone_alimentation vide, et A5 (210x148) non mesuré à la règle ?")
E

echo "== 7. local.env"
if [[ ! -f local.env ]]; then cp local.env.example local.env && info "local.env créé : EDITEZ-LE (index caméras, ports), puis : source local.env"
else ok "local.env existe ($(grep -E '^export (SIDE|TOP|ANGLE45)' local.env | tr '\n' ' '))"; fi

echo
if [[ $PB == 0 ]]; then echo "Tout est prêt. Suite : README.md, section « Arrivée au local »."
else echo "$PB point(s) à régler (lignes ✗ ci-dessus)."; fi
exit 0
