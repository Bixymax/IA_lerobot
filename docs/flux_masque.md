# Flux caméra masqué vers LeRobot

`flux_masque.py` lit les **vraies** caméras, efface les pièces que le robot ne doit pas prendre
(`masquage.py`) et publie le résultat sur des **caméras virtuelles** (`/dev/video10`, `11`, `12`).
`lerobot-teleoperate` et `lerobot-record` lisent ces caméras virtuelles comme des webcams
ordinaires : **rien à changer dans LeRobot, seuls les index des caméras changent**.

```
vraies caméras            flux_masque.py                       caméras virtuelles     LeRobot
side    /dev/video2  ─┐   lecture → détection (5/s) →          /dev/video10 (side)  ─┐
top     /dev/video4  ─┼─▶ effacement des non-cibles (chaque ─▶ /dev/video11 (top)   ─┼─▶ teleoperate
angle45 /dev/video6  ─┘   image) → publication                 /dev/video12 (angle45)┘   record / inférence
```

Le robot voit ainsi **exactement les mêmes images** à l'enregistrement et à l'inférence.

## Installation (une seule fois)

```bash
sudo apt install v4l2loopback-dkms v4l2loopback-utils v4l-utils
pip install pyvirtualcam            # dans l'environnement lerobot
```

Si le PC a le *Secure Boot* activé, Ubuntu demande à l'installation de créer un mot de passe
MOK, puis de le confirmer au redémarrage (écran bleu « Enroll MOK ») : sans cela le module ne se
charge pas (`modprobe: ERROR: could not insert 'v4l2loopback': Key was rejected by service`).

## À chaque démarrage du PC

```bash
sudo modprobe v4l2loopback devices=3 video_nr=10,11,12 \
    card_label="side_masque,top_masque,angle45_masque" exclusive_caps=1
v4l2-ctl --list-devices          # doit lister side_masque, top_masque, angle45_masque
```

Les numéros 10, 11 et 12 sont choisis loin des vraies caméras (0 à 7) pour ne jamais les
croiser. `exclusive_caps=1` : la caméra virtuelle n'apparaît comme webcam que lorsque le flux
tourne, donc **lancer `flux_masque.py` avant LeRobot**.

## À chaque séance

### 1. Repérer les vraies caméras

```bash
lerobot-find-cameras opencv      # ou : v4l2-ctl --list-devices
```

Relever les index (`./setup_local.sh`) et les mettre dans `local.env` (`source local.env` définit `$SIDE`, `$TOP`, `$ANGLE45`, `$PORT_FOLLOWER`, `$PORT_LEADER`, utilisés dans toutes les commandes de ce dossier). Les caméras virtuelles apparaissent aussi
dans cette liste (10, 11, 12) : ne pas les confondre.

### 2. Réglages caméra et fond (si l'installation a bougé)

```bash
python masquage.py reglages --cams side=$SIDE top=$TOP angle45=$ANGLE45 --out fonds/
python masquage.py capture  --cams side=$SIDE top=$TOP angle45=$ANGLE45 --out fonds/    # table vide
```

### 3. Terminal 1 : le flux masqué (le laisser tourner)

```bash
python flux_masque.py --cams side=$SIDE top=$TOP angle45=$ANGLE45 --forme triangle
```

Commandes à taper dans ce terminal (lettre puis Entrée) :

| Touche | Effet |
|---|---|
| `t` `r` `h` `e` | une pièce **conforme** de cette forme reste visible (triangle, rond, hexagone, étoile) |
| `d` | une pièce **défectueuse** reste visible (enregistrements du modèle « poubelle ») |
| `n` | nouvelle cible, même mode : **à faire à chaque remise en place des pièces** |
| `a` | aucune : toutes les pièces sont effacées |
| `b` / `m` | flux brut (sans masquage) / retour au masquage |
| `q` | quitter |

Toutes les 10 s, le flux affiche pour chaque caméra le nombre d'images par seconde et le temps
de traitement. Il faut **30 img/s** et moins de 33 ms ; sinon, voir *Dépannage*.
Options : `--apercu` (fenêtre de contrôle ; avec `--diagnostic`, les pièces détectées sont encadrées avec leur forme et leur teinte `h=` : vert = montrée, orange = effacée), `--detection-hz 3` (moins de détections),
`--sans-masquage` (démarrer en brut), `--sorties side=10 top=11 angle45=12` (défaut).

### 4. Terminal 2 : téléopération pour tester et régler

Même commande qu'avant, avec les **index virtuels** et **sans `fourcc`** (les caméras virtuelles
ne fournissent pas de MJPG ; LeRobot refuserait de démarrer) :

```bash
lerobot-teleoperate \
  --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm \
  --robot.cameras='{ side: {type: opencv, index_or_path: 10, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: 11, width: 640, height: 480, fps: 30}, angle45: {type: opencv, index_or_path: 12, width: 640, height: 480, fps: 30} }' \
  --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm \
  --display_data=true
```

Dans Rerun, vérifier : une seule pièce visible, pas de trace des autres, le bras jamais effacé
(surtout ses câbles rouges près des pièces). Changer de forme dans le terminal 1 pour tester.

### 5. Terminal 2 : enregistrement

```bash
lerobot-record \
  --robot.type=so101_follower --robot.port=$PORT_FOLLOWER --robot.id=my_awesome_follower_arm \
  --robot.cameras='{ side: {type: opencv, index_or_path: 10, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: 11, width: 640, height: 480, fps: 30}, angle45: {type: opencv, index_or_path: 12, width: 640, height: 480, fps: 30} }' \
  --teleop.type=so101_leader --teleop.port=$PORT_LEADER --teleop.id=my_awesome_leader_arm \
  --dataset.repo_id=Bixymax/so101_masque_triangle \
  --dataset.num_episodes=50 --dataset.episode_time_s=20 --dataset.reset_time_s=10 \
  --dataset.single_task="Prendre la pièce visible et la mettre dans la zone d'échange" \
  --dataset.streaming_encoding=true --dataset.encoder_threads=2 \
  --dataset.push_to_hub=true --display_data=true
```

Pendant le temps de remise en place entre deux épisodes, on peut changer la forme visible
dans le terminal 1 et déplacer les pièces : le modèle apprend à prendre « la pièce visible »,
quelle que soit sa forme.

### 6. Plus tard : inférence

Même terminal 1, puis la commande LeRobot qui fait tourner la politique, avec **les mêmes
caméras virtuelles** (même bloc `--robot.cameras` que ci-dessus). Elle dépend de la version
(`pip show lerobot`) :

- **LeRobot 0.6** : `lerobot-rollout --strategy.type=base --policy.path=<modèle> --robot.type=so101_follower ... --robot.cameras='{ ... 10, 11, 12 ... }' --task="..." --duration=60`.
  `lerobot-record` y refuse les datasets `eval_...` et ne sert qu'à la collecte.
- **Versions antérieures** : `lerobot-record ... --policy.path=<modèle> --dataset.repo_id=Bixymax/eval_...`.

Avec le Stäubli de P-Robo, `cellule.py` remplace le terminal 1 : il choisit la forme demandée
(`FluxMasque.choisir_forme`) et mesure la pièce déposée. Voir `docs/essai_cellule.md`.

## Règles à respecter

- **Toujours passer par le flux**, à l'enregistrement comme à l'inférence, même en mode brut
  (`b`) : les caméras virtuelles convertissent l'image (format YUV), donc les images ne sont pas
  identiques à celles lues directement. Les épisodes déjà enregistrés sans le flux ne sont pas
  à mélanger avec les nouveaux.
- **Ne jamais ouvrir les vraies caméras dans LeRobot** pendant que le flux tourne
  (« Device or resource busy »).
- Avec la caméra `top`, la cible est choisie sur `top` (forme, taille, couleur : voir
  `docs/conformite.md`) et retrouvée sur les autres caméras par la calibration : plusieurs pièces
  de même couleur sont possibles. **Sans calibration** (ou avec `--ancien-detecteur`), il faut
  toujours **une pièce de chaque couleur** sur la table.
- La cible est **verrouillée** dès qu'elle est choisie : refaire le choix (`n` ou la touche du
  mode) à chaque remise en place des pièces, sinon les pièces posées ensuite restent visibles.
- Un dataset par modèle : `--forme triangle` (ou `t r h e` entre les épisodes) pour le modèle
  « zone d'échange », `--forme defaut` (`d`) pour le modèle « poubelle ».
- Refaire la capture du fond si une caméra bouge ou si l'éclairage change.

## Dépannage

| Message / symptôme | Cause probable | Solution |
|---|---|---|
| `Impossible d'ouvrir la caméra virtuelle /dev/video10` | module non chargé | `sudo modprobe v4l2loopback ...` (ci-dessus) |
| LeRobot : `failed to set fourcc` | `fourcc: MJPG` resté dans la commande | retirer `fourcc` pour les caméras virtuelles |
| LeRobot : `failed to set fps=30` | la caméra virtuelle annonce un autre fps | `v4l2loopback-ctl set-fps /dev/video10 30` (idem 11, 12 ; anciennes versions : `set-fps 30 /dev/video10`), ou retirer `fps: 30` de la caméra |
| LeRobot : `Failed to open` / caméra 10 introuvable | flux pas encore lancé (`exclusive_caps=1`) | lancer `flux_masque.py` d'abord |
| 15 img/s même avec `--sans-masquage` (0 ms de traitement) | `CAP_PROP_BUFFERSIZE = 1` : avec les C310, V4L2 divise le débit par deux | corrigé (2 tampons) ; vérifier avec un test de lecture seule des caméras (30 img/s attendus) |
| 26-27 img/s sur `top` avec masquage | la détection (35 ms) bloquait la boucle de l'image | corrigé : détection dans un fil à part (`asynchrone=True`) ; l'effacement ne coûte que ~6 ms |
| Une pièce de la zone rouge n'est plus détectée, grande zone « différente du fond » | la lumière a dérivé depuis la capture du fond (soleil, store) : un côté de la table diffère partout | corrigé en partie (gain de lumière **local**) ; surtout : lumière stable, puis refaire `reglages`, `capture` du fond et `apprendre` |
| Des « fantômes » pâles à la place des pièces effacées | fond plus clair que la table réelle à cet endroit | idem : fond refait dans la lumière définitive |
| Un cadre orange reste longtemps après le retrait d'une pièce, ou une partie du bras disparaît | le suivi gardait les pièces 50 s | corrigé : une pièce dont l'emplacement est vide est oubliée en ~1 s (`oubli_libre`) ; un objet hors des zones de pièces n'est jamais effacé |
| `Device or resource busy` | une vraie caméra ouverte par deux programmes | n'ouvrir les vraies caméras que dans le flux |
| Flux < 30 img/s | caméra **ou** traitement : lancer avec `--sans-masquage` (ou `b` + Entrée) : si c'est toujours ~15 img/s, c'est la caméra (exposition manuelle trop longue : `exposure_time_absolute` ≤ 300 dans `reglages.json`, ou plus de lumière) ; si c'est 30, c'est le traitement | exposition / lumière, ou `--detection-hz 3`, fermer l'aperçu, moins de pièces |
| Une pièce sombre (vert foncé, rouge foncé) reste visible sur `side` dans sa boîte orange | sa face noire était prise pour le bras | corrigé : une zone sombre entièrement dans la boîte d'une pièce est effacée avec elle |
| Des pièces visibles sur `side` mais sans aucune boîte | le fond ne correspond plus à l'image (caméra bougée, pièces posées contre le bord de la table) : tout le bord de table « change » et forme une zone trop grande | refaire le fond : `python masquage.py capture --cams side=4 top=2 angle45=0` (table vide) |
| `INDISPONIBLE` sur une caméra alors que la pièce est là (elle est effacée) | forme devinée d'après la teinte `h`, qui change d'une caméra à l'autre (lumière, balance des blancs) : le triangle rouge est pris pour un rond orange | `--diagnostic` : le terminal affiche `[diag] top : rond h=12, ...` à chaque changement ; lire le `h=` de la pièce, puis ajuster `TEINTES` dans `masquage.py` (rouge : 0-10 et 165-179, orange : 11-22) |
| Une pièce clignote (réapparaît une fraction de seconde) | le détecteur la rate de temps en temps | déjà atténué : une pièce reste effacée 4 détections après sa dernière vue, sa forme est votée sur 5 détections, la cible ne change pas tant qu'elle est valable. Si ça persiste : `--detection-hz 8` |
| Le bras ou ses câbles rouges sont effacés | pris pour une pièce rouge | le signaler : seuils à ajuster dans `masquage.py` |
