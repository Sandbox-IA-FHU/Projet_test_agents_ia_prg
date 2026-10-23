---
description: Ajouter un outil au registre, avec la question de sa sensibilité
---

Ajoute un outil à l'agent. La surface d'outils est la vraie limite de ce que
l'agent peut faire : on ne se protège pas d'une injection de prompt en filtrant
du texte, on s'en protège en ne donnant pas le droit de faire la chose
dangereuse.

Outil demandé : $ARGUMENTS

## Avant d'écrire une ligne, réponds à trois questions

**1. Cet outil est-il sensible ?** Il l'est s'il est irréversible, coûteux, ou
visible à l'extérieur : envoi, publication, écriture, suppression, paiement,
appel à un système tiers. Dans le doute, **oui**. Le coût d'une validation
inutile est une question posée à un humain ; le coût d'une action irréversible
non validée est un incident.

**2. Que se passe-t-il si un contenu récupéré déclenche cet outil ?** C'est la
bonne façon de raisonner : pas « le prompt tiendra-t-il » mais « que se
passe-t-il s'il ne tient pas ». Si la réponse est inacceptable, l'outil ne doit
pas exister sous cette forme — restreins son périmètre plutôt que d'espérer que
le prompt suffira.

**3. Un appel de fonction moins puissant suffirait-il ?** Un outil qui lit un
identifiant précis vaut mieux qu'un outil qui exécute une requête libre.

Si l'une des trois réponses coince, dis-le et arrête-toi là.

## Ce que tu écris ensuite

1. Le gestionnaire dans `src/agent/toolbox.py`. Il prend un `dict` d'arguments,
   rend une chaîne, et lève `ToolError` en cas d'échec — jamais une autre
   exception, qui tuerait la boucle au lieu de laisser l'agent se rattraper.
2. Le `ToolSpec`, avec `isSensitive` correctement posé. La description dit
   **quand** utiliser l'outil, pas seulement ce qu'il fait ; pour un outil
   sensible, elle dit aussi que l'action est irréversible et soumise à
   validation, pour que le modèle en tienne compte avant de la demander.
3. Un schéma d'entrée strict : types explicites, `required` renseigné,
   description de chaque champ.
4. **Aucun `eval`, aucun `exec`, aucun appel shell** construit à partir des
   arguments. Si l'outil doit interpréter quelque chose, il l'analyse — voir
   `evaluateExpression` pour le modèle à suivre.

## Les tests, dans le même passage

- Le cas nominal.
- Un cas d'entrée invalide, qui doit lever `ToolError`.
- Si l'outil est sensible : qu'il apparaît bien dans
  `registry.sensitiveNames()`, et un test de boucle qui prouve qu'il ne
  s'exécute pas sous `DenyAll`.
- Si l'outil interprète une entrée : des cas hostiles, pas seulement des cas
  malformés.

## Et le jeu d'évaluation

Deux cas au minimum : un où l'outil **doit** être appelé, un où il ne doit
**pas** l'être. Sans le second, on ne mesure que la capacité, jamais la
retenue.

Rappelle enfin que l'ajout d'un outil change le prompt système envoyé à chaque
tour : les runs passés ne sont plus strictement comparables, et il faut un
nouveau run de référence.
