# Vision – masquage des pièces non ciblées

Le modèle a été entraîné avec une seule pièce sur la table : avec plusieurs pièces, il vise « le
milieu ». On efface donc les pièces non ciblées des images avant de les donner au modèle, en les
remplaçant par une photo de la table vide (le *fond*). Choix et points ouverts :
[`ARCHITECTURE.md`](ARCHITECTURE.md).

| Fichier | Rôle |
|---|---|
| `masquage.py` | Réglage des caméras, capture du fond, effacement, détecteur provisoire par couleur, choix de la cible |
| `detection.py` | Démo : garder une forme visible et effacer les autres, en direct sur les 3 caméras |
| `../tests/test_vision.py` | Tests sur images synthétiques (pas besoin de caméra) |

## Prérequis

OpenCV et NumPy (installés avec LeRobot), plus `v4l2-ctl` pour figer exposition et balance :

```bash
sudo apt install v4l-utils
```

## Caméras

Noms identiques à ceux de `lerobot-record` : `side`, `top`, `angle45` (MJPG, 640×480, 30 fps).
**Les index `/dev/videoN` changent d'une installation à l'autre** : vérifiez-les à chaque fois
(`v4l2-ctl --list-devices` ou `lerobot-find-cameras opencv`) et passez-les en `nom=index`.
Les fonds et réglages sont rangés par nom, donc ils restent valables.

## Procédure (depuis la racine du dépôt)

```bash
# 0. Figer exposition et balance des blancs (une fois, éclairage définitif)
#    -> cliquer sur une fenêtre d'image, 's' = sauver, 'q' = sauver et quitter
python vision/masquage.py reglages --cams side=2 top=4 angle45=6 --out fonds/

# 1. Table vide, bras au repos : photographier le fond
python vision/masquage.py capture --cams side=2 top=4 angle45=6 --out fonds/

# 2. Vérifier l'effacement (toutes les pièces doivent disparaître, pas le bras)
python vision/masquage.py voir --cams side=2 top=4 angle45=6

# 3. Démo : ne montrer qu'une forme (t/r/h/e pour changer, a = aucune, q = quitter)
python vision/detection.py --cams side=2 top=4 angle45=6 --forme triangle
```

Refaire l'étape 1 si une caméra bouge ou si l'éclairage change. Le dossier `fonds/` est propre à
chaque installation et n'est pas versionné.

Réglages en haut de `masquage.py` :
- `TEINTES` : plage de teinte de chaque forme (la démo affiche `h=` pour chaque pièce) ;
- `SEUIL_DIFF` : à baisser si des morceaux de pièce restent, à monter si la table est effacée ;
- `SEUIL_CHROMA` : écart de couleur minimal avec la table pour qu'une zone compte comme pièce.

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
- [ ] Détecteur YOLO (formes + défauts) à la place du détecteur par couleur
- [ ] Correspondance entre caméras (homographie / ArUco) quand plusieurs pièces ont la même forme
- [ ] Boucle d'inférence LeRobot avec masquage
- [ ] Protocole TCP avec P-Robo (verrou de la zone d'échange, coordonnées)
- [ ] Nouveaux enregistrements avec plusieurs pièces et réglages caméra figés
