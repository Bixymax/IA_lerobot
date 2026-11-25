# Essai de la cellule en deux étapes (communication + modèle « échange »)

Le programme reçoit la demande, montre la cible et mesure la pièce ; **vous** lancez le modèle.
Protocole : `docs/protocole_tcp.md`.

## À la maison (sans matériel)

```bash
python echange_tcp.py                  # terminal 1 : serveur à coordonnées fictives
python scripts/faux_staubli.py         # terminal 2 : joue le robot
```

Terminal 1 : `o` (zone libre), puis `v` (coordonnées) ou `x` (NONE).

## Au local

### 1. Préparation (checklist A à F)
- [ ] `./setup_local.sh`, `local.env` à jour, conda `lerobot` seul
- [ ] Fond, calibration (**coins bleus cliqués sur `top`**) et références dans la même lumière
- [ ] Rectangle **bleu** mesuré à la règle (`fonds/points_table.json` : 148 × 210 mm supposés) :
      ses coins définissent le repère envoyé au Stäubli
- [ ] Hauteur de l'objectif de `top` au-dessus de la table, épaisseur des pièces

### 2. Essai du modèle seul, sans le Stäubli

```bash
# terminal 1 (remplace flux_masque.py, qui ne doit pas tourner en même temps)
source local.env
python cellule.py --cams side=$SIDE top=$TOP angle45=$ANGLE45 \
    --hauteur-camera <mm> --epaisseur <mm>
# terminal 3
python scripts/faux_staubli.py
```

1. Taper `o` dans la cellule (zone libre), puis `e` dans le faux Stäubli.
2. Aperçu : une seule étoile visible dans les vues « vu par le modèle ».
3. **Bras au repos**, terminal 2 : `source local.env && ./scripts/rollout_echange.sh`
   (30 s ; `DUREE=45 …` pour plus long).
4. Quand la commande est finie et le bras au repos : `v`.
5. La cellule envoie les coordonnées ; **contrôler à la règle** X et Y depuis le coin bas gauche
   bleu, et le sens de la flèche sur la vue « top brute ».
6. Répondre `d` ou `n` dans le faux Stäubli.

| Touche | Effet |
|---|---|
| `o` | le Stäubli est hors de la zone (démarrage, blocage) |
| `v` | mesurer et envoyer les coordonnées |
| `n` | nouvelle cible (second essai) |
| `x` | répondre `NONE` |
| `q` | quitter |

À noter pour chaque essai : forme, pièce prise (oui/non), pièce dans la zone (oui/non), écart X/Y.

### 3. Liaison RJ45 avec le Stäubli

IP à obtenir de P-Robo (exemple ci-dessous). Internet continue par le Wi-Fi.

```bash
ip -br link                                   # nom du port filaire (eno1, enp…)
nmcli con add type ethernet ifname eno1 con-name staubli \
    ipv4.method manual ipv4.addresses 192.168.0.10/24 ipv4.never-default yes ipv6.method disabled
nmcli con up staubli
ping <ip du contrôleur J205>
sudo ufw status                               # si actif : sudo ufw allow 5000/tcp
```

Premier essai avec le robot : `python echange_tcp.py --host 192.168.0.10` (coordonnées fictives,
**mouvement du Stäubli désactivé**), puis la cellule complète avec le même `--host`.

`--host` = l'IP **filaire** du PC : sans lui, le serveur écoute aussi sur le Wi-Fi, et toute
connexion venue de là remplace celle du robot (la cellule se bloque).

## Limites

- Aperçu et modèle tournent en même temps : si `lerobot-rollout` signale une boucle trop lente,
  réduire `--detection-hz` ou `--echelle`, ou lancer avec `--sans-apercu`.
- La cellule **ne commande pas le SO-101**. Elle refuse d'envoyer tant qu'un programme
  `lerobot-*` tourne et affiche « ARRÊTEZ LE SO-101 » s'il en démarre un pendant que le Stäubli a
  la zone, mais elle ne l'arrête pas.
- Lancer `rollout_echange.sh` bras au repos : LeRobot revient à la position de départ.
- Réglages au besoin : `--seuil-encombrement` (la valeur courante est affichée sur la vue brute),
  `--delai-none` (0 = jamais de `NONE` automatique), `--echelle`, `--sans-apercu`.

## Messages de refus

| Message | Que faire |
|---|---|
| `REFUSÉ : lerobot-rollout tourne encore` | attendre la fin, puis `v` |
| `quelque chose est dans la zone d'échange` | écarter le bras ; zone vide mais valeur élevée : fond à refaire |
| `pas de … dans la zone d'échange` | pièce non déposée : `n`, relancer le modèle, `v` |
| `la pièce bouge` / `orientation instable` | attendre, vérifier la lumière, `v` |
| `plusieurs pièces` | n'en laisser qu'une de cette forme |
