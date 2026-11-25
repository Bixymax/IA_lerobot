# Prochaine session au local robot : état et reprise

## Travail à la maison du 2026-11-25 (communication avec le Stäubli, non essayé sur matériel)

- Nouveau : `echange_tcp.py` réécrit selon le PDF de P-Robo, `mesure_echange.py`, `cellule.py`,
  `scripts/rollout_echange.sh`, `scripts/faux_staubli.py`. Tests et essai avec caméras simulées OK.
- **À faire au local** : suivre `docs/essai_cellule.md` (modèle « échange » avec le faux Stäubli,
  précision X/Y/RZ à la règle, puis liaison RJ45).
- **À envoyer à P-Robo** : `docs/protocole_tcp.md` (questions au §7).
- Plus tard : dataset poubelle, puis lancement automatique du modèle.

## Séance du 2026-11-23 (résumé, le plus récent d'abord)

**Fait**
- Caméras `angle45` déplacée en cours de séance : fond et calibration d'`angle45` refaits. Références ×4
  réapprises dans la lumière du jour. Index détectés au départ : `SIDE=6 TOP=0 ANGLE45=2` (à revérifier).
- Datasets « échange » complets à 100 épisodes, **poussés sur HF** : `Bixymax/so101_masque_echange_etoile_100`
  (2 × 50), `…_hexagone_100` (46 + 54, `angle45` a bougé entre les deux parties), `…_rond_20261117_113551`,
  `…_triangle_20261117_092054` (clignotements possibles à 9 h non relus).
- Fusion des 4 : `Bixymax/so101_masque_echange_toutes_formes` (400 épisodes, 154 546 images), local. **Push
  lancé ensuite, résultat non vu** : vérifier qu'il est bien sur le Hub (sinon `LeRobotDataset(...).push_to_hub()`
  avec conda `lerobot` seul, sans `.venv`).
- Entraînement ACT lancé sur les GPU de l'école avec ce dataset (`lerobot-train`, `policy.repo_id=
  Bixymax/act_so101_masque_echange_toutes_formes`).

**À faire / nettoyage**
- Hub : les deux morceaux d'hexagone (`…_20261123_150633` 46 ép., `…_hexagone_2_20261123_153703` 54 ép.) sont
  toujours en ligne, supprimés en local seulement. À supprimer sur le Hub si on veut.
- Local à trier : `…rond_112107` (25), `…rond_110859` (6), morceaux étoile `…etoile_v2_*` (deux), `…poubelle_…_old`.
- **Jeton HF collé dans le chat** : à révoquer et recréer.
- **Dataset poubelle à continuer** (47 épisodes existent, poussés le 16). Prévu : `--forme defaut`, repo_id
  `Bixymax/so101_masque_poubelle_3`, tâche « Prendre la pièce défectueuse visible et la mettre dans la zone
  poubelle ». **Avant : screening** (`conformite.py verifier`, pièces étalon, `c`, remplir `vraie_forme` /
  `vraie_etat`, `scripts/bilan_formes.py`) : aucune bonne pièce classée défectueuse, la lumière a changé.
- Pièges de la séance : un `(.venv)` actif masque `lerobot` ; commande `lerobot-record` collée sur plusieurs
  lignes = « Missing required field `dataset` » ; une seule ligne, sans `\`.

## Séance du 2026-11-17 (résumé, le plus récent d'abord)

**Datasets « échange » enregistrés, NON poussés sur HF** (`push_to_hub=false`), dans
`~/.cache/huggingface/lerobot/Bixymax/` :
- `so101_masque_echange_triangle_20261117_092054` : 100 épisodes (enregistré à 9 h 20, avant les
  incidents ; des autres pièces clignotaient parfois : à relire avant de pousser).
- `so101_masque_echange_rond_20261117_113551` : 100 épisodes (série propre, après le nouveau fond de 11 h 02
  et la calibration de 11 h 05). Autres dossiers ronds : `_112107` (25 ép.) et `_110859` (6 ép.) : à relire,
  à supprimer ou fusionner.
- `so101_masque_echange_etoile_20261117_123112` : 27 épisodes (objectif 50, arrêté faute de temps).
  `…_122727` (1 épisode) : à supprimer. La caméra `side` a lâché pendant la série : **vérifier les derniers
  épisodes de `side`** (image figée ou noire) avant de pousser.
- Reste : dataset « poubelle » déjà poussé le 16 ; fusion des 2 poubelle, fusion des morceaux ronds/étoile,
  push HF, entraînement.

**Incidents du jour (à éviter la prochaine fois)**
- **Caméra `side` : faux contact USB** (port `usb-0:3`). Son index est passé de 4 à 5 puis à 4 (12 h 28) et le
  flux affichait « side : N lectures ratées ». Remplacer le câble, le fixer au scotch, vérifier
  `v4l2-ctl --list-devices` avant chaque série. Les épisodes enregistrés pendant une coupure sont inutilisables.
- **`angle45` déplacée par accident** : fond + calibration à refaire (c'était la calibration). Scotcher les pieds
  des caméras ET leurs câbles.
- **Alimentation du leader coupée** : `Missing motor IDs 1..6` = bras non alimenté. Puis plus aucun `ttyACM`
  = les deux câbles USB débranchés.
- Commande `lerobot-record` incomplète (sans `--dataset.repo_id`) : « FileExistsError … /lerobot ».
- Lancer les commandes depuis `~/projetIArobot`, conda `lerobot` seul (ni `.venv`, ni `(base)` empilé).
- Un `rerun` oublié depuis 8 h 58 consommait 75 % d'un cœur : le fermer.

**Références d'étoile nettoyées (fonds/references.json)** : 8 mesures aberrantes retirées (diamètre 15-22 mm,
solidité/régularité basses, surtout vers x = -36..-50, y = 100..150 : reflet / zone plus claire). Sauvegardes :
`fonds/references_avant_nettoyage_etoile_1253.json` et `~/sauvegardes_pia/fonds_2026-11-17`. **À refaire au
prochain labo : `rm fonds/references.json` puis `apprendre` ×4 (étoile comprise), dans la lumière du jour.**
Contrôler que le coin x ≈ -45, y ≈ 100-150 n'a pas de reflet. Tolérance de taille de l'étoile serrée (σ 0,4 mm,
`taille_k=3`) : à vérifier avec `verifier` (faux défauts ?).

**Reprise** : checklist A à E (fond, calibration, références) ; terminer les étoiles (50 -> ~23 de plus), relire
les datasets, fusionner, pousser, entraîner. Index de la fin de séance : `SIDE=4 TOP=2 ANGLE45=0`,
`PORT_FOLLOWER=/dev/ttyACM0`, `PORT_LEADER=/dev/ttyACM1` (à revérifier).

(Ce qui suit date du 2026-11-16 et avant.)

## Séance du 2026-11-16 (résumé, le plus récent d'abord)

**Enregistré et poussé sur Hugging Face (publics)** : modèle « poubelle » = pièce défectueuse -> zone verte.
- `Bixymax/so101_masque_poubelle_20261116_161455` : 27 épisodes (30 enregistrés, 0, 3 et 5 supprimés : deux
  pièces visibles sur `top` ou `side`) ; sauvegarde locale `…_161455_old` à supprimer.
- `Bixymax/so101_masque_poubelle_2_20261116_165836` : 20 épisodes, une seule pièce visible sur `top` et
  `side` à chaque début d'épisode (contrôle automatique 20/20).
- **Pas encore fait : le dataset « échange »** (pièce conforme -> zone bleue, touches `t r h e`, un seul
  dataset toutes formes mélangées, ~40 épisodes), ni la fusion des 2 datasets poubelle
  (`lerobot-edit-dataset --operation.type merge`, syntaxe à vérifier), ni l'entraînement.
- Cette version de LeRobot ajoute la date au nom du dataset (`repo_id` + `_AAAAMMJJ_HHMMSS`).

**Réglages / validation** : fond refait 15 h 36 ; références ×4 apprises (~52 échantillons par forme) ;
bilan sur 79 mesures étiquetées : 0 erreur de forme, 0 défaut classé OK, 0 bonne pièce classée défaut.
Correctifs : ambiguïté rond/hexagone (commit 2d4bb40) ; **rotation des cibles avec `n`** (`selection.py`,
**non commité** : avant, `n` redonnait toujours la pièce la plus isolée).

**Pièges rencontrés**
- L'épisode 0 démarre dès la connexion : poser les pièces, taper la touche (`d`, `r`...) ou `n` et vérifier
  `top` ET `side` dans Rerun AVANT de lancer `lerobot-record`.
- Pièces posées après le choix de la cible : restent visibles (verrou) -> `n` après avoir tout posé.
- Commande collée sur une ligne avec des `\` : « unrecognized arguments » -> une seule ligne sans antislash.
- Erreur `Torque_Enable id_=5 Incorrect status packet` au démarrage : liaison/alimentation du follower
  (rebrancher le câble du moteur 5, vérifier l'alimentation), pas un bug logiciel.
- La lumière dérive en fin de journée : l'image de `top` est devenue saturée/magenta pendant le flux alors
  que les épisodes enregistrés sont restés stables (cause non élucidée). Fond et références datent de
  15 h 36 ; à refaire dans la lumière de la prochaine séance (stores fermés, éclairage artificiel).
- Reste : étoile parfois non effacée sur `side` (références étoile avec un échantillon aberrant à 15,6 mm,
  non touchées) ; fantômes pâles des pièces effacées sur `top` ; hexagone long à choisir.

**Reprise** : checklist A à F (fond + références dans la lumière du jour), puis G pour le dataset
« échange », fusion, entraînement. Sauvegarde de `fonds/` : `~/sauvegardes_pia/fonds_2026-11-16`
(`fonds/` n'est pas versionné). Index du jour : `SIDE=2 TOP=4 ANGLE45=0`, `PORT_FOLLOWER=/dev/ttyACM0`,
`PORT_LEADER=/dev/ttyACM1` (à revérifier : ils changent).

(Ce qui suit date du 2026-11-09 ; l'état à jour est ci-dessus.)

Dernière séance : **2026-11-09** (premier passage avec la checklist). Procédure complète :
`docs/checklist_enregistrement.md`. Ici : où on s'est arrêté, dans l'ordre.

## État à la fin de la séance

| Étape | État |
|---|---|
| A, B (environnement, bras calibrés, téléopération) | fait |
| C (caméras : `SIDE=4 TOP=2 ANGLE45=0` ce jour-là, à revérifier) | fait |
| D (fond, calibration vert + bleu + rouge, A5 mesuré) | fait, **mais fond de 17 h 05 à refaire dans la lumière définitive** |
| E (flux masqué 30 img/s) | **fait** |
| F (conformité) | **à refaire** : `references.json` appris sous une autre lumière, formes à réapprendre |
| G (essai 3 épisodes, puis série) | **pas commencé** |

Rien n'a encore été enregistré. Datasets prévus : `Bixymax/so101_masque_echange_<forme>` et
`Bixymax/so101_masque_poubelle`.

## Reprise, dans l'ordre

1. **Matériel et environnement** : checklist A et B. Conda `lerobot` seul (pas de `.venv`), les deux
   bras alimentés, ports re-relevés (`lerobot-find-port`) : `local.env` contenait
   `PORT_LEADER=/dev/ttyACM0`, `PORT_FOLLOWER=/dev/ttyACM1` à la fin de la séance, mais ils changent.
2. **Lumière** : stores fermés, éclairage artificiel seul. C'est la cause de la majorité des ennuis
   de la séance (fond de 14 h 46 inutilisable à 17 h : un côté de la table « différait du fond »).
3. **Caméras** : vérifier `top` / `side` à l'écran, `reglages`, puis `capture` du fond (table vide, bras
   au repos). Refaire `cliquer` / `voir` seulement si une caméra a bougé.
4. **Réapprendre les 4 formes** : `rm fonds/references.json`, puis `apprendre` ×4 dans la **zone
   rouge**, 10 à 15 positions chacune. Puis `verifier` (OK vertes ; rond jaune et hexagone déformé
   rouges ou orange).
5. **Flux masqué** (terminal 1) puis téléopération sur les caméras virtuelles (terminal 2) : contrôle
   visuel dans Rerun.
6. **Essai de 3 épisodes** sans push (checklist G), puis la série de 50 épisodes d'un seul tenant.

## Ce qui a été corrigé (code, non commité : voir la fin)
- Débit : `flux_masque.py` demandait 1 tampon V4L2, ce qui divisait le débit des C310 par deux
  (15 img/s). Maintenant 2 tampons ; effacement dans un rectangle (6 ms au lieu de 34) ;
  détection dans un fil à part. Résultat : 30 img/s, < 33 ms.
- Lumière : le gain de luminosité du fond est maintenant **local** (avant : un seul gain par canal).
- Suivi : objets hors des zones de pièces (`zones_pieces`) ignorés (bord de table, robot) ; une pièce
  partie est oubliée en ~1 s au lieu de 50 s (les cadres orange effaçaient le bras).
- Conformité : contrôle de **teinte par canal** (un rond jaune passait pour orange), taille jugée
  seulement dans la zone apprise, état LIMITE (orange) dans `verifier`, affichage lisible
  (badges + bandeau noir sous l'image, option `--echelle`).
- 41 tests (`.venv/bin/python -m pytest -q`).

## Points ouverts
- **Pièces collées vues de `side`** : elles forment un bloc rattaché à la cible, donc les voisines
  restent visibles. Piste : séparer les blocs par couleur (`masquage.py`). Contournement : espacer
  les pièces à l'alimentation.
- **Pièces de la zone bleue** : visibles sur `side` (qui ne voit pas la zone, calibration par
  extrapolation) et parfois sur `angle45`. À décider : les pièces déjà déposées dans l'échange
  doivent-elles être effacées sur toutes les caméras ?
- **Rond / hexagone** : contours proches, 4 hexagones sur 69 classés rond. Rapprocher `top` aiderait.
- **Tolérance de taille** : `taille_k = 3`. Avec `taille_k = 2`, une déformation de 2 à 3 % est
  détectée (5/6 au lieu de 2/6) mais une dérive de lumière suffit à refuser des pièces conformes.
  À retenter avec un éclairage stable.
- **Fantômes pâles** des pièces effacées : devraient disparaître avec un fond pris dans la lumière
  définitive ; à vérifier (ils laissent deviner la forme au modèle).
- Proposés, jamais acceptés : mode « pièce quelconque » (touche `p`), option `--auto` de re-choix de
  cible, `recalage.py`. À reproposer.
- Protocole TCP avec P-Robo : `docs/protocole_tcp.md` (v2 du 2026-11-25), pas encore validé.
- `docs/` contient des captures non référencées (noms avec espaces) : les renommer ou les supprimer.

## Nouveau depuis la séance du 2026-11-09 (travail à la maison, à valider au local)

Pourquoi : la forme (rond / hexagone) et le verdict bon / défectueux décident de l'étiquette des
épisodes. Une erreur du logiciel = une mauvaise étiquette apprise par le modèle.

- **Forme au contour renforcée** (`conformite.py`) : régularité radiale + harmoniques 3, 5, 6 du profil
  du contour ; planchers de dispersion abaissés (0,03 rendait les 18 pièces jaunes de la dernière séance
  toutes ambiguës). **Non validé sur de vraies images** : seulement images synthétiques et 18 mesures.
- **Pièces « incertaines »** (`?`) : forme ambiguë / inconnue ou contrôle à moins de 25 % de sa limite.
  Le flux ne les choisit jamais (`selection.py`).
- **Mode manuel** (`flux_masque.py`) : `l` liste les pièces, un numéro montre cette pièce sans aucun
  jugement du logiciel.
- **`scripts/bilan_formes.py`** : matrice de confusion forme et bon/défectueux à partir de
  `fonds/mesures_v2.csv` (colonnes `vraie_forme` et `vraie_etat` à remplir à la main).

## Plan de la séance (ordre)

1. Checklist A-E comme avant (lumière : stores fermés, éclairage artificiel seul).
2. **Pièces étalon prêtes** (voir A) : forme + état connus, numérotées.
3. F : `rm fonds/references.json`, `apprendre` ×4 (10-15 positions, zone rouge) : OBLIGATOIRE, l'ancien
   fichier n'a pas les nouvelles mesures de forme.
4. F : passer chaque pièce étalon dans `verifier`, `c`, remplir le csv, `python scripts/bilan_formes.py`.
   **Décision à prendre selon le résultat** : (a) 0 erreur -> flux automatique ; (b) confusion
   rond/hexagone -> rapprocher `top` puis recommencer ; (c) pas réglable -> mode manuel en G.
5. **Rapporter le csv** (ou la sortie de `bilan_formes.py`) à Claude : calibrer les seuils d'ambiguïté
   (`AMBIGUITE_MIN`, `ZONE_INCERTAINE`, planchers `SIGMA_VECTEUR_MIN`) sur les vraies erreurs.
6. G : essai de 3 épisodes sans push, puis série.

## Pas encore fait
- Journal par épisode (n° de pièce choisie, verdict du logiciel) pour filtrer a posteriori : proposé,
  pas accepté.
- Si le dataset est étiqueté par le logiciel, les erreurs d'étiquette y entrent : le bilan de l'étape 4
  dit si c'est tolérable.

## À commiter
Modifié mais non commité : `conformite.py`, `selection.py`, `flux_masque.py`, `tests/test_conformite.py`,
`docs/*.md`, `scripts/bilan_formes.py`. `fonds/` n'est pas versionné, hormis `points_table.json`.
Les captures non suivies de `docs/` et de la racine sont à renommer ou supprimer.
