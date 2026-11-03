# Checklist : avant les premiers enregistrements (au local robot)

Objectif : 2 datasets distincts, enregistrés **via le flux masqué**, une pièce visible à la fois :
- `…_echange` : pièce conforme → zone d'échange ;
- `…_poubelle` : pièce défectueuse → zone poubelle.

Cases à cocher dans l'ordre. Chaque étape a un critère de réussite.

## A. Avant de partir de chez soi
- [ ] `conda activate lerobot && pip install pyvirtualcam` ; `hf auth login --force`
- [ ] `./setup_local.sh --sans-sudo` (voir ce qui manque), `python -m pytest -q`
- [ ] Imprimer : ce document, les 4 formes OK et quelques défectueuses à emporter, règle graduée
- [ ] Ruban adhésif de couleur (repérer pieds des caméras, repasser les traits de la nappe)

## B. Matériel
- [ ] Brancher bras (leader, follower) et 3 caméras C310, allumer l'alimentation des bras
- [ ] `./setup_local.sh` → corriger les ✗ ; `nano local.env` ; `source local.env`
- [ ] `lerobot-find-port` : lequel est le leader / le follower → `PORT_LEADER`, `PORT_FOLLOWER`
- [ ] Téléopération sans caméra (`manuel.md`) : le follower suit le leader. Sinon recalibrer (`manuel.md`)

## C. Caméras
- [ ] `python masquage.py voir --cams side=$SIDE top=$TOP angle45=$ANGLE45` : **vérifier à l'écran
      que `top` est bien la vue du DESSUS et `side` la vue RASANTE** (inversion constatée en octobre). Corriger `local.env`.
- [ ] Cadrage : toute la zone d'alimentation + la zone d'échange + la poubelle visibles sur `top` ;
      marquer au scotch la position des pieds des caméras
- [ ] Éclairage définitif (fermer les stores, lumière stable), puis ne plus y toucher
- [ ] `python masquage.py reglages …` : figer exposition et balance des blancs (touche `q` pour sauver)

## D. Fond et calibration (table vide, bras au repos)
- [ ] `python masquage.py capture …`
- [ ] **Mesurer à la règle** le rectangle repère de la nappe ; corriger `fonds/points_table.json`
      (A5 = 210 × 148 supposé) ; ajouter `zone_alimentation` (polygone mm)
- [ ] `python calibration.py cliquer …` puis `voir` : la grille colle à la nappe sur les 3 caméras
- [ ] `python masquage.py voir …` : toutes les pièces posées disparaissent, pas le bras

## E. Flux masqué
- [ ] `sudo modprobe v4l2loopback …` (fait par `setup_local.sh`) ; `v4l2-ctl --list-devices` liste les `*_masque`
- [ ] `python flux_masque.py --cams side=$SIDE top=$TOP angle45=$ANGLE45 --forme triangle --apercu --diagnostic`
- [ ] 30 img/s et < 33 ms par caméra ; sinon : `docs/flux_masque.md` (Dépannage)
- [ ] Plusieurs pièces sur la table : une seule visible, cadre vert sur la cible, bras jamais effacé (câbles rouges !)
- [ ] `lerobot-teleoperate` sur les caméras virtuelles 10, 11, 12 (sans `fourcc`) : même vue dans Rerun

## F. Conformité (nécessaire pour le modèle « poubelle » et pour l'inférence)
- [ ] `python conformite.py apprendre --cam top=$TOP --forme <f>` pour les 4 formes (8 à 15 positions chacune)
- [ ] `python conformite.py verifier --cam top=$TOP` avec pièces OK **et défectueuses** : relever la dispersion `sigma`
      (un défaut < 3 × sigma n'est pas détectable ; sinon rapprocher/zoomer `top` ou mieux éclairer)

## G. Premier enregistrement (essai de 3 épisodes, sans push)
- [ ] Dataset de test : `--dataset.num_episodes=3 --dataset.push_to_hub=false`
- [ ] Pour chaque épisode : replacer les pièces, **refaire le choix de la cible** (touche de forme / `d` / `n`),
      vérifier le cadre vert, puis prendre cette pièce avec le leader
- [ ] Rejouer / relire le dataset : les images sont masquées, une seule pièce visible, 3 caméras synchronisées
- [ ] Si OK : supprimer le dataset de test, lancer la série (50 épisodes), **une séance d'un seul tenant**,
      sans toucher aux caméras ni à la lumière
- [ ] Noms de datasets : `Bixymax/so101_masque_echange_<forme>` et `Bixymax/so101_masque_poubelle`

## H. En partant
- [ ] Noter dans `local.env` les index utilisés ; `git add` / commit de `fonds/points_table.json` si modifié
- [ ] Noter les problèmes rencontrés pour la prochaine session
