# Architecture et décisions

## Rôle du système

1. P-Robo demande une forme (triangle, étoile, hexagone, rond) par TCP.
2. On choisit une pièce **conforme** de cette forme dans la zone d'alimentation.
3. Le bras la prend, la dépose dans la zone d'échange et revient au repos.
4. La caméra du dessus mesure la pièce ; on renvoie à P-Robo sa position et son orientation. La
   zone est à lui jusqu'à son accusé de réception, le SO-101 reste immobile.
5. Quand le robot de P-Robo n'a pas la zone : les pièces défectueuses (taille, couleur, forme)
   vont à la zone de déchets.

## Briques

| Brique | Rôle | État |
|---|---|---|
| Vision – détection | Classe et position de chaque pièce (forme × conforme/défaut) | Fait : forme au contour, taille et couleur vs pièces OK apprises (`conformite.py`) |
| Vision – calibration | Pixels ↔ mm de la table, par caméra | Fait (`calibration.py`) |
| Vision – sélection | Cible choisie sur `top`, verrouillée, retrouvée sur les autres caméras | Fait (`selection.py`) |
| Vision – masquage | Efface les pièces non ciblées dans les images du modèle | Fait (`masquage.py`) |
| Modèle de gestes | Politique LeRobot (ACT) entraînée par imitation | **2 modèles** (voir ci-dessous) ; 1er essai : triangle seul |
| Orchestrateur | Demandes P-Robo, choix de la cible, nouvelles tentatives | En deux étapes (`cellule.py`, modèle lancé à la main) ; automatique à faire |
| Communication | TCP avec le Stäubli, sécurité de la zone | Fait (`echange_tcp.py`, `docs/protocole_tcp.md`) ; à valider avec P-Robo et à essayer sur le robot |
| Coordonnées | Position et orientation dans la zone d'échange | Fait (`mesure_echange.py`) ; précision réelle à mesurer |

## Décision (2026-11-25) : dépôt à la demande, protocole de P-Robo

- Les pièces conformes sont déposées **à la demande**, une seule à la fois : pas d'emplacements à
  gérer ni de pièces voisines dans la zone.
- On suit les trames du cahier des charges de P-Robo (déjà codées sur leur robot) au lieu de notre
  proposition JSON. Le droit d'entrée dans la zone est donné par l'envoi des coordonnées : la
  sécurité tient donc au moment où l'on répond (`docs/protocole_tcp.md` §5).
- Premier essai **en deux étapes** (modèle lancé à la main) pour tester séparément le modèle et
  la communication.
- Orientation `RZ` : phase du moment complexe d'ordre n de la surface (n = 3, 5, 6), moyennée sur
  plusieurs images ; erreur < 2,5° sur images synthétiques, à mesurer sur les vraies pièces.

## Décision (2026-11-16) : deux modèles, choisis selon la destination

On entraîne **deux** politiques, une par destination :

| Modèle | Destination | Dataset | Cible montrée par le flux (`flux_masque.py`) |
|---|---|---|---|
| « échange » | zone d'échange (bleue) | `Bixymax/so101_masque_echange_<forme>` | pièce **conforme** d'une forme : touches `t r h e` |
| « poubelle » | zone de déchets (verte) | `Bixymax/so101_masque_poubelle` | pièce **défectueuse** : touche `d` |

Le modèle ne décide pas où aller : la caméra ne lui montre que la pièce à déplacer (les autres sont
effacées) et c'est **le logiciel** qui juge (forme, taille, couleur : `conformite.py`, `selection.py`).
À l'inférence, l'orchestrateur choisit la pièce, la montre via le flux, puis lance le modèle qui
correspond à sa destination (conforme -> « échange », défectueuse -> « poubelle »).
Conséquence : une erreur du logiciel de conformité = une mauvaise étiquette apprise ou un mauvais
modèle lancé ; d'où le bilan de `scripts/bilan_formes.py` (0 erreur sur 79 mesures le 2026-11-16).

## Décision : masquage plutôt que ré-entraînement en scène encombrée

Le premier modèle n'a vu qu'une pièce à la fois et va « au milieu » quand il y en a plusieurs.
Plutôt que d'enregistrer des scènes encombrées, on montre au modèle une scène qui ressemble à ses
données : une seule pièce visible.

- Remplacement par une **photo de la table vide** (caméras fixes, éclairage stable, table uniforme).
- Seuls les pixels qui **diffèrent du fond** et forment un ensemble contenant des pixels **plus
  colorés que la table** sont remplacés : pièce, face sombre et ombre partent ; le bras (noir et
  blanc) reste. La table étant elle-même un peu teintée, le critère « plus coloré que la table »
  (Lab) remplace un simple seuil de saturation, qui effaçait les bords du bras.
- La cible est protégée même si la boîte d'une voisine la recouvre.
- Limite : les pièces effacées sont toujours là physiquement ; le bras peut les heurter.
  On choisit donc la cible la plus isolée.

## Caméras

| Nom LeRobot | Vue | Index lors du 1er enregistrement (changent à chaque séance : `local.env`) |
|---|---|---|
| `top` | dessus | 2 |
| `side` | côté (rase la table) | 4 |
| `angle45` | oblique | 0 |

- MJPG, 640×480, 30 fps, comme dans `lerobot-record`.
- Exposition et balance des blancs **figées** (`fonds/reglages.json`). Les mêmes réglages doivent
  servir pour la capture du fond, l'enregistrement et l'inférence.
- Les épisodes déjà enregistrés l'ont été en automatique : à refaire avec les réglages figés.

## Points ouverts

- ~~Correspondance entre caméras~~ : résolue par homographie table ↔ caméra (coins de la nappe
  cliqués), voir `docs/conformite.md`. Repère de P-Robo : `docs/protocole_tcp.md` §4.
- **Câbles rouges du bras** : peuvent être pris pour une pièce quand le bras passe dans une boîte.
- **Défauts** : choix des mesures (taille en mm, couleur Lab, forme au contour) plutôt que YOLO :
  un défaut de taille subtil ne se voit pas sur l'apparence, il se mesure ; et les références
  s'apprennent avec quelques pièces OK, sans étiqueter de dataset. Reste à mesurer la dispersion
  réelle avec les pièces défectueuses (`conformite.py verifier`).
- **LeRobot remet-il les contrôles caméra à zéro ?** À vérifier avec `v4l2-ctl --get-ctrl`
  pendant un enregistrement.
