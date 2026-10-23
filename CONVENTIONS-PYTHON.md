# Conventions Python

Complète le `CLAUDE.md` de l'organisation, ne le remplace pas. Ce qui est figé
partout : Python 3.13, `uv`, `ruff` (format et lint), `pytest`.

Ce fichier est **identique dans `rag-model` et `agentic-model`**. Une
modification dans l'un se reporte dans l'autre, par PR, dans la foulée. Deux
copies qui divergent sont pires qu'une seule copie imparfaite.

---

## 1. Nommage

C'est le seul endroit où cette organisation s'écarte de la PEP 8, et l'écart
est assumé, écrit, et appliqué par l'outil.

| Élément | Convention | Exemple |
|---|---|---|
| Fichier, module, paquet | `snake_case` | `answer_generation.py` |
| Classe, exception | `PascalCase` | `RetrievedPassage`, `EmptyContextError` |
| Constante de module | `MAJUSCULES_SNAKE` | `MAX_ITERATIONS`, `ANSWER_MODEL` |
| Variable, attribut | `camelCase` | `chunkSize`, `totalTokens` |
| Fonction, méthode | `camelCase` | `retrievePassages()`, `countTokens()` |
| Privé | préfixe `_` | `_normalizeText()` |

**Les identifiants sont en anglais**, comme partout dans l'organisation. Les
docstrings, les commentaires et les messages destinés à un humain sont en
français. `def compterLesJetons()` est doublement faux ; `def countTokens()`
avec une docstring française est juste.

Trois précisions qui évitent les allers-retours en revue :

- **Les clés des fichiers de données restent en `snake_case` français**, telles
  que documentées dans `EVALUATION.md` (`nb_cas`, `jetons_entree`,
  `latence_p95_s`). C'est un contrat de données lu par des humains et par
  d'autres outils, pas du code Python. La conversion se fait à la
  sérialisation, dans un seul module.
- **Les arguments nommés des bibliothèques tierces gardent leur nom.** On écrit
  `client.chat.completions.create(max_tokens=...)`, évidemment.
- **Les noms de fichiers de code sont en anglais** (`retrieval.py`), les noms
  de fichiers de documentation en français (`CONVENTIONS-PYTHON.md`). Un
  fichier `.py` est du code.

### Pourquoi cet écart, et ce qu'il coûte

La PEP 8 impose `snake_case` pour les variables et les fonctions. Le choix du
`camelCase` est une décision d'équipe, pour rester homogène avec les autres
dépôts du groupe. Il a un coût réel, qu'il vaut mieux connaître : le code sera
stylistiquement différent de toutes les bibliothèques qu'il appelle, et
quiconque arrive d'un autre projet Python le remarquera.

Ce qui n'est pas négociable, c'est que l'écart soit **unique, écrit et
mécanique**. Une dérogation appliquée par `ruff` est une règle ; une préférence
non outillée est une source de discussions en revue.

Tout le reste de la PEP 8 s'applique sans dérogation : mise en page, imports,
espacement, lignes vides, opérateurs. `ruff format` s'en charge, on ne le
discute pas.

### Comment c'est appliqué

Dans `pyproject.toml` :

```toml
[tool.ruff.lint]
# Convention maison : camelCase pour les variables, arguments et fonctions.
# Écart assumé à la PEP 8, voir CONVENTIONS-PYTHON.md § 1.
ignore = ["N802", "N803", "N806", "N815", "N816"]
```

`N801` (classes en `PascalCase`) et `N818` (exceptions suffixées `Error`)
restent actifs : la dérogation ne les concerne pas.

Longueur de ligne : **88 caractères**, le défaut de `ruff format`. C'est un
écart aux 79 de la PEP 8, universel dans l'écosystème et non discuté ici.

---

## 2. Typage

Toute signature publique est annotée. `X | None` plutôt que `Optional[X]`,
`list[str]` plutôt que `List[str]` — on est en 3.13.

Pas de `Any` sans un commentaire qui dit pourquoi. Un `Any` sur une réponse
d'API est presque toujours une `dataclass` qu'on n'a pas pris le temps
d'écrire.

**Pas de vérificateur de types dans la CI** pour l'instant. Ce serait un
cinquième outil dans un socle qui en compte quatre, et un job de plus dans le
workflow commun. Les annotations servent ici de documentation exécutable et
d'aide à l'éditeur. Décision réversible : si un dépôt en tire un bénéfice
mesurable, on en discute pour toute l'organisation, pas dans son coin.

---

## 3. Structure et imports

Disposition `src/` : le code du paquet vit dans `src/<paquet>/`, les tests dans
`tests/`, les points d'entrée en ligne de commande dans `scripts/`.

- Imports **absolus** uniquement. Pas de `from .module import`, pas de
  `import *`, pas de manipulation de `sys.path`.
- **Un module qui s'importe ne fait rien.** Pas de lecture d'environnement, pas
  d'ouverture de fichier, pas d'appel réseau, pas d'instanciation de client au
  niveau module. Tout cela se fait dans une fonction, appelée explicitement.

Cette dernière règle est celle qui rend les tests possibles sans serveur. Un
client construit au niveau module lit l'environnement à l'import : l'import
lui-même échoue quand une variable manque — donc la CI, qui n'a volontairement
ni vraie adresse ni vraie clé.

---

## 4. Configuration et secrets

Un seul module `config.py`, **seul endroit du dépôt où `os.environ` est lu**.
Partout ailleurs, on reçoit la configuration en argument.

- `os.environ["CLE"]` et pas `os.environ.get("CLE")`. Une clé absente doit
  faire échouer le démarrage avec un message clair, pas produire un `None` qui
  casse trois couches plus loin avec une trace incompréhensible.
- Aucun chemin en dur. Les chemins vers des données réelles arrivent par
  variable d'environnement — voir `DONNEES.md`.
- `.env.example` liste toutes les variables attendues, avec des **valeurs
  vides** (ou une valeur générique non secrète, comme un nom de modèle). Une
  variable ajoutée au code et pas à `.env.example` est un défaut. Ce nom exact
  est celui que le dépôt de production accepte de versionner.
- Aucune valeur par défaut pour un secret. Un défaut sur une clé masque l'oubli
  et produit une erreur d'authentification illisible. Une clé **vide** est
  admise quand le service n'en demande pas (LLM local sans passerelle) : elle
  est lue quand même, pour qu'une clé puisse arriver sans toucher au code.
- Une adresse de service ne s'écrit jamais en dur : elle arrive par variable
  d'environnement, et le démarrage échoue si elle manque.

---

## 5. Appels modèle

Un module client unique. Le reste du code ne connaît pas le SDK.

Le modèle par défaut de l'organisation est le **LLM local**, servi par une
API compatible OpenAI. Son adresse et son nom viennent de la configuration
(`LLM_BASE_URL`, `LLM_MODEL`), jamais écrits en ligne dans le code appelant.
Un modèle externe éventuel suit la même règle : identifiant en constante
majuscule ou en configuration, jamais en ligne.

**Un nom de modèle n'est pas une version.** Le LLM local est exposé sous un
nom stable, qui ne change pas quand le modèle derrière change ; un fournisseur
externe a souvent des alias qui bougent de même. La reproductibilité repose
donc sur le fichier de run, qui consigne le nom utilisé, **le modèle réel et
sa révision**, et la date d'exécution. Deux scores sur le même nom à deux
dates ne sont pas comparables sans vérifier ce qui a bougé côté serveur.

Les autres règles d'appel :

- Délai d'expiration explicite sur le client. Les défauts des SDK sont
  souvent de plusieurs minutes : ce n'est pas une valeur qu'on subit sans le
  savoir.
- Nombre de réessais **borné par une constante**, et jamais de boucle de
  réessai maison par-dessus celle du SDK.
- Chaque appel renvoie ses jetons d'entrée et de sortie **séparément**, lus
  dans `usage`. C'est la mesure de charge du LLM partagé, et c'est ce qui
  permet de recalculer un coût si un projet passe un jour sur une API
  facturée, sans tout relancer.
- **La réflexion d'un modèle n'est pas sa réponse.** Quand le serveur la
  renvoie à part, le client l'écarte : elle ne repart pas dans l'historique,
  n'apparaît dans aucun log ni aucune trace. Son niveau est un réglage
  explicite, consigné dans le fichier de run.
- Avec une API facturée, et seulement dans ce cas, les tarifs sont des
  constantes **datées en commentaire**, dans un seul module. Un tarif sans
  date est un tarif faux.
- Un seul paramètre change entre deux runs d'évaluation. Deux changements
  simultanés produisent un résultat ininterprétable.

---

## 6. Boucles d'agent

Toute boucle qui appelle un modèle porte un plafond d'itérations en dur, en
majuscules, et **testé** :

```python
MAX_ITERATIONS = 12
```

Atteindre le plafond n'est pas une erreur silencieuse : la boucle renvoie une
trace qui dit qu'elle s'est arrêtée là, et pourquoi. Une boucle qui s'arrête
sans le dire produit une réponse tronquée qu'on prend pour une réponse.

Une boucle sans plafond occupe indéfiniment un LLM partagé entre plusieurs
projets — et, sur une API facturée, devient un incident financier. C'est
écrit dans le `SECURITY.md` de l'organisation, ceci en est la traduction en
code.

---

## 7. Contenu externe

Tout ce que le système récupère — passage de document, résultat d'outil, page
web, fichier déposé — est de la **donnée**, jamais une instruction.

En pratique, dans le code :

- Le contenu récupéré est inséré dans le prompt dans une zone délimitée et
  annoncée comme telle, séparée des consignes.
- Aucune action irréversible ne se déclenche à partir d'un contenu récupéré
  sans validation humaine explicite.
- Le jeu d'évaluation contient au moins un cas de contenu empoisonné. Ce cas
  est un test, pas une curiosité : il doit rester vert.

---

## 8. Erreurs

- Pas de `except:` nu. Pas d'`except Exception` qui avale et continue.
- Des exceptions métier nommées, définies dans un module `errors.py`, suffixées
  `Error` (`EmptyContextError`, `IterationLimitError`).
- Les messages d'exception sont en français et disent quoi faire.
- **Un message d'erreur ne contient jamais le contenu d'un prompt, d'un
  document récupéré ou d'une réponse de modèle.** Il contient un identifiant,
  une longueur, un compteur. C'est la même règle que pour les logs, et elle est
  plus souvent violée dans les exceptions que dans les logs.

---

## 9. Journalisation

`logging` de la bibliothèque standard. **Aucun `print` dans `src/`** — la règle
`T20` de `ruff` le vérifie. Les `print` sont autorisés dans `scripts/`, dont
c'est le rôle.

Ce qu'on logue : des identifiants, des compteurs, des durées, des jetons, des
noms de modèle.

Ce qu'on ne logue jamais : un prompt, un extrait de document, une réponse de
modèle, la réflexion d'un modèle, un contenu d'outil. Loguer un prompt de RAG
revient à loguer le contenu métier des documents récupérés, intégralement ; la
réflexion reprend tout ce que le modèle a lu. Les fichiers de trace ne sont
jamais commités.

Le niveau se règle par variable d'environnement, il n'est pas figé dans le
code.

---

## 10. Fichiers

`pathlib` partout, jamais de concaténation de chaînes pour construire un
chemin.

**`encoding="utf-8"` explicite à chaque ouverture de fichier texte.** Sans lui,
Python 3.13 utilise l'encodage local, qui n'est pas UTF-8 sur les postes
Windows de l'équipe. C'est la source de bug la plus fréquente et la plus bête :
le code marche chez son auteur, échoue en CI, et l'erreur ne parle pas
d'encodage.

Pour le JSON écrit dans le dépôt : `ensure_ascii=False` et une indentation, ou
le diff est illisible en revue.

---

## 11. Tests

`tests/` reflète `src/`. Un comportement par test, un nom qui dit lequel.

- **Aucun appel réseau.** La CI le garantit en fournissant une adresse de
  LLM injoignable et une clé factice ; le code doit le rendre possible, en
  acceptant un client injecté plutôt qu'en le construisant lui-même.
- Le faux client vit dans `tests/conftest.py` et renvoie des réponses fixes,
  au format de l'API réelle.
- Ce qui se teste en priorité sur un projet IA : le découpage, le comptage des
  jetons, le plafond d'itérations, le comportement de refus, l'assemblage du
  prompt, et la mise à l'écart de la réflexion du modèle. Pas la qualité de la réponse du modèle — ça, c'est le jeu
  d'évaluation, et ce n'est pas un test unitaire.
- Un test qui échoue une fois sur trois est pire que pas de test : on finit par
  ignorer la CI rouge.

---

## 12. Ce qu'on n'écrit pas

- Une classe quand une fonction suffit. Une classe sans état est une fonction
  déguisée.
- Un état global mutable. Les constantes en majuscules sont immuables ; le
  reste se passe en argument.
- Une couche d'abstraction pour un seul usage. On l'écrit quand le deuxième
  arrive, pas en prévision.
- Une dépendance pour vingt lignes. On écrit les vingt lignes.
- Un `TODO` sans nom ni date. Il n'y en aura pas d'autre.
- Un notebook dans `src/`. Un notebook est un brouillon, pas un livrable.

---

## 13. Avant de commiter

```bash
uv run ruff format .
uv run ruff check .
uv run pytest
git diff --staged
```

La dernière ligne n'est pas décorative : c'est elle qui attrape la clé, la
donnée et le nom de client. Trois secondes.
