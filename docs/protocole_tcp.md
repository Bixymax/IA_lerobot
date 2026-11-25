# Protocole TCP/IP commun P-IA ↔ P-Robo (zone d'échange)

**Statut : v2, à valider par les deux pôles.** Reprend le cahier des charges de P-Robo
(`Cahier des charges — Communication TCP IP Robot ↔ Vision.pdf`, 27/09/2026) pour les messages, et
précise ce qu'il laisse ouvert (§4, §5, §7). Remplace la proposition JSON précédente.
Implémentation côté P-IA : `echange_tcp.py` (dialogue), `mesure_echange.py` (coordonnées),
`cellule.py` (enchaînement).

## 1. Transport

| Élément | Valeur |
|---|---|
| Rôles | PC P-IA = **serveur**, contrôleur Stäubli (port J205) = **client** |
| Liaison | câble RJ45 direct, IP fixes **à convenir** |
| Port | TCP **5000** |
| Trames | texte ASCII, champs séparés par `,`, fin par `@` (code 64), **sans retour à la ligne** |
| Nagle | désactivé des deux côtés |
| Délai | le robot attend la réponse **sans limite de temps** |
| Clients | un seul ; une nouvelle connexion ferme l'ancienne |

## 2. Messages

| Message | Sens | Format | Exemple |
|---|---|---|---|
| Demande | Robot → Vision | `GET-Query,Forme@` | `GET-Query,Etoile@` |
| Pièce disponible | Vision → Robot | `GET-Respond,Forme,X,Y,RZ@` | `GET-Respond,Etoile,74.0,105.0,30.0@` |
| Pas de pièce | Vision → Robot | `GET-Respond,Forme,NONE@` | `GET-Respond,Etoile,NONE@` |
| Prise réussie | Robot → Vision | `ACK-Done,Forme@` | `ACK-Done,Etoile@` |
| Prise ratée | Robot → Vision | `ACK-NotDone,Forme@` | `ACK-NotDone,Etoile@` |
| Fin de cycle | Vision → Robot | `ACK-End@` | `ACK-End@` |

Formes, orthographe exacte : `Etoile`, `Cercle`, `Triangle`, `Hexagone`.
`X`, `Y`, `RZ` : point décimal, une décimale. La hauteur n'est **pas** transmise : elle est
constante et connue de P-Robo.

## 3. Cycle

```
Stäubli                                   PC P-IA (SO-101)
  │── GET-Query,Etoile@ ──────────────────▶│  le SO-101 dépose une étoile conforme,
  │        (attente, sans limite)          │  revient au repos ; mesure par la caméra du dessus
  │◀── GET-Respond,Etoile,X,Y,RZ@ ─────────│  ┐
  │    prend la pièce                      │  │ zone au Stäubli : SO-101 immobile
  │    SORT du plan de travail             │  │
  │── ACK-Done,Etoile@ ───────────────────▶│  ┘
  │◀── ACK-End@ ───────────────────────────│  le SO-101 peut retravailler
```

## 4. Repère `fEchange` et orientation (**à valider**)

- Zone d'échange : rectangle **bleu** de la nappe (148 × 210 mm, à mesurer).
- **Origine** : coin **bas gauche** vu par la caméra du dessus (côté SO-101).
- **X** vers la droite, **Y** vers le haut de l'image (s'éloigne du SO-101), **Z vers le plafond**
  (repère direct). Millimètres.
- Calibration commune : le robot apprend `fEchange` sur 3 points de la nappe : origine, coin bas
  droit (sur X), coin haut gauche (côté Y positif).
- **RZ** : degrés, **antihoraire** vu de dessus. `RZ = 0` : une **pointe** de la pièce vers +Y.

| Forme | Plage de RZ |
|---|---|
| Triangle | 0 à 120° |
| Étoile | 0 à 72° |
| Hexagone | 0 à 60° |
| Cercle | toujours 0 |

La position envoyée est le **centre** de la pièce.

## 5. Sécurité de la zone

Règle : **message douteux = personne ne bouge.** Aucun message de verrou : la zone appartient au
Stäubli entre l'envoi des coordonnées et son ACK.

Exigences côté P-IA :

- Coordonnées envoyées seulement après validation de l'opérateur, aucun programme LeRobot actif,
  zone dégagée et mesures stables sur plusieurs images.
- Jamais de message non demandé ni répété (il resterait dans le tampon du robot).

Exigence côté P-Robo (**à confirmer**) :

- `ACK-Done` / `ACK-NotDone` envoyés **seulement quand le bras est physiquement hors du plan de
  travail P-IA** (pas seulement `bCOM_ZoneAutorisee = false`).

Comportement du serveur P-IA dans les cas anormaux (« bloqué » = SO-101 immobile, aucune réponse
jusqu'à ce que l'opérateur confirme que le Stäubli est hors de la zone, touche `o`) :

| Situation | Comportement |
|---|---|
| Démarrage du serveur | bloqué ; une demande reçue entre-temps est traitée après confirmation |
| Trame inconnue, mal formée, forme mal écrite | ignorée et signalée, rien ne change |
| Liaison perdue pendant la préparation | demande annulée |
| Liaison perdue pendant que le Stäubli a la zone | bloqué ; la reconnexion seule ne débloque pas |
| ACK d'une autre forme, ou nouvelle demande sans ACK | bloqué |
| Envoi des coordonnées en échec | bloqué |
| ACK sans zone donnée | ignoré, sauf après `NONE` ou après déblocage : réponse `ACK-End@` |
| Nouvelle demande avant la réponse | la dernière forme demandée l'emporte |

## 6. Essais

| Essai | Commandes P-IA | Remplace |
|---|---|---|
| Communication seule, coordonnées **fictives** (mouvement robot désactivé) | `python echange_tcp.py` puis `o`, `v 130.5 46.2 30`, `x` | Hercules (tests T1 à T4, T8, T9) |
| Cellule complète sans le Stäubli | `python cellule.py …` et `python scripts/faux_staubli.py` | le robot |
| Les deux cellules | `python cellule.py …` | |

Les tests T5 à T7 (trames volontairement fausses) restent à faire avec Hercules.

## 7. Points à valider avec P-Robo

1. Le cahier des charges du 27/09 est-il la dernière version ?
2. ACK envoyé seulement bras sorti (§5) ?
3. Le Stäubli passe-t-il au-dessus du reste de la table (caméras, SO-101) ?
4. Repère `fEchange` et convention RZ (§4) ; précision nécessaire en X, Y, RZ.
5. IP et masque du port J205 ; IP à donner au PC P-IA.
6. Épaisseur des pièces en mm (sert à P-IA pour corriger la position vue par la caméra).
7. Après `NONE`, le robot envoie-t-il un ACK ou directement une nouvelle demande ?
8. Peut-il envoyer un second `GET-Query` avant l'ACK ?
9. Après `ACK-NotDone` : nouvelle mesure à la demande suivante, 3 essais au maximum ?
