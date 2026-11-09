# Conformité des pièces et choix de la pièce montrée au robot

Ce document décrit comment le flux masqué (`flux_masque.py`) décide quelle pièce reste visible :
une pièce **conforme** d'une forme donnée (modèle « zone d'échange ») ou une pièce
**défectueuse** (modèle « poubelle »). Les autres sont effacées sur les trois caméras.

## Règles du client

| Forme | Couleur OK | Taille nominale (indicative) |
|---|---|---|
| étoile | verte | 28 mm |
| hexagone | jaune | 25 mm |
| triangle | rouge | 28 mm |
| rond | orange | 30 mm |

Une pièce défectueuse a la **mauvaise taille** ou la **mauvaise couleur**. Elle n'est pas
déformée. L'écart de taille peut être faible.

## Principe

```
caméra top ──► pièces (différence avec le fond) ──► mesure de chaque pièce ──► verdict
                                                     forme  : contour (solidité, remplissage)
                                                     taille : diamètre équivalent en mm
                                                     couleur: Lab au centre de la pièce
            ──► suivi dans le temps (médiane des 7 dernières mesures)
            ──► choix de la cible selon le mode, puis VERROUILLAGE
side, angle45 ──► pièces détectées ──► rattachées aux pièces de top par la calibration
            ──► effacement de toutes les pièces sauf la cible, sur chaque caméra
```

### Pourquoi la forme au contour et pas à la couleur

Une étoile rouge est une **étoile défectueuse**, pas un triangle. L'ancien détecteur déduisait la
forme de la couleur : il aurait pris cette étoile pour un triangle conforme. La forme est donc
lue sur le contour, avec deux mesures qui ne dépendent ni de la taille ni de la rotation :

- **solidité** = aire / aire de l'enveloppe convexe : basse pour l'étoile (~0,8 à cette
  résolution), ~1 pour les autres ;
- **remplissage** = aire / aire du cercle circonscrit : ~0,5 triangle, ~0,8 hexagone, ~0,9 rond.

### Pourquoi une calibration en mm

La caméra `top` n'est pas parfaitement verticale : une même pièce paraît plus grande d'un côté de
la table que de l'autre, et l'angle change un peu d'une séance à l'autre. Une homographie
(plan de la table → image), obtenue en cliquant 4 coins d'un rectangle tracé sur la nappe,
ramène tout en millimètres. Elle sert aussi à :

- retrouver sur `side` et `angle45` **la même pièce** que sur `top` (même point de la table),
  ce qui lève l'ancienne contrainte « une pièce de chaque couleur sur la table » ;
- donner à P-Robo des coordonnées en mm.

### Pourquoi apprendre sur les pièces OK plutôt qu'utiliser les cotes

La taille mesurée n'est pas la cote nominale : la caméra voit aussi un peu les côtés de la pièce,
les pointes de l'étoile sont arrondies par le flou, et le résultat dépend de l'endroit. Ce biais
est le même pour une pièce OK et une pièce défectueuse posées au même endroit. On enregistre donc
des pièces OK à 8-15 endroits ; le programme modélise la taille attendue **selon la position**
(constante, puis plan à partir de 6 échantillons, puis surface courbe à partir de 15) et la
dispersion des pièces OK autour de ce modèle.

### Mesure fine de la taille

Une pièce fait ~28 px sur l'image (≈ 1 px par mm). Pour détecter un écart de l'ordre du mm :

- le bord est placé à mi-contraste entre la table et la pièce (indépendant de la couleur) ;
- les pixels du bord comptent pour la fraction de pièce qu'ils contiennent (précision
  inférieure au pixel) ;
- le verdict utilise la médiane des 7 dernières mesures.

Sur images synthétiques (flou, bruit), un rond de 28 mm est mesuré à ±0,2 mm et un écart de 4 %
(1,1 mm) est retrouvé à ±0,3 mm. **Sur les vraies caméras, la commande `verifier` affiche la
dispersion réelle (`sigma`)** : un défaut plus petit qu'environ 3 sigma n'est pas détectable de
façon fiable. Si c'est insuffisant : rapprocher ou zoomer la caméra `top` (plus de pixels par mm),
améliorer l'éclairage (moins de bruit), ou restreindre la zone d'alimentation.

### Verdict

| Contrôle | Forme apprise | Forme pas encore apprise |
|---|---|---|
| forme | plus proche des formes apprises | plus proche des prototypes mesurés sur vos photos |
| couleur | écart Lab ≤ max(10, 3 × dispersion des OK) | nom de couleur (teinte) = couleur attendue |
| teinte (a, b de Lab, sans la clarté) | chaque canal ≤ 3 × sa dispersion (plancher 3) | — |
| taille | écart ≤ max(2,5 %, 3 × dispersion des OK) **dans la zone apprise** | non vérifiée (signalé) |

- La **teinte** est jugée canal par canal : la clarté et les reflets (le rond brille) gonflent
  l'écart global de couleur et laissaient passer un rond jaune pris pour un rond orange.
- La **taille** n'est jugée que dans le rectangle des échantillons (+ 40 mm) : la caméra n'est
  pas verticale, la taille apparente change avec la position et le modèle ne vaut rien ailleurs
  (zones verte et bleue : remarque « hors de la zone apprise : taille non vérifiée »). Il faut donc
  apprendre **dans la zone d'alimentation**, partout où des pièces seront posées.
- `taille_k` = 3 (2 détecte mieux les petites déformations, mais ne laisse aucune marge à une
  dérive de lumière : à n'essayer qu'avec un éclairage stable). `taille_k_par_forme` : l'étoile,
  dont le « diamètre » dépend de l'orientation, garde 3.
- Dans `verifier`, une pièce dont le verdict change sur les 15 dernières images est **orange
  (LIMITE)** : elle est à la frontière d'une tolérance. Le flux, lui, juge la médiane des 7
  dernières mesures.
- **Rond et hexagone se ressemblent** (4 hexagones sur 69 classés rond) : un rond jaune est reconnu
  comme défaut soit par sa teinte (classé rond), soit par sa taille (classé hexagone).

Les tolérances se règlent dans `fonds/references.json`, clé `tolerances`
(`taille_min_pct`, `taille_k`, `taille_k_par_forme`, `couleur_min`, `couleur_k`, `teinte_k`,
`teinte_sigma_min`, `forme_max`). Elles sont sauvées AVEC les références : modifier les valeurs par
défaut dans `conformite.py` ne change pas une installation déjà apprise.

Les objets détectés **hors des zones de pièces** (`zones_pieces` dans `fonds/points_table.json` :
alimentation, déchet, échange, marge 30 mm) ne sont pas des pièces (bord de table, robot, câbles) :
ni suivis, ni effacés.

### Choix et verrouillage de la cible

- Mode forme (`t r h e`) : une pièce **conforme** de cette forme ; mode `d` : une pièce
  **défectueuse**, n'importe laquelle. Si plusieurs conviennent, la plus isolée.
- La pièce doit être immobile et mesurée au moins 3 fois, et dans la zone d'alimentation si elle
  est définie (`zone_alimentation` dans `fonds/points_table.json`, polygone en mm) : une pièce
  déjà posée dans la zone d'échange ne sera jamais rechoisie.
- Une fois choisie, la cible est **verrouillée** : elle reste la même quand le bras la cache, la
  saisit ou la dépose. Ce qui apparaît après le choix (la pièce dans la pince, les câbles rouges
  du bras) **reste visible** ; seules les pièces présentes au moment du choix sont effacées.
- **Après avoir replacé les pièces entre deux épisodes, refaire le choix** : touche de la forme,
  `d`, ou `n` (nouvelle cible, même mode). Le flux prévient si une pièce immobile apparaît
  pendant le verrou.

### Sur `side` et `angle45`

Chaque pièce de `top` est projetée sur la caméra (point de la table où elle est posée) et
rattachée à la détection la plus proche. La cible est rattachée en premier : si deux pièces se
chevauchent sur une vue rasante, on préfère laisser voir une voisine que d'effacer la cible.
Sans calibration de cette caméra, le rattachement se fait par couleur ; deux pièces de même
couleur dont l'une est la cible restent alors visibles toutes les deux (avertissement au
démarrage).

## Procédure

À faire dans l'ordre, avec l'éclairage définitif. Index des caméras : `v4l2-ctl --list-devices`.

```bash
# 1. Réglages caméra et fond (table vide) — inchangé
python masquage.py reglages --cams side=$SIDE top=$TOP angle45=$ANGLE45 --out fonds/
python masquage.py capture  --cams side=$SIDE top=$TOP angle45=$ANGLE45 --out fonds/

# 2. Calibration (une fois, puis dès qu'une caméra bouge)
#    Au premier lancement, fonds/points_table.json est créé avec les 4 coins du rectangle vert
#    (A5 supposé : 210 x 148 mm). MESUREZ-LE À LA RÈGLE et corrigez si besoin.
#    Ajoutez des coins d'autres rectangles (mm, même origine) si side ou angle45 ne voient pas
#    bien le rectangle vert : 4 points visibles minimum par caméra.
python calibration.py cliquer --cams top=$TOP side=$SIDE angle45=$ANGLE45
python calibration.py voir    --cams top=$TOP side=$SIDE angle45=$ANGLE45   # la grille doit coller à la nappe

# 3. Apprentissage des pièces OK (une commande par forme ; q = sauver)
#    1 à 4 pièces OK de la forme à la fois, espace, les déplacer, espace... 8 à 15 échantillons,
#    répartis sur toute la zone d'alimentation, bras hors du champ.
python conformite.py apprendre --cam top=$TOP --forme etoile
python conformite.py apprendre --cam top=$TOP --forme hexagone
python conformite.py apprendre --cam top=$TOP --forme triangle
python conformite.py apprendre --cam top=$TOP --forme rond

# 4. Vérification avec des pièces OK ET défectueuses (c = enregistrer dans fonds/mesures.csv)
python conformite.py verifier --cam top=$TOP

# 5. Flux masqué pour l'enregistrement (voir docs/flux_masque.md)
python flux_masque.py --cams side=$SIDE top=$TOP angle45=$ANGLE45 --forme triangle --apercu --diagnostic
```

Avec `--apercu --diagnostic`, chaque pièce est encadrée : vert = cible, orange = effacée,
gris = laissée visible (apparue après le choix), avec son verdict (`#3 triangle DEF -6.2%`).

## Fichiers

| Fichier | Rôle |
|---|---|
| `calibration.py` | Homographies table ↔ caméras, zone d'alimentation |
| `conformite.py` | Mesure, références apprises, verdict ; commandes `apprendre` et `verifier` |
| `selection.py` | Suivi sur `top`, choix et verrouillage de la cible, rattachement sur les autres caméras ; `inventaire()` pour l'orchestrateur P-Robo |
| `fonds/points_table.json` | Repères de la nappe en mm, zone d'alimentation (à remplir) |
| `fonds/calibration.json` | Homographies (générées) |
| `fonds/references.json` | Échantillons des pièces OK et tolérances (générés) |
| `tests/test_conformite.py` | Tests sur images synthétiques |

`fonds/` n'est pas versionné (propre à l'installation). `points_table.json` et
`references.json` peuvent être ajoutés au dépôt (`git add -f`) pour ne pas les refaire sur un
autre PC, à condition de garder la même nappe et les mêmes réglages caméra.

## Limites connues

- Pièces qui se touchent : elles forment une seule tache et ne sont pas mesurables (le cahier des
  charges garantit un petit espace entre elles).
- Défauts plus petits que ~3 × la dispersion mesurée par `verifier` : non détectables de façon
  fiable à la résolution actuelle.
- Une pièce voisine bousculée par le bras pendant l'épisode peut réapparaître sur l'image.
- Le verrouillage suppose qu'on refait le choix à chaque remise en place des pièces.
