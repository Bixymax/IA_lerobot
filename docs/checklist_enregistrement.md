# Checklist : avant les premiers enregistrements (au local robot)

Objectif : 2 datasets distincts, enregistrés **via le flux masqué**, une pièce visible à la fois :
- `…_echange` : pièce conforme → zone d'échange ;
- `…_poubelle` : pièce défectueuse → zone poubelle.

Cases à cocher dans l'ordre. Chaque étape a un critère de réussite. L'état de la dernière séance
et ce qui reste à faire sont dans `docs/prochaine_session.md`.

Nappe : **rouge = alimentation** (pièces de départ), **vert = déchet** (poubelle, non conformes),
**bleu = échange** (conformes). Coordonnées en mm dans `fonds/points_table.json`.

## A. Avant de partir de chez soi
- [ ] `conda activate lerobot && pip install pyvirtualcam` ; `hf auth login --force`
- [ ] **N'utiliser QUE le conda `lerobot`** : ne pas activer le `.venv` du projet par-dessus (il masque
      `lerobot`). Les tests se lancent avec `.venv/bin/python -m pytest -q` (pytest n'est pas dans conda).
- [ ] `./setup_local.sh --sans-sudo` (voir ce qui manque)
- [ ] Imprimer : ce document, les 4 formes OK et quelques défectueuses à emporter (dont un rond d'une
      mauvaise couleur et une pièce déformée), règle graduée
- [ ] Ruban adhésif de couleur (repérer pieds des caméras, repasser les traits de la nappe)

## B. Matériel
- [ ] Brancher bras (leader, follower) et 3 caméras C310, **allumer l'alimentation des DEUX bras**
      (valeurs figées pendant la calibration = un bras non alimenté)
- [ ] `./setup_local.sh` → corriger les ✗ ; `nano local.env` ; `source local.env`
- [ ] `lerobot-find-port` (débrancher/rebrancher un bras) → `PORT_LEADER`, `PORT_FOLLOWER`
- [ ] `sudo chmod 666 $PORT_LEADER $PORT_FOLLOWER`
- [ ] Téléopération sans caméra (`manuel.md`) : le follower suit le leader. Sinon recalibrer
      (`manuel.md`) : à la question, **taper `c`** (Entrée seul réutilise l'ancienne calibration)

## C. Caméras
- [ ] `python masquage.py voir --cams side=$SIDE top=$TOP angle45=$ANGLE45` : **vérifier à l'écran
      que `top` est bien la vue du DESSUS et `side` la vue RASANTE** (inversion constatée en octobre)
- [ ] Cadrage : toute la zone d'alimentation + la zone d'échange + la poubelle visibles sur `top` ;
      marquer au scotch la position des pieds des caméras
- [ ] **Éclairage définitif : fermer les stores, éclairage artificiel seul, puis ne plus y toucher.**
      Le soleil qui tourne dans l'après-midi décale les couleurs et les tailles mesurées (constaté :
      fond de 14 h 46 inutilisable à 17 h).
- [ ] `python masquage.py reglages …` : figer exposition et balance des blancs (touche `q` pour sauver)

## D. Fond et calibration (table vide, bras au repos)
Faire D, E et F **dans la même heure et la même lumière** (fond, calibration et apprentissage
doivent correspondre).
- [ ] `python masquage.py capture …`
- [ ] Rectangle repère de la nappe mesuré à la règle (A5 = 210 × 148, **confirmé le 2026-11-09**) ;
      `zones_pieces` et `zone_alimentation` renseignées dans `fonds/points_table.json` (déjà fait)
- [ ] `python calibration.py cliquer …` : cliquer les coins du vert **et** du bleu **et** du rouge
      visibles ; `n` pour un point invisible (le bleu n'est pas visible sur `side`) ;
      puis `voir` : la grille colle à la nappe sur les 3 caméras
- [ ] `python masquage.py voir …` : toutes les pièces posées disparaissent, pas le bras

## E. Flux masqué
- [ ] `sudo modprobe v4l2loopback …` (fait par `setup_local.sh`) ; `v4l2-ctl --list-devices` liste les `*_masque`
- [ ] **Terminal 1** : `python flux_masque.py --cams side=$SIDE top=$TOP angle45=$ANGLE45 --forme triangle --detection-hz 3`
      (sans `--apercu --diagnostic` hors réglage : l'aperçu coûte cher)
- [ ] **30 img/s** et **< 33 ms** par caméra (atteint le 2026-11-09) ; sinon : `docs/flux_masque.md` (Dépannage)
- [ ] Plusieurs pièces dans la zone rouge : une seule visible (cadre vert), bras jamais effacé (câbles rouges !)
- [ ] Commandes (taper la lettre + Entrée dans le terminal 1) : `t r h e` formes OK, `d` défectueuse,
      `n` nouvelle cible (**après avoir replacé les pièces**), `a` aucune, `b`/`m` brut/masque, `q`
- [ ] **Terminal 2** : `lerobot-teleoperate` sur les caméras virtuelles 10, 11, 12 (sans `fourcc`),
      lancé APRÈS le terminal 1 : même vue dans Rerun
- [ ] Pas de « fantômes » pâles à la place des pièces effacées (sinon fond à refaire)

## F. Conformité (nécessaire pour le modèle « poubelle » et pour l'inférence)
- [ ] `rm fonds/references.json` (les références doivent venir de la lumière d'aujourd'hui)
- [ ] `python conformite.py apprendre --cam top=$TOP --forme <f>` pour les 4 formes : **10 à 15 positions
      chacune, DANS LA ZONE ROUGE, répartie partout** (la taille n'est jugée que là où on a appris)
- [ ] `python conformite.py verifier --cam top=$TOP` **dans la zone rouge** : les 4 formes conformes
      sont vertes ; le rond d'une mauvaise couleur et la pièce déformée sont rouges ou orange (LIMITE) ;
      relever `sigma` (un défaut < 3 × sigma n'est pas détectable). `c` enregistre dans `fonds/mesures.csv`.
- [ ] Ne pas resserrer `taille_k` tant que la lumière n'est pas stable (voir `docs/conformite.md`)

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
- [ ] Noter les problèmes rencontrés pour la prochaine session (`docs/prochaine_session.md`)
