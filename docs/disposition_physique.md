# Disposition physique du poste P-IA

> Comment placer concrètement les zones, le SO-101, les caméras et les
> formes sur votre nappe. S'appuie sur les schémas déjà fournis :
> disposition des 3 zones, placement des caméras (vue de dessus), et
> hauteur/angle des caméras (vue de profil, ci-dessus).

## 1. Point de départ : mesurez votre SO-101

Il n'existe pas de chiffre officiel fiable pour le rayon d'action exact du
SO-101 — plutôt que de vous donner une valeur approximative qui pourrait
être fausse, **mesurez-le vous-même** : bras follower tendu au maximum,
mesurez la distance entre l'axe de la base et le bout de la pince fermée.
Notez cette valeur **R** (en cm) — c'est elle qui dimensionne tout le
reste ci-dessous.

## 2. Zone d'alimentation

- Se trouve devant/autour de la base du SO-101, dans son rayon d'action.
- Tracez-la comme une zone d'environ **0,7 × R** de rayon autour de la
  base (marge de sécurité : le bras n'atteint pas bien tout son rayon
  théorique près de la table, à cause de l'inclinaison du poignet).
- Les 4 formes y sont dispersées aléatoirement — laissez un peu d'espace
  entre elles pour faciliter la détection par contours (étape 6 du guide
  d'entraînement).

## 3. Zone poubelle

- Un coin fixe à l'intérieur ou juste à côté de la zone d'alimentation, à
  portée du SO-101 (boîte ou zone délimitée, organisation libre).
- Placez-la pour ne pas gêner l'accès à la zone d'échange ni la vue des
  caméras (voir le schéma des 3 zones, ci-dessus dans la conversation).

## 4. Zone d'échange — à coordonner avec le P-Robo

⚠️ La seule zone que vous ne pouvez pas dessiner seuls : elle doit être
adjacente à la zone d'alimentation (imposé) et atteignable **à la fois**
par le SO-101 et par le bras Stäubli du P-Robo. À convenir avec l'équipe
P-Robo avant de la tracer sur la nappe :
- sa taille et sa position exactes (fonction du rayon d'action du
  Stäubli, que vous ne connaissez pas — demandez-leur de le mesurer
  aussi),
- un **repère de coordonnées commun** sur la nappe (par ex. distances en
  cm depuis un coin fixe), pour que la position que vous leur transmettez
  en TCP/IP ait un sens de leur côté aussi.

## 5. Caméras

Reprend le schéma de placement vu plus haut (`front` / `wrist` / `side`) :

- **`front`** et **`side`** : fixées sur les 2 statifs fournis, en
  surplomb de la zone d'alimentation, inclinées vers le bas (voir la vue
  de profil ci-dessus). Il n'y a pas de hauteur/angle "officiels" à
  respecter — réglez-les en regardant l'**aperçu live de LeLab**
  (onglet Teleoperate) jusqu'à ce que toute la zone de travail soit
  visible sans zone morte.
- **`wrist`** : fixée directement sur le poignet du bras follower.

Une fois réglées, **ne rebougez plus les statifs** entre l'enregistrement
des démonstrations et l'utilisation réelle — un déplacement de caméra
entre les deux fait chuter les performances de la politique.

## 6. Récapitulatif

| Élément | Où | Référence |
|---|---|---|
| Zone d'alimentation | Autour de la base du SO-101, rayon ≈ 0,7×R | Schéma des 3 zones |
| Zone poubelle | Coin de la zone d'alimentation | Schéma des 3 zones |
| Zone d'échange | Adjacente à l'alimentation, à définir avec P-Robo | Schéma des 3 zones |
| Caméra front | Statif, face à la zone d'alimentation | Vue de dessus + vue de profil |
| Caméra side | Statif, perpendiculaire à la caméra front | Vue de dessus + vue de profil |
| Caméra wrist | Poignet du bras follower | Vue de dessus + vue de profil |
| Formes | Dispersées aléatoirement dans la zone d'alimentation | — |
