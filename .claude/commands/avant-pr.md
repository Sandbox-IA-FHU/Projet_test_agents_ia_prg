---
description: Passer la checklist de revue sur son propre diff, avant de la demander
---

Relis le diff comme un relecteur exigeant le ferait. La relecture de son propre
diff attrape la moitié des remarques de revue : cinq minutes qui en font gagner
trente à quelqu'un d'autre.

## 1. Les commandes

Lance et rends le résultat brut, sans le résumer :

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
git status --short
git diff
```

## 2. Le contrôle données et secrets

Sur le diff complet, cherche et signale :

- une clé d'API, même partielle, même expirée, même en commentaire ;
- un extrait de donnée réelle, un chemin réseau, une adresse personnelle ;
- un nom de client — on écrit « le client », « un groupe de distribution » ;
- un fichier de données hors de `evaluations/jeux/` ;
- un notebook contenant des sorties de cellules ;
- un fichier de plus de 5 Mo.

Ces cinq derniers points font échouer le check `donnees` de la CI. Le premier
ne fait échouer que la vie réelle.

## 3. Le contrôle méthode

- L'adresse et le nom du modèle viennent-ils de la configuration
  (`LLM_BASE_URL`, `LLM_MODEL`), jamais en dur ? Aucune adresse de serveur
  n'apparaît-elle dans le diff, même en exemple ?
- La réflexion du modèle reste-t-elle hors de l'historique, des logs et des
  traces ?
- Si `compose.yaml` a changé : `docker compose config -q` passe-t-il, le
  service reste-t-il préfixé par le projet, sans GPU ni port ?
- Tout chiffre annoncé porte-t-il sa date et son nombre de cas ?
- Si le prompt a changé : les deux runs existent-ils, avant et après ?
- Si une conclusion est tirée : l'écart est-il assez grand pour être
  interprétable sur ce nombre de cas ?
- Le plafond d'itérations est-il toujours en dur, et son atteinte toujours
  visible dans la trace ?
- Un outil ajouté est-il correctement marqué `isSensitive` ? Un outil sensible
  peut-il encore être atteint sans passer par la validation ?
- Un `eval`, un `exec` ou un appel shell construit à partir d'arguments
  d'outil est-il apparu quelque part ?
- Une dépendance a-t-elle été ajoutée ? Si oui, la raison est-elle écrite ?

## 4. Le contrôle style

Contre [CONVENTIONS-PYTHON.md](../../CONVENTIONS-PYTHON.md) : identifiants en
anglais, `camelCase` pour variables et fonctions, `MAJUSCULES` pour les
constantes, `PascalCase` pour les classes, docstrings en français,
`encoding="utf-8"` sur chaque ouverture de fichier, aucun `print` dans `src/`.

## 5. Ce que tu rends

- La liste de ce qui bloque, et séparément ce qui est un `détail :`. Sans cette
  distinction, l'auteur ne sait pas ce qu'il doit traiter et traite tout.
- Un titre de PR qui décrit l'effet, pas le contenu du diff.
- Un corps de PR pré-rempli sur le gabarit de l'organisation : ce qui change,
  d'où vient la demande, les choix faits et pourquoi, ce qui a été
  volontairement laissé de côté.
- Un rappel de mettre à jour la date de l'en-tête du README si le dépôt a bougé.
- Un rappel du circuit : le travail se pousse sur `staging` ; la seule PR
  est `staging` → `main`, approuvée et fusionnée par Florian, en merge
  commit.
