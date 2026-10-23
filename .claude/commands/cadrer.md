---
description: Cadrer une modification avant de coder — question, mesure, seuil
---

Cadre le travail demandé **avant** d'ouvrir un fichier de code. Coder d'abord
et mesurer ensuite est le réflexe le plus coûteux en IA : on passe des semaines
à améliorer une impression.

Sujet à cadrer : $ARGUMENTS

## Ce que tu produis

Quatre réponses courtes, en français, puis tu t'arrêtes et tu attends la
validation. Tu n'écris aucun code à cette étape.

**1. La question posée.** Une phrase, compréhensible par quelqu'un d'extérieur
au projet. Pas « améliorer le RAG » — « est-ce qu'un découpage plus court
remonte plus souvent le bon passage sur les questions à vocabulaire décalé ? »

**2. Comment on saura que c'est réussi.** La métrique exacte parmi celles que
le dépôt mesure déjà (`tache_reussie` et son découpage `par_type`,
`outil_interdit_appele`, `limite_iterations_atteinte`, `etapes_medianes`,
`jetons_par_tache`, `latence_mediane_s`), le nombre de cas, et le seuil. Si la modification ne touche
aucune de ces métriques, dis-le : c'est peut-être qu'elle ne se mesure pas, et
c'est une information.

**3. Ce qui change, et ce qui ne change pas.** Un seul paramètre à la fois.
Deux modifications simultanées produisent un résultat ininterprétable, et il
faudra tout relancer pour savoir laquelle a agi.

**4. Ce que la mesure ne prouvera pas.** Le point le plus souvent oublié. Un
test sur 25 cas ne prouve rien sur 10 000 ; un jeu inventé ne prouve rien sur
un corpus réel plus bruité.

## Vérifications avant de rendre la main

- La solution la plus simple a-t-elle été envisagée ? Avant un appel modèle
  supplémentaire : une règle, un filtre ou un tri suffiraient-ils ?
- Le run de référence existe-t-il ? Sans point de départ mesuré, il n'y aura
  pas de comparaison possible. S'il n'existe pas, le premier travail est de le
  produire.
- Le seuil est-il écrit **avant** la mesure ? Sinon on ajuste l'exigence au
  résultat obtenu.

Termine par la ligne à ajouter au README si le cadrage change la question ou le
seuil du dépôt.
