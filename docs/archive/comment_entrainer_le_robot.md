# Comment entraîner le robot (SO-101) — Guide P-IA

> Guide pratique pour la partie « apprentissage » de la cellule de
> conditionnement, avec l'**imitation learning** (approche recommandée par
> le cahier des charges) et [LeLab](https://github.com/huggingface/leLab),
> l'interface graphique officielle de LeRobot (calibration, téléopération,
> enregistrement, entraînement, replay, inférence — sans ligne de commande).

## Vue d'ensemble du pipeline

Votre cellule doit faire deux choses de nature différente — ne les
confondez pas dans un seul modèle :

| Sous-tâche | Nature | Approche typique |
|---|---|---|
| Détecter et classifier une forme (type + conformité) | Perception / classification | **Vision classique OpenCV** (segmentation + contours, sans entraînement) |
| Saisir une pièce et la déposer (échange ou poubelle) | Manipulation / geste | **Imitation learning** avec le SO-101 |

Ce guide couvre la **manipulation** (le geste du bras). La détection/
classification est un autre chantier (vision), qui alimente ensuite la
politique de manipulation ou le code applicatif.

Le principe de l'imitation learning : vous téléopérez le bras follower
avec le bras leader pour **démontrer** le geste plusieurs fois (un
« épisode » = une démonstration), ces démonstrations sont enregistrées
comme un **dataset**, puis un réseau de neurones (la **politique**)
apprend à reproduire ce geste seul, à partir des images caméra.

**Prérequis matériel :**
- SO-101 (leader + follower) branché en USB.
- 3 caméras en place (`front`, `wrist`, `side`) — voir le schéma de
  placement fourni séparément.
- Pour entraîner sur le serveur GPU HELMo : accès SSH à ce serveur
  (demandez la procédure aux enseignants si vous ne l'avez pas encore).

## Étape 1 — Calibrer et vérifier le matériel dans LeLab

- Onglet **Add robots** : sélectionnez le type de bras (leader/follower),
  calibrez chaque articulation depuis la position médiane, puis attachez
  les 3 caméras.
- Onglet **Teleoperate** : bougez le leader et vérifiez que le follower
  suit fidèlement (visualisation 3D en direct), et que les 3 caméras
  cadrent bien ce qu'elles doivent voir (cf. schéma de placement) —
  aucune occultée par le bras ou un câble, éclairage stable.

Ne passez à l'enregistrement qu'une fois ces deux vérifications faites.

## Étape 2 — Découper la tâche en démonstrations homogènes

N'enregistrez pas « faire toute la cellule » en une seule tâche confuse.
Découpez en gestes **cohérents et répétables**, par exemple :

1. *« Attraper une forme conforme sur le tapis et la déposer dans la zone
   d'échange »*
2. *« Attraper une forme non conforme et la déposer dans la zone
   poubelle »*

Chaque geste distinct = une description de tâche différente à renseigner
dans LeLab, éventuellement un dataset séparé si les gestes sont très
différents. Une
politique apprend mieux d'un comportement cohérent que d'un mélange de
comportements sans distinction claire.

## Étape 3 — Enregistrer les démonstrations

Onglet **Record** de LeLab : renseignez la description de la tâche, le
nombre d'épisodes, les durées d'épisode/reset, puis appuyez sur
**espace** pour passer d'un épisode à l'autre. LeLab peut pousser le
dataset vers le Hub en un clic (onglet **Upload**) une fois terminé.

**Points essentiels pour la qualité du dataset :**

- **Variez les positions** des pièces à chaque épisode — le cahier des
  charges précise que les formes arrivent à des positions aléatoires, le
  dataset doit refléter cette variabilité, pas toujours le même point de
  départ.
- **Gestes en une fois** : évitez les micro-corrections pendant la
  démonstration (un seul mouvement franc de saisie, un seul dépôt propre).
- **Caméras fixes immobiles** entre l'enregistrement et l'usage réel — ne
  les rebougez pas d'une séance à l'autre.
- **Éclairage stable** d'une prise à l'autre.
- **Combien d'épisodes ?** LeLab recommande au moins **30 épisodes**. Un
  premier comportement peut déjà émerger dès ~20 épisodes homogènes pour
  un geste simple. Commencez petit, évaluez, puis augmentez si le
  résultat n'est pas fiable.

**Spécifique à la tâche « poubelle » :** le bras n'apprend qu'un geste, il
ne sait jamais *pourquoi* une pièce y va (voir étape 6). Pour qu'il sache
la saisir quelle que soit son apparence :
- Démontrez avec les **4 formes**, pas juste une, et à des positions
  variées — comme pour la tâche échange.
- Une fois qu'un premier prototype fonctionne avec des pièces normales,
  ajoutez si possible quelques démonstrations avec de **vraies pièces
  défectueuses** (couleur modifiée, légèrement déformées) : la politique
  est conditionnée sur l'image caméra, elle généralisera mieux à ces cas
  si elle en a déjà vu quelques-uns. Pas obligatoire pour démarrer.

## Étape 4 — Entraîner une politique

Deux politiques adaptées à un bras unique avec 3 caméras :

| Politique | Avantages | Quand la choisir |
|---|---|---|
| **ACT** (Action Chunking with Transformers) | Rapide à entraîner (quelques heures sur GPU), bon pour un geste précis et répétitif | Une tâche simple et bien définie |
| **SmolVLA** | Généralise mieux, peut conditionner le geste sur une instruction textuelle | Plusieurs tâches/variations (ex. conforme vs non-conforme) |

Deux façons d'entraîner, selon le GPU que vous voulez utiliser :

- **Dans LeLab** — onglet **Train** (entraînement local, sur la machine où
  tourne LeLab) ou **Cloud training via HF Jobs** (GPU à la demande chez
  Hugging Face, payant). Pratique, mais n'utilise pas le serveur HELMo.
- **Sur le serveur GPU HELMo** (fourni par l'école, gratuit) — une fois le
  dataset poussé sur le Hub, connectez-vous en SSH au serveur et lancez
  `lerobot-train` directement en ligne de commande (LeLab n'est pas
  nécessaire pour cette étape, seul `lerobot` doit y être installé) :

```bash
# ACT
lerobot-train \
  --dataset.repo_id=${HF_USER}/nom_du_dataset \
  --policy.type=act \
  --output_dir=outputs/train/act_conditionnement \
  --job_name=act_conditionnement \
  --policy.device=cuda \
  --wandb.enable=true

# SmolVLA
lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --dataset.repo_id=${HF_USER}/nom_du_dataset \
  --batch_size=64 \
  --steps=20000 \
  --output_dir=outputs/train/smolvla_conditionnement \
  --job_name=smolvla_conditionnement \
  --policy.device=cuda \
  --wandb.enable=true
```

Adaptez `--dataset.repo_id` à votre dataset. `--wandb.enable=true` est
optionnel mais pratique pour suivre l'entraînement (nécessite
`wandb login`).

## Étape 5 — Évaluer et itérer

Le plus simple : onglet **Run inference** de LeLab, sélectionnez le
modèle entraîné dans votre liste, un clic suffit. En ligne de commande,
l'équivalent est `lerobot-record` pointé vers le checkpoint
(`--policy.path`), sans téléopération — le robot agit seul :

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_awesome_follower_arm \
  --robot.cameras='{"front": {...}, "wrist": {...}, "side": {...}}' \
  --dataset.single_task="Attraper une forme conforme et la déposer dans la zone d'échange" \
  --dataset.repo_id=${HF_USER}/eval_conditionnement \
  --dataset.num_episodes=10 \
  --policy.path=${HF_USER}/act_conditionnement
```

**Si le résultat n'est pas fiable :**
- Vérifiez que les démonstrations ne contenaient pas d'incohérences
  (caméra bougée, prises trop différentes les unes des autres).
- Ajoutez des épisodes, en particulier pour les cas où le robot échoue.
- Introduisez la variation **progressivement** (positions, puis
  éventuellement luminosité) plutôt que tout à la fois — le cahier des
  charges recommande d'éviter d'ajouter trop de variation trop vite.

## Étape 6 — Vision classique et dispatch vers la bonne politique

**Principe** : la classification (vision classique OpenCV, sans
entraînement) décide *avant* d'agir ; elle ne fait qu'aiguiller vers l'une
des deux politiques de manipulation entraînées à l'étape 4. Le bras
n'apprend qu'un geste — il ne « comprend » jamais la notion de
conformité, il ne sait pas pourquoi une pièce va à tel ou tel endroit.

**0. Calibration caméra → robot (préalable)** — la caméra donne des
coordonnées en pixels, le SO-101 a besoin de coordonnées dans son propre
repère. Le tapis étant plat, une simple **homographie** suffit
(`cv2.findHomography` avec 4 points de correspondance connus
pixel ↔ position réelle). C'est aussi le repère à utiliser pour la
coordonnée transmise au P-Robo — à convenir avec l'autre pôle.

**1. Segmentation** — HSV + seuillage pour isoler les pièces du fond du
tapis, `cv2.findContours` → un contour par pièce, centroïde = position.

**2. Forme** — teste d'abord la **solidité** (aire du contour / aire de
l'enveloppe convexe) : une étoile est nettement plus basse à cause de ses
pointes concaves. Pour les formes convexes restantes, `cv2.approxPolyDP`
(nombre de sommets : 3 = triangle, ~6 = hexagone) et la **circularité**
(4π·aire / périmètre²) proche de 1 = cercle.

**3. Conformité** — colorimétrie : couleur moyenne (HSV) de la pièce
comparée à la couleur attendue pour cette forme, hors tolérance = non
conforme. Déformation structurelle : taille/ratio du contour comparés à
une référence, écart au-delà d'un seuil = non conforme.

**4. Dispatch** — le code applicatif choisit la politique à exécuter :

```python
piece = classifier(image)  # vision classique OpenCV
if piece.conforme:
    policy_echange.run(pick=piece.position)
    notifier_p_robo(piece.position)   # TCP/IP, uniquement si conforme
else:
    policy_poubelle.run(pick=piece.position)
```

Les seuils/paramètres du classifieur se règlent et se testent
indépendamment du dataset du bras — aucun lien entre les deux pendant
l'entraînement.

## Étape 7 — Documenter au fil de l'eau

Le cahier des charges demande une documentation avec **justification des
choix**. Notez dès maintenant, à chaque itération :
- le nombre d'épisodes enregistrés et pourquoi,
- la politique choisie et ses hyperparamètres,
- les résultats d'évaluation (taux de réussite, échecs observés),
- les essais qui n'ont pas fonctionné et l'hypothèse sur la cause.

Cela vous fera gagner un temps précieux au moment de rédiger la
documentation technique finale.
