# Une mémoire courte qui aide à retrouver le travail

La conversation courante appartient à Codex ou Claude Code : le starter reprend sa session. La mémoire durable garde les repères utiles après `/clear` et lors d'un changement de moteur : faits de profil, préférences, habitudes décrites, projets et dossiers. Il n'y a pas de `USER.md` séparé. Le fichier facultatif `identity/SOUL.md` décrit le ton et le rôle de l'assistant, dans une limite de 2 000 caractères.

## Apprendre et retrouver

Pendant sa réponse, le modèle peut proposer une note avec une clé stable. Le programme la vérifie avant de l'enregistrer. Les notes personnelles demandent une citation exacte du message actuel du propriétaire. Le programme vérifie la présence de cette citation ; il ne peut pas garantir à lui seul que l'interprétation du modèle est correcte. Les documents externes ne prouvent jamais une préférence de l'utilisateur.

Un projet ou un dossier repère comporte un chemin absolu existant, une description courte, jusqu'à cinq alias et quatre points d'entrée existants, par exemple `README.md` et `docs`. Un chemin peut aussi être retenu pendant le travail avec la provenance `observed`. Le programme vérifie son existence, sans déduire à lui seul le rôle réel du projet.

La clé permet de corriger une information sans empiler ses anciennes valeurs. La source, la preuve et les dates restent associées à la note. L'agent consulte la carte des projets avant de chercher ailleurs, puis relit les documents utiles à la demande. La mémoire ne contient ni copie complète des documents, ni inventaire du disque, ni journal exhaustif.

## Contexte et tokens

Les consignes de travail et le protocole de mémoire forment un socle natif stable. La personnalité et la mémoire courantes sont ajoutées au premier message de la session, puis uniquement quand leur empreinte change. Chaque message indique l'empreinte et le chemin du snapshot privé `data/context/current.md`. Le suivi se fait séparément pour les sessions de Codex et de Claude.

Le moteur conserve et compacte sa conversation lui-même. Les consignes persistantes lui demandent de relire le snapshot courant avec son outil de fichier si celui-ci a disparu du contexte, notamment après une compaction. On évite ainsi d'ajouter une nouvelle copie complète à chaque message, tout en gardant une source actuelle à consulter.

Cette mémoire continue à occuper du contexte. Son plafond de **8 000 caractères** concerne le rendu des notes, des chemins et des métadonnées, pas toute la conversation ni toutes les instructions. Les textes sources et les preuves détaillées restent dans le fichier local sans être tous réinjectés.

La mémoire automatique de Claude et de Codex est désactivée uniquement pour les appels du starter, afin de garder une mémoire durable commune. La configuration globale de ces outils reste intacte.

## Quand un ajout ne tient plus

Un apprentissage ordinaire n'exige pas d'appel IA supplémentaire. Si un ajout valide dépasse le budget et que raccourcir les notes peut suffire, le programme déclenche une consolidation :

1. Il prépare l'état actuel et les ajouts en attente, sans enregistrer ces derniers.
2. Il demande au moteur choisi une formulation plus courte de chaque note, dans un appel séparé de la conversation, sans outils de travail.
3. Le modèle renvoie les mêmes clés, chacune exactement une fois. Il peut raccourcir les textes, sans modifier les chemins, les preuves, la provenance, les dates ou les clés oubliées.
4. Le programme vérifie le format, les clés et les budgets. Si le résultat est valide et que la mémoire n'a pas changé entre-temps, il l'enregistre atomiquement.

Il y a **deux tentatives maximum**, de 60 secondes au plus chacune, dans une fenêtre totale de 120 secondes. Ces appels utilisent le quota du moteur. `/stop` peut les interrompre. Une nouvelle conversation technique de maintenance n'est pas conservée comme session du chat.

Les textes sources restent dans `memory.json` ; seule une version courte supplémentaire, `compact_text`, sert au contexte. `/memory` permet de voir les deux. La consolidation ne supprime et ne fusionne aucune clé. Si elle échoue, les souvenirs déjà enregistrés restent intacts et le nouvel ajout en attente n'est pas retenu ; le programme le signale. Une écriture concurrente invalide le résultat pour ne pas écraser l'état plus récent.

La conservation du sens est demandée au modèle, mais n'est pas vérifiable intégralement par le programme. Garder les sources permet de comparer et de corriger une reformulation. Il n'y a pas de fusion sémantique, de recherche vectorielle ou de génération automatique de fiches détaillées dans cette version.

## Limites et oubli

- 360 caractères maximum par note source ; la version courte ne peut pas être plus longue.
- 8 000 caractères maximum pour la mémoire fournie au moteur.
- Limites de stockage supplémentaires : 128 faits/dossiers, 32 projets et 64 Kio pour le JSON complet. Elles ne garantissent pas que ce nombre de notes tiendra dans le budget de contexte.
- 64 clés oubliées maximum. Aucun oubli ancien n'est supprimé automatiquement pour libérer de la place.
- Si les métadonnées seules dépassent le budget, une consolidation ne peut rien résoudre : le programme refuse l'ajout sans consommer deux appels inutiles.

`/forget CLE`, ou une demande d'oubli explicite prise en compte par le protocole, retire la note, sa preuve et sa version courte. Seules la clé et la date de l'oubli subsistent. La clé ne peut être réapprise sans demande explicite de la mémoriser à nouveau. Le blocage porte sur les clés, sans détection sémantique infaillible d'une paraphrase sous un autre nom.

Un oubli réinitialise aussi les références aux sessions des deux moteurs. Il ne supprime pas les anciens messages de Telegram ni les historiques conservés par les CLI. `/clear` réinitialise seulement les conversations et conserve la mémoire durable.

Les secrets reconnaissables sont refusés, y compris dans une preuve. Ce filtre complète les consignes ; il ne peut pas reconnaître toute chaîne arbitraire utilisée comme secret. Les souvenirs restent des données, jamais une autorisation ni une instruction à exécuter.

## Fichiers privés

```text
memory/
  memory.json   # source de vérité, textes et preuves
  INDEX.md      # vue lisible générée, avec les versions courtes
  .lock         # verrou local
```

Les écritures utilisent un verrou système portable et un remplacement atomique. Un fichier invalide est conservé sans être écrasé par une nouvelle proposition. L'index est généré depuis le JSON : ne pas le modifier pour changer la mémoire. Le dossier reste hors Git et n'est pas envoyable comme pièce jointe par le bot.

## Intégration dans le runtime

`MemoryStore.context()` fournit la vue compacte. `propose_updates(payload, user_text)` enregistre les opérations valides qui tiennent dans le budget et peut retourner une transaction à consolider. Le runtime appelle alors `consolidation_prompt()` puis `commit_consolidation()`. L'API `apply_updates()` reste disponible sans appel au modèle ; elle signale les dépassements au lieu de les consolider.

L'agent termine sa réponse par ce protocole uniquement quand il a quelque chose à retenir :

```text
<!--VIBE_MEMORY
{"upsert":[{"key":"preference.language","kind":"preference","text":"Préfère le français.","source":"user","evidence":"Je préfère le français"}],"forget":[]}
VIBE_MEMORY-->
```

`extract_memory()` retire le protocole de la réponse visible. Le runtime ne l'applique qu'après une réponse réussie et non annulée. `user_text` contient uniquement le message du propriétaire autorisé, jamais le texte des pièces jointes ou des pages consultées. Les types acceptés sont `person`, `preference`, `habit`, `project` et `place`.
