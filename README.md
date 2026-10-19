# PIA – Zone d'alimentation et d'échange (SO-101 + LeRobot)

Pôle IA du projet : un bras SO-101 piloté par un modèle d'imitation (LeRobot) prend dans la
zone d'alimentation la pièce demandée par l'équipe robotique (P-Robo) et la dépose dans la zone
d'échange. Sans demande, il trie les pièces défectueuses vers la zone de déchets.

Ce dépôt contient la partie **vision** : détecter les pièces, effacer celles que le bras ne doit
pas prendre, et enregistrer les datasets LeRobot avec ces images masquées.

## Principe

Le modèle a été entraîné avec une seule pièce sur la table. Avec plusieurs pièces, il vise « le
milieu ». On efface donc les pièces non ciblées des images avant de les donner au modèle, en les
remplaçant par une photo de la table vide (le *fond*). Détails et choix : [`docs/architecture.md`](docs/architecture.md).

```
vraies caméras ─▶ flux_masque.py ─▶ caméras virtuelles ─▶ lerobot-record / inférence
                  (détection + effacement)
```

## Contenu

| Fichier | Rôle |
|---|---|
| `masquage.py` | Réglage des caméras, capture du fond, effacement, détecteur provisoire par couleur, choix de la cible |
| `detection.py` | Démo : garder une forme visible et effacer les autres, en direct sur les 3 caméras |
| `flux_masque.py` | Caméras virtuelles masquées, lues par `lerobot-teleoperate` / `lerobot-record` comme des webcams |
| `capture_dataset.py` | Constitue le jeu d'images étiqueté (format YOLO) pour le futur détecteur |
| `tests/` | Tests sur images synthétiques (pas besoin de caméra) |
| `docs/architecture.md` | Architecture, décisions, points ouverts |
| `docs/flux_masque.md` | Enregistrer un dataset avec le masquage : installation, procédure, dépannage |
| `docs/manuel.md` | Aide-mémoire des commandes LeRobot (calibration, téléopération, test d'un modèle) |
| `docs/3_PIA_AlimentationEchange.pdf` | Cahier des charges du pôle |

## Installation

```bash
pip install -r requirements.txt
sudo apt install v4l-utils      # v4l2-ctl, pour figer exposition et balance des blancs
```

Pour le flux masqué (caméras virtuelles) : voir [`docs/flux_masque.md`](docs/flux_masque.md).

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

# 4. Enregistrer un dataset avec le masquage : voir docs/flux_masque.md
python flux_masque.py --cams side=4 top=2 angle45=0 --forme triangle
```

Refaire l'étape 1 si une caméra bouge ou si l'éclairage change. Le dossier `fonds/` est propre à
chaque installation et n'est pas versionné.

Réglages utiles en haut de `masquage.py` :
- `TEINTES` : plage de teinte de chaque forme (la démo affiche `h=` pour chaque pièce) ;
- `SEUIL_DIFF` : à baisser si des morceaux de pièce restent, à monter si la table est effacée ;
- `SEUIL_CHROMA` : écart de couleur minimal avec la table pour qu'une zone soit une pièce.

Les messages `Corrupt JPEG data` (décodeur MJPG, sans gravité) sont masqués ; `--verbeux` les
réaffiche. Pour LeRobot : `lerobot-record ... 2> >(grep -v "Corrupt JPEG" >&2)`.

## Utilisation dans une boucle d'inférence

```python
from masquage import Masqueur, appliquer_reglages_dossier, choisir_cible

indices = {"side": 4, "top": 2, "angle45": 0}
appliquer_reglages_dossier("fonds/", indices)       # avant d'ouvrir les caméras
masqueur = Masqueur.charger("fonds/")

detections = masqueur.detecter("top", frame_bgr)     # provisoire, en attendant YOLO
cible, non_cibles = choisir_cible(detections, "triangle")
image = masqueur.effacer("top", frame, non_cibles,
                         boites_protegees=[cible["boite"]] if cible else None,
                         entree_rgb=True)            # images LeRobot = RGB
```

## Tests

```bash
python -m pytest -q
```

## État

- [x] Réglage des caméras, capture du fond, effacement des pièces non ciblées
- [x] Démo « une forme visible » avec détecteur provisoire par couleur
- [x] Flux masqué vers caméras virtuelles pour l'enregistrement LeRobot
- [x] Capture d'images étiquetées pour YOLO
- [ ] Détecteur YOLO (formes + défauts) à la place du détecteur par couleur
- [ ] Correspondance entre caméras (homographie / ArUco) quand plusieurs pièces ont la même forme
- [ ] Boucle d'inférence LeRobot avec masquage
- [ ] Protocole TCP avec P-Robo (verrou de la zone d'échange, coordonnées)
- [ ] Nouveaux enregistrements avec plusieurs pièces et réglages caméra figés

## Sécurité

Ne mets **jamais** ton token Hugging Face dans ce code ni en argument de commande.
Connecte-toi une fois pour toutes avec :

```bash
hf auth login --add-to-git-credential
```