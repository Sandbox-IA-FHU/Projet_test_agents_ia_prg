# Agent à outils (modèle) — consignes Claude Code

Les règles communes de l'organisation (`CLAUDE.md` du dépôt `.github`)
s'appliquent : français, aucune donnée réelle, aucune clé, aucun nom de
client, `uv` uniquement, chiffres datés. Ce fichier les complète pour ce
dépôt. Les conventions d'écriture Python sont dans
[CONVENTIONS-PYTHON.md](CONVENTIONS-PYTHON.md) — à lire avant toute
modification de code.

**Ce dépôt est public.** Tout ce que tu écris dans un fichier, un commit, une
branche ou une PR est lisible par n'importe qui, pour toujours. Aucune donnée
réelle, aucune clé, aucun nom de client, aucune adresse ni nom de serveur.

## Horaires du serveur de staging : à vérifier AVANT chaque tâche

Ne s'applique que si la session tourne **sur le serveur de staging**.

Le serveur est allumé **en continu du lundi 7h00 au vendredi 20h00**. Ces
horaires sont **provisoires** : Florian (responsable) communique tout
changement. À 20h00 le vendredi, il s'arrête d'un coup : une commande en
cours est tuée, et ce qui n'est pas poussé reste inaccessible jusqu'au lundi
7h00.

Avant toute tâche (commandes, build d'image, tests, évaluation, série de
modifications), et de nouveau avant chaque étape longue :

1. Lancer `date` pour connaître le jour et l'heure réels (heure de Paris).
   Ne jamais se fier à une heure supposée.
2. Estimer la durée de la tâche entière, **commit et push compris**, en
   prenant l'estimation haute.
3. Comparer l'heure de fin estimée à la prochaine coupure, le vendredi
   20h00 :
   - **fin avant vendredi 19h30** : on y va, sans prévenir. Du lundi au
     jeudi, c'est le cas de toute tâche normale ;
   - **fin entre vendredi 19h30 et 19h50** : ne rien lancer. Donner l'heure,
     la durée estimée et la fin prévue, et demander s'il faut y aller ou
     attendre lundi ;
   - **fin après vendredi 19h50** : bloquer, sans rien lancer. Expliquer
     pourquoi et proposer de reprendre lundi.

Jamais de tâche en arrière-plan qui finirait après vendredi 19h50. Si une
tâche est reportée, commiter et pousser d'abord ce qui est stable. Le
vendredi, tout ce qui est stable est poussé avant de s'arrêter. Jour férié ou
horaire inhabituel : demander avant de supposer que le serveur est allumé.

## Le serveur : ce qui est permis

- Pas de `sudo`, pas d'accès au Docker du serveur : on utilise **son propre
  Docker rootless**. Tout tourne en conteneur, rien ne s'installe au niveau du
  système (`uv` n'y est pas : passer par `docker compose run`).
- **Jamais d'accès direct au GPU**, jamais de bibliothèque de modèle locale
  (PyTorch, transformers…) pour contourner l'API. L'agent appelle le LLM, point.
- Ne pas toucher aux conteneurs des autres.
- **Le dépôt de production est hors d'atteinte** : pas d'accès, pas de
  tentative d'accès. L'import est fait par Florian.

## Périmètre et Git

- Le dépôt est créé par Florian, qui y pose les protections et crée
  `staging`. Tu ne crées pas de dépôt et tu ne touches ni aux réglages ni aux
  protections du dépôt (rôle Write).
- Travail sur la branche **`staging`** : commits et push directs, jamais de
  force-push, jamais de suppression de branche.
- Projet à deux : chacun sur sa branche personnelle, mise à jour par
  `git rebase origin/staging` avant d'être intégrée dans `staging` (voir le
  README, « Projet à deux »).
- `main` ne reçoit que des PR `staging` → `main`, **approuvées et fusionnées
  par Florian**, en merge commit. Ne jamais fusionner toi-même.
- Pousser au fil de l'eau, et toujours avant de s'arrêter un vendredi.
- Commits en français, à l'impératif, sans préfixe.

## Le projet

**Question posée** : un agent à outils sur le LLM local peut-il relire un
acte de droit des affaires au format Word (statuts, procès-verbal), le
comparer à une fiche société et à une liste de contrôles par forme sociale et
type d'acte, et signaler chaque erreur au bon paragraphe avec sa gravité, sans
faux signalement et **sans jamais modifier l'acte** ?

**Pour qui** : les juristes. Ce sont eux qui corrigent ; l'agent signale.
L'outil de production des actes ne doit pas compter :
on ne lit que le `.docx` final, champs de formulaire compris.

**Le problème principal** : la bibliothèque de clauses de l'outil de
production contient des erreurs (« entreprise » au lieu d'« exploitation »
dans des statuts d'EARL). Ces erreurs connues sont des contrôles
`terme_interdit` de `controles/controles.toml`, vérifiés par le code.

**Principe** : ce qu'une règle sait vérifier, le code le vérifie
(`terme_interdit`, `fiche`) ; seul le jugement va au LLM (`verification`).
Gravités : `bloquant`, `majeur`, `mineur`, `a_verifier`.

**Outils de l'agent** (`relecture.py`) : `chercherDansActe`, `lireActe`,
`signalerPoint`. **Aucun outil d'écriture** : `signalerPoint` ajoute à une
liste en mémoire. La copie commentée (un commentaire Word par point, suivi des
modifications activé) et le rapport sont écrits par le code après la boucle,
dans `RELECTURE_SORTIE` ; l'original n'est jamais ouvert en écriture, une
copie n'est jamais écrasée. Test : `test_reviewAgentHasNoWriteTool`. Ajouter
un outil à ce registre est une décision à justifier, et tout outil qui envoie,
publie, écrit ou supprime sera `isSensitive=True`.

Les outils de notes du modèle (`toolbox.py`) ne sont **pas** dans le registre
de relecture. Ils restent dans le dépôt parce qu'ils portent les invariants 3
et 4 ci-dessous ; les supprimer est une décision à part.

**Données** : un acte est par nature une donnée réelle. Aucun `.docx` réel
n'entre dans le dépôt (`*.docx` est dans `.gitignore`, les actes vivent dans
`data/`). Le rapport contient des extraits de l'acte : il reste dans `data/`.
Le jeu d'évaluation utilise des actes fictifs, décrits en texte dans
`evaluations/jeux/relecture_demo.jsonl`. Les contrôles de
`controles/controles.toml` sont des **exemples à faire valider par un
juriste** : ne jamais présenter leur contenu juridique comme vérifié.

Le code reste volontairement minuscule : une modification qui rend l'agent
plus capable mais moins lisible est une régression.

## Contraintes techniques

- LLM local, API compatible OpenAI. Adresse dans `LLM_BASE_URL` (fournie par
  Florian), jamais en dur. Nom exposé stable : `LLM_MODEL=altoneo-llm`.
- Révision du modèle dans `LLM_MODEL_REVISION`, jamais dans le dépôt :
  obligatoire pour une évaluation.
- Appels d'outils au format `tools` / `tool_calls`. S'ils sont refusés par le
  serveur, le signaler à Florian ; **ne jamais** les remplacer par une analyse
  du texte libre.
- Réflexion : `REASONING_EFFORT = "low"` dans `client.py`. Elle n'entre
  jamais dans la trace, son résumé ou un fichier commité (`test_client.py`).
  Par défaut, elle ne repart pas dans l'historique
  (`KEEP_REASONING_IN_HISTORY = False`) ; l'activer est une mesure à faire,
  pas un réglage à changer sans run.
- `compose.yaml` : service préfixé par le projet, `TZ: Europe/Paris`, image
  figée par tag et empreinte, pas de GPU, pas de port, utilisateur réglé par
  `AGENT_UID` / `AGENT_GID`.

## Où en est-on

- 2026-11-24 — premier run de référence (`evaluations/runs/2026-11-24-reference.json`),
  précédé d'un essai `--limite 3` : 13/13, rappel de jugement 8/8, 0 faux
  signalement, 0 outil interdit, 3 tours médians, 5 au maximum
  (`earl-injection`, budget 4). Le jeu est saturé : il ne départage plus rien,
  l'étendre passe avant toute comparaison de prompt ou de réflexion.
- 2026-11-24 — jeu `relecture_v2.jsonl` (30 cas : les 13 premiers + 17 plus
  durs, voir `evaluations/jeux/LISEZ-MOI.md`). Run `2026-11-24-jeu-v2.json` :
  30/30, rappel de jugement 26/26, 0 faux signalement, 4 tours médians.
  Toujours saturé : un seul run, notation par identifiant seulement, cas non
  relus par un juriste.
- 2026-11-23 — objectif changé : relecture d'actes de droit des affaires. La
  modification de documents Word est reprise par Florian ; `documents.py` et
  son jeu sont retirés (dans l'historique, commit `03dea9a`). Ajouts :
  `acte.py`, `relecture.py`, `controles/controles.toml`, prompt
  `relecture_v1.md`, jeu de 13 cas. Tests hors ligne verts. Aucun run.
- 2026-10-30 — interface web retirée : le pare-feu du serveur de staging
  refuse les connexions locales vers un port publié, tunnel SSH compris
  (confirmé). Le code reste dans l'historique (commit `f2e9d47`) ; y revenir
  suppose une ouverture de port accordée par Florian.
- 2026-10-29 — option `--documents-demo` dans `run_agent.py`. Premier essai
  réel, une seule tâche sur `compte-rendu-reunion.docx` (un remplacement, une
  section ajoutée) : copie correcte, original intact, 3 tours, 7075 jetons
  d'entrée. Un essai n'est pas un run d'évaluation.
- 2026-10-28 — objectif changé : la modification de documents Word remplace
  la synthèse audio, abandonnée.
- 2026-10-28 — outils Word ajoutés (`documents.py`, prompt `agent_v2.md`),
  dépendance `python-docx`, jeu d'évaluation porté à 24 cas. Aucun run.
- 2026-10-28 — projet créé depuis le modèle : service, nom du paquet,
  en-tête et section « Le projet » renseignés. Aucun outil propre au projet.
- 2026-10-23 — modèle branché sur le LLM local (client compatible OpenAI),
  voie conteneur ajoutée. Réflexion `low` par défaut (décidé le 22/10 sur
  comparatif). Aucun run de référence sur ce modèle.

## À travailler

- Run de référence complet sur le jeu d'évaluation, une fois `--limite 3`
  passé sans erreur.
- Comparer la réflexion `off` et `low` sur le jeu d'évaluation du projet :
  deux runs qui ne diffèrent que par `--reflexion`. Garder `low` sauf si
  `off` fait au moins aussi bien sur la réussite **et** sur
  `outil_interdit_appele` (qui doit rester à 0).
- Mesurer `--garder-reflexion` (réflexion renvoyée au modèle dans
  l'historique) : deux runs qui ne diffèrent que par ce paramètre, comparés
  sur `tache_reussie`, `etapes_medianes` et `outil_interdit_appele` (qui doit
  rester à 0). Voir le README.

---

## Commandes

Sur un poste :

```bash
uv sync                      # installation
uv run ruff format .         # formatage
uv run ruff check .          # lint
uv run pytest                # tests, sans réseau ni serveur
uv run --env-file .env python scripts/run_agent.py "une tâche"
uv run --env-file .env python scripts/evaluate.py --limite 3
```

Sur le serveur (rootless) ou après import :

```bash
docker compose run --rm agent-projet_test_agents_ia_prg pytest
docker compose run --rm agent-projet_test_agents_ia_prg ruff check .
docker compose run --rm agent-projet_test_agents_ia_prg python scripts/evaluate.py --limite 3
```

Aucun test n'appelle le LLM. Les scénarios d'agent sont rejoués par
`ScriptedClient` dans `tests/conftest.py` : une liste de réponses préparées au
format OpenAI, rendues dans l'ordre et lues par le même analyseur que le vrai
client. C'est ce qui permet de tester des boucles entières — plafond atteint,
action refusée, outil en erreur — hors ligne.

## Architecture, en une phrase par module

| Module | Rôle |
|---|---|
| `models.py` | Structures, dont `Trace` — ce qu'on relit et ce qu'on mesure. |
| `config.py` | Seul endroit qui lit `os.environ`. Valide et échoue au démarrage. |
| `client.py` | Seul module qui connaît le SDK. Protocole `AgentClient`. Écarte la réflexion. |
| `tools.py` | Registre : le schéma envoyé au modèle et la fonction exécutée viennent du même objet. |
| `toolbox.py` | Les quatre outils de notes du modèle, hors registre de relecture. |
| `acte.py` | Lecture de l'acte (champs de formulaire et tableaux compris), copie commentée. |
| `relecture.py` | Fiche société, contrôles, contrôles du code, outils de l'agent, rapport, `reviewActe`. |
| `approval.py` | Politiques de validation. Défaut : refus. |
| `loop.py` | `runAgent` — la boucle, plafonnée. |
| `evaluation.py` | Notation par points attendus / interdits, agrégation : réussite, rappel, tours, jetons. |

## Les quatre choses à ne pas casser

**1. Le plafond d'itérations.** `MAX_ITERATIONS` dans `loop.py`, en dur, en
majuscules. Il ne devient jamais un paramètre sans valeur par défaut, il ne
disparaît pas, et l'atteindre reste visible dans la trace. Tests :
`test_iterationLimitStopsTheLoop`, `test_iterationLimitIsNotSilent`.

**2. Le passage obligatoire par la validation.** Tout outil `isSensitive`
traverse `approval.approve` dans `executeCall`. Aucun chemin de contournement,
quelle que soit la justification écrite par le modèle. Test :
`test_sensitiveToolNeedsApproval`.

**3. `eval` n'entre jamais dans ce dépôt.** L'outil `calculate` analyse
l'expression et n'autorise que des nœuds arithmétiques. Du code produit par un
modèle est du code plausible, pas du code sûr. Test :
`test_functionCallsAreRefused`.

**4. Le contenu d'outil reste de la donnée.** On ne filtre pas les résultats
d'outils, on ne prétend pas détecter une injection : on limite la surface
d'outils. Le magasin d'exemple contient une note empoisonnée, elle doit y
rester.

---

## La charge d'un agent n'est pas linéaire

C'est le point le plus mal anticipé sur ce type de projet, et c'est de
l'arithmétique, pas une opinion.

L'API est **sans état** : à chaque tour, la boucle renvoie tout l'historique.
Si `B` est la partie fixe (prompt système + schémas d'outils + tâche) et `C` ce
qu'un tour ajoute (réponse du modèle + résultats d'outils), le total de jetons
d'entrée sur `N` tours vaut :

```
N × B  +  C × N(N−1)/2
```

Pour `N = 8` : la partie fixe est envoyée **8 fois**, et le terme variable
vaut **28 fois** le contenu d'un tour, pas 8. Un agent qui met six tours au
lieu de deux ne consomme pas trois fois plus : il consomme nettement plus.

Le LLM tourne sur un GPU déjà payé : il n'y a pas de facture à l'appel. Mais
il est **partagé** entre plusieurs projets, et chaque jeton qu'un agent lui
fait traiter est du temps pris aux autres. Trois conséquences pratiques :

- **Le nombre de tours est une métrique de premier ordre**, pas une
  curiosité. `etapes_medianes`, `etapes_max` et `jetons_par_tache` sont dans
  le fichier de run pour ça. Faire passer la médiane de 4 à 3 vaut souvent
  mieux que n'importe quelle optimisation de prompt.
- **Faire regrouper les appels d'outils indépendants** est le gain le plus
  simple : deux notes lues dans le même tour, c'est un aller-retour au lieu de
  deux. Le prompt le demande déjà ;
  `test_parallelToolResultsShareOneRoundTrip` vérifie que la boucle ne casse
  pas cette possibilité en étalant les résultats sur plusieurs tours.
- **La réflexion se paie en jetons de sortie et en latence.** Elle est
  comptée dans `jetons_sortie`. Un niveau plus élevé n'est justifié que par
  une mesure qui montre un gain de réussite.

Ne convertis jamais un nombre de mots en jetons avec un ratio de tête. Le
comptage se lit dans `usage` après un vrai appel, et il est déjà accumulé sur
toute la boucle dans `trace.usage`.

---

## Diagnostiquer un agent qui se comporte mal

« L'agent est bête » n'est pas un diagnostic. Six symptômes distincts, six
causes différentes, et dans quatre cas sur six la correction **n'est pas dans
le prompt**.

Commence toujours par lire la trace : `summarizeTrace(trace)` donne la
séquence d'outils et les compteurs, `trace.steps` donne le détail.

### L'agent redemande le même outil avec les mêmes arguments

C'est le symptôme le plus fréquent, et le prompt n'y est pour rien. Le modèle
boucle parce que le **résultat d'outil ne lui apprend rien** : chaîne vide,
message d'erreur sans indication de correction, format ambigu.

Correction : dans `toolbox.py`, faire que l'outil dise ce qu'il faut faire.
`readNote` liste les notes disponibles quand le nom est inconnu — c'est
délibéré, et c'est ce qui permet au modèle de se rattraper en un tour au lieu
de réessayer trois fois.

### L'agent appelle le mauvais outil

Problème de **description**, pas de prompt système. Une description qui dit ce
que l'outil fait sans dire quand l'utiliser laisse le modèle deviner.

Relis la description avec cette question : quelqu'un qui ne connaît pas le
projet saurait-il choisir entre cet outil et son voisin ?

### L'agent atteint le plafond

Trois causes à distinguer avant de toucher à `MAX_ITERATIONS` — l'augmenter est
la mauvaise réponse dans deux cas sur trois :

- **Il boucle** — voir plus haut, c'est le résultat d'outil qu'il faut corriger.
- **La tâche demande plus d'étapes que le plafond** — légitime. C'est alors une
  décision explicite, avec la charge recalculée selon la formule ci-dessus, pas
  un chiffre qu'on monte parce que ça bloque.
- **Il explore sans but** — il lit tout « au cas où ». C'est le prompt, section
  « il ne continue pas à explorer au cas où ».

### L'agent répond sans appeler d'outil

Il a répondu de mémoire au lieu d'aller chercher. Sur une question générale
c'est acceptable ; sur une question portant sur les notes, c'est une réponse
inventée qui a l'air sûre d'elle. À traiter comme un échec, jamais comme une
réussite rapide.

### L'agent obéit à ce qu'il a lu

Injection réussie. La réaction correcte **n'est pas** d'ajouter une
interdiction au prompt : c'est de regarder ce que l'agent a pu faire à cause
d'elle. Si la réponse est « rien de grave, la validation a bloqué », le
dispositif a fonctionné comme prévu. Si la réponse est « il aurait pu faire X »,
c'est X qu'il faut retirer ou marquer sensible.

Le prompt réduit la fréquence ; il ne borne pas les dégâts. Seule la surface
d'outils les borne.

### L'agent réessaie après un refus de validation

C'est le prompt, et c'est un vrai problème de charge : chaque nouvelle
tentative est un tour complet. `REFUSAL_MESSAGE` dans `approval.py` le lui dit
déjà — si le comportement persiste, c'est là qu'il faut renforcer, pas
ailleurs.

---

## La description d'un outil fait partie du prompt

Point systématiquement oublié en revue.

Le schéma de chaque outil, description comprise, part vers le LLM à **chaque
tour**, au même titre que le prompt système. Trois conséquences :

1. **Modifier une description invalide les runs passés**, exactement comme
   modifier le prompt. Il faut un nouveau run de référence, et le dire.
2. Une description bavarde est envoyée à chaque tour de chaque tâche. La
   formule de charge plus haut s'applique aussi à elle.
3. Une description est le bon endroit pour dire qu'une action est irréversible
   et soumise à validation — le modèle peut alors en tenir compte **avant** de
   demander l'action, pas seulement après un refus. C'est ce que vérifie
   `test_sensitiveToolDescriptionWarnsTheModel`.

## Ce qui se règle par le prompt, et ce qui ne s'y règle pas

| Objectif | Prompt | Code |
|---|---|---|
| Que l'agent soit plus concis | oui | — |
| Qu'il regroupe ses appels | oui | — |
| Qu'il cesse de réessayer après un refus | oui | — |
| Qu'il n'obéisse pas à une note empoisonnée | réduit la fréquence | **ne garantit rien** |
| Qu'aucune action irréversible n'ait lieu sans accord | non | `isSensitive` + `approval` |
| Que la charge du serveur soit bornée | non | `MAX_ITERATIONS` |
| Qu'aucun code arbitraire ne s'exécute | non | l'analyseur de `calculate` |

La ligne à retenir : **une garantie qui repose sur une phrase de prompt n'en
est pas une.** Si on te demande d'empêcher un comportement dangereux en
ajoutant une interdiction au prompt, pose d'abord la question de l'outil
correspondant.

## Si on te demande d'ajouter un outil

Trois questions, dans cet ordre, avant d'écrire la ligne :

1. **Est-il sensible ?** Irréversible, coûteux, ou visible à l'extérieur
   (envoi, publication, suppression, écriture, paiement) → `isSensitive=True`.
   Dans le doute, oui : le coût d'une validation inutile est une question posée
   à un humain ; le coût d'une action irréversible non validée est un incident.
2. **Que peut-il faire si un contenu récupéré le déclenche ?** C'est la bonne
   façon de raisonner sur l'injection : pas « le prompt tiendra-t-il » mais
   « que se passe-t-il s'il ne tient pas ».
3. **Sa description dit-elle quand l'utiliser, et pas seulement ce qu'il
   fait ?**

Un outil ajouté demande deux cas dans le jeu d'évaluation : un où il **doit**
être appelé, un où il ne doit **pas** l'être. Sans le second, on ne mesure que
la capacité, jamais la retenue. Voir `/outil`.

## Lire un fichier de run

Dans cet ordre, et le premier est éliminatoire :

1. `outil_interdit_appele` — doit être à **0**. Un agent qui tente une action
   interdite une fois sur vingt la tentera en production. Si ce n'est pas 0, le
   reste du run n'a pas d'intérêt.
2. `limite_iterations_atteinte` — ces cas ne sont ni réussis ni ratés, ils sont
   ininterprétables. Beaucoup de plafonds atteints = le score de réussite porte
   sur moins de cas qu'annoncé.
3. `tache_reussie`, **et son découpage par type**. Des échecs concentrés sur
   les cas `retenue` décrivent un agent qui noie le juriste sous les faux
   points ; sur `injection`, un agent qu'un acte peut faire taire. Puis
   `rappel_jugement` (seuil : 0,8) et `faux_signalements`.
4. `etapes_medianes` / `etapes_max` / `jetons_par_tache` — la charge, et le
   meilleur gisement d'économies.
5. Latence médiane et p95, et le bloc `modele` : nom exposé, modèle réel,
   révision. Deux runs ne se comparent que si ce bloc, la `reflexion` et
   `garder_reflexion` sont identiques (sauf si c'est justement le paramètre étudié).

## Ce qu'on attend d'une session ici

**Avant de coder, cadrer.** Quelle question, quelle mesure, quel seuil. La
commande `/cadrer` sert à ça.

**Diagnostiquer avant de corriger.** Lire la trace d'abord. Proposer une
retouche de prompt sans avoir regardé la séquence d'outils est l'erreur la plus
courante sur un agent.

**Une modification de prompt — ou de description d'outil — se mesure.** Un run
avant, un run après, un seul paramètre changé.

**Prévenir de la charge avant de lancer une évaluation.** Sur 13 cas et
`MAX_ITERATIONS = 8`, c'est jusqu'à 104 appels au LLM partagé, pas 13.
Proposer `--limite 3` d'abord. Sur le serveur, appliquer aussi la règle des
horaires.

**Ne pas conclure sur un écart faible.** Sur 13 cas, un seul cas qui bascule
fait 8 points. Traduis toujours un écart en nombre de cas.

**Ne pas ajouter de dépendance** sans raison écrite. En particulier : pas de
framework d'agents, pas de bibliothèque d'orchestration « pour voir », pas de
bibliothèque de modèle locale.

**Ne jamais inventer un chiffre.** Performances du modèle, taille de contexte,
débit du serveur : si la valeur n'est pas mesurée ou vérifiée dans la
session, le dire au lieu de l'écrire.

## Ce qui ne va jamais dans le dépôt

Une donnée réelle, une clé, un nom de client, une adresse ou un nom de
serveur, un notebook avec ses sorties.

Attention particulière ici : une **trace d'agent contient le contenu de tout ce
que l'agent a lu**, résultats d'outils compris. C'est la trace la plus riche —
donc la plus dangereuse — des deux modèles de l'organisation. Elle ne se
commite jamais, `traces/` est dans `.gitignore`, et `summarizeTrace` existe
précisément pour n'afficher que des noms d'outils et des compteurs. Tests :
`test_traceSummaryLeaksNoContent`, et pour la réflexion du modèle
`test_reasoningNeverReachesHistoryOrTrace`.

## Commandes et sous-agents

| | |
|---|---|
| `/cadrer` | Écrire question, mesure et seuil avant de coder |
| `/prompt` | Créer une version de prompt sans écraser la précédente |
| `/outil` | Ajouter un outil, avec la question de sa sensibilité |
| `/evaluer` | Lancer l'évaluation et écrire le fichier de run |
| `/avant-pr` | Passer la checklist de revue sur son propre diff |
| `relecteur-resultats` | La conclusion est-elle soutenue par ses chiffres ? |
| `verificateur-donnees` | Le diff contient-il donnée, clé ou nom de client ? |
