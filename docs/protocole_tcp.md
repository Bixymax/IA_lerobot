# Protocole TCP/IP de la zone d'échange P-IA ↔ P-Robo

**Statut : PROPOSITION (v1) à faire valider par P-Robo avant tout développement de la zone d'échange**
(exigence du cahier des charges). Implémentation de référence côté P-IA : `echange_tcp.py`
(testée dans `tests/test_echange_tcp.py`).

## 1. Objectifs

1. **Sécurité** : jamais les deux robots en même temps dans la zone d'échange (verrou).
2. P-IA indique à P-Robo **quelles pièces conformes** sont disponibles et **où** (mm).
3. Fonctionnement simple et robuste : si la liaison tombe, on choisit toujours le côté sûr.

## 2. Transport

- TCP, **P-IA = serveur** (port **5050**, modifiable), **P-Robo = client**. Un seul client P-Robo.
- Messages **JSON, un par ligne** (UTF-8, terminés par `\n`). Lisible à la main (`nc <ip> 5050`).
- Champs communs : `"v"` (version du protocole, **1**), `"type"`, `"id"` (entier croissant choisi par
  l'émetteur d'une requête). La réponse reprend `"re": <id de la requête>`.
- Messages **poussés** par P-IA (sans requête) : `ZONE_UPDATE`, `LOCK_AVAILABLE`.
- **Heartbeat** : P-Robo envoie `PING` toutes les 2 s ; P-IA répond `PONG`. Sans réponse pendant 6 s,
  P-Robo considère la liaison perdue (voir §5).
- Adresses IP : à convenir (réseau du local, IP fixes recommandées).

## 3. Repère des coordonnées

- **Millimètres**, repère de la table défini par P-IA (`fonds/points_table.json`) : origine = coin
  haut-gauche du rectangle repère, x vers la droite, y vers le robot P-IA.
- **À convenir avec P-Robo** : la position de ce repère par rapport à leur robot (la calibration du
  Stäubli vers ce repère est de leur ressort : le cahier des charges leur laisse l'étalonnage).
  Proposition : on matérialise sur la nappe 2 à 3 repères communs que les deux équipes mesurent.
- Orientation `theta_deg` : angle de la pièce dans ce repère, **optionnel** (`null` pour le rond).

## 4. Messages

### 4.1 Connexion

| Sens | Message | Contenu |
|---|---|---|
| P-Robo → P-IA | `HELLO` | `{"type":"HELLO","v":1,"id":1,"role":"probo"}` |
| P-IA → P-Robo | `HELLO_ACK` | `{"type":"HELLO_ACK","re":1,"zone":"FREE"}` (`zone` = `FREE`, `PIA` ou `PROBO`) |
| P-Robo → P-IA | `PING` / `PONG` | heartbeat |

Tout autre message avant `HELLO` est refusé (`ERROR`, code `NO_HELLO`). Version incompatible : `ERROR`
code `VERSION`.

### 4.2 Verrou de la zone

P-IA arbitre. États : `FREE` (libre), `PIA` (P-IA y travaille), `PROBO` (P-Robo y travaille).

| Sens | Message | Effet |
|---|---|---|
| P-Robo → P-IA | `LOCK_REQUEST` | demande d'entrer dans la zone |
| P-IA → P-Robo | `LOCK_GRANTED` | verrou accordé : P-Robo peut entrer ; P-IA **n'entre pas** |
| P-IA → P-Robo | `LOCK_DENIED` `{"holder":"pia"}` | refusé : P-IA est dans la zone. Attendre `LOCK_AVAILABLE` |
| P-Robo → P-IA | `LOCK_RELEASE` | P-Robo est sorti, bras hors de la zone |
| P-IA → P-Robo | `LOCK_RELEASED` | verrou libre |
| P-IA → P-Robo | `LOCK_AVAILABLE` | **poussé** quand P-IA libère le verrou |

Règles : pas de file d'attente ni de préemption (celui qui a le verrou le garde jusqu'à `RELEASE`) ;
P-IA ne dépose **jamais** une pièce sans avoir le verrou ; P-Robo n'entre **jamais** sans `LOCK_GRANTED`.

### 4.3 Inventaire de la zone

| Sens | Message | Contenu |
|---|---|---|
| P-Robo → P-IA | `GET_ZONE` | demande l'état |
| P-IA → P-Robo | `ZONE` | `{"stable":true,"holder":"FREE","pieces":[...]}` |
| P-IA → P-Robo | `ZONE_UPDATE` | **poussé** après chaque dépôt (liste complète) |
| P-Robo → P-IA | `PIECE_TAKEN` `{"piece_id":3}` | P-Robo a pris la pièce (verrou requis) |
| P-IA → P-Robo | `TAKEN_ACK` | inventaire mis à jour |

`stable:false` = P-IA est en train de déposer : les positions ne sont **pas** fiables, ne pas s'en servir.
Les pièces ne sont lues par P-Robo qu'avec `stable:true`, de préférence **après** `LOCK_GRANTED`.

Une pièce :

```json
{"id": 3, "forme": "triangle", "couleur": "rouge", "x_mm": 40.0, "y_mm": 25.0, "theta_deg": 30.0}
```

`forme` ∈ `triangle | etoile | hexagone | rond`. Seules des pièces **conformes** se trouvent dans la
zone d'échange (les défectueuses vont à la poubelle). `id` : numéro unique tant que la pièce est dans
la zone.

### 4.4 Erreurs

`{"type":"ERROR","re":<id>,"code":"...","msg":"..."}` — codes : `NO_HELLO`, `VERSION`, `BAD_JSON`,
`BAD_TYPE`, `NOT_HOLDER` (verrou requis / non détenu), `UNKNOWN_PIECE`.

## 5. Défaillances : on choisit toujours le côté sûr

| Situation | Comportement |
|---|---|
| Liaison perdue, **P-Robo détient** le verrou | Il le **garde** : P-IA n'entre pas. P-Robo se reconnecte (`HELLO`) puis `LOCK_RELEASE`, ou l'opérateur le remet à `FREE` après contrôle visuel (`reinitialiser()`). |
| Liaison perdue, **P-IA détient** le verrou | P-IA termine son geste, ramène le bras au repos, ne libère **qu'à la reconnexion** de P-Robo. P-Robo, sans `PONG` depuis 6 s, **n'entre pas**. |
| P-Robo plante après `LOCK_GRANTED` | Même cas : intervention opérateur. Aucun timeout automatique ne redonne la zone à P-IA. |
| Arrêt d'urgence d'un robot | Hors protocole (câblage/sécurité de chaque cellule) ; le verrou reste dans son état. |

## 6. Déroulements types

**P-IA dépose une pièce**

```
P-IA                                P-Robo
 │ prend le verrou (interne) : FREE → PIA
 │ ... dépose la pièce, bras au repos ...
 │ libère : PIA → FREE
 │──── ZONE_UPDATE {pieces} ─────────▶│
 │──── LOCK_AVAILABLE ───────────────▶│
 │◀─── LOCK_REQUEST ──────────────────│
 │──── LOCK_GRANTED ─────────────────▶│  FREE → PROBO
 │◀─── GET_ZONE ──────────────────────│  (peut relire)
 │──── ZONE {stable:true,pieces} ────▶│
 │                                    │ va chercher la pièce (x_mm, y_mm)
 │◀─── PIECE_TAKEN {piece_id:3} ──────│
 │──── TAKEN_ACK ────────────────────▶│
 │◀─── LOCK_RELEASE ──────────────────│  PROBO → FREE
 │──── LOCK_RELEASED ────────────────▶│
```

**P-Robo veut entrer pendant un dépôt** : `LOCK_REQUEST` → `LOCK_DENIED {holder:"pia"}`, puis il attend
`LOCK_AVAILABLE`.

## 7. Points à valider avec P-Robo

1. Format JSON par lignes et port 5050 : OK ? (sinon : binaire, autre port.)
2. **P-Robo veut-il aussi pousser une « demande de forme »** (ex. `REQUEST_PIECE {"forme":"etoile"}`) pour
   que P-IA dépose une forme précise ? Le cahier des charges décrit un flux « P-IA trie et dépose » ;
   `docs/architecture.md` suppose une demande P-Robo. À trancher : ce message est prévu en v1.1.
3. Repère commun des coordonnées (§3) et précision attendue de la position (mm).
4. Orientation des pièces (`theta_deg`) nécessaire pour leur pince ?
5. Dimensions et limites de la zone d'échange ; nombre max de pièces simultanées (4 attendues : une de chaque forme ?).
6. Délais : durée maximale d'un séjour de P-Robo dans la zone avant alerte opérateur (proposition : 60 s).
7. Où se trouvent les IP et qui lance quoi à la démo.

## 8. À faire côté P-IA

- [x] Spécification et serveur de référence (`echange_tcp.py`), tests sur sockets locales.
- [ ] Faire valider ce document par P-Robo (le modifier ensemble, puis fixer la version).
- [ ] Étendre la calibration (`fonds/points_table.json`) pour que la zone d'échange soit dans le champ
      de la caméra `top` : sinon P-IA ne peut pas mesurer l'inventaire, seulement le déduire de ses dépôts.
- [ ] Brancher l'orchestrateur : `prendre_pia` avant chaque geste de dépôt, `liberer_pia(inventaire)` après.
- [ ] Test d'intégration avec le vrai client P-Robo (ou `nc`) avant la démo.

## 9. Essayer à la main

```bash
python echange_tcp.py --port 5050        # P-IA simulé ; touche d = dépose un triangle
nc 127.0.0.1 5050
{"type":"HELLO","v":1,"id":1,"role":"probo"}
{"type":"LOCK_REQUEST","v":1,"id":2}
{"type":"GET_ZONE","v":1,"id":3}
```
