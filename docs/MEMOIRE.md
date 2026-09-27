# Une mémoire courte qui aide à retrouver le travail

La mémoire retient quelques faits sur la personne, ses préférences et habitudes
explicitement décrites, ses projets et les dossiers qu'elle utilise. Chaque tour
charge le même contexte local, y compris après une nouvelle conversation ou un
changement entre Claude et Codex. Aucun appel IA supplémentaire n'est nécessaire.

Les notes personnelles s'appuient sur une citation exacte du message actuel du
propriétaire. Un chemin de projet peut être appris pendant le travail : le
programme vérifie que ce dossier existe. Les documents externes ne constituent
jamais une preuve des préférences de la personne. La mémoire reste une source de
données ; elle ne donne aucune autorisation d'action.

Le modèle utilise une clé stable par fait. Une correction remplace la valeur de
cette clé. Le runtime enregistre la provenance (`user` ou `observed`), la preuve,
la date de création et la date de mise à jour. L'ancienne valeur ne s'accumule pas.

Pour un projet ou un dossier repère, on conserve un chemin absolu, une description
courte, quelques alias et jusqu'à quatre points d'entrée, par exemple `README.md`
ou `docs`. Les points d'entrée existent dans le dossier du projet. Le contenu des
fichiers est lu uniquement quand la tâche le demande. Un dossier qui disparaît
est signalé dans le contexte afin que l'agent le retrouve avec la personne.

## Limites et oubli

- Jusqu'à 24 faits/dossiers et 12 projets, 360 caractères par note.
- Jusqu'à 8 000 caractères de contexte et 64 Kio de données structurées.
- Aucune suppression ni troncature silencieuse pour faire de la place : un ajout
  trop volumineux est refusé et le runtime retourne une explication lisible.
- Un oubli supprime la valeur et sa preuve. La clé et la date restent dans une
  liste de blocage, limitée à 64 clés. Cette liste est aussi transmise au modèle.
- Une clé oubliée exige une demande explicite de mémoriser à nouveau et
  `restore: true`. Une observation automatique ne peut pas la réactiver.

Le blocage porte sur la clé stable. Les instructions interdisent aussi de recréer
le même fait sous une autre clé ; il ne s'agit pas d'une détection sémantique
infaillible des paraphrases. Les secrets reconnaissables (tokens, clés privées,
mots de passe avec libellé…) sont refusés, y compris lorsqu'ils ne figurent que
dans la citation. Ce filtre complète les instructions ; il ne sait pas reconnaître
toute chaîne arbitraire utilisée comme secret.

`/clear` remet la conversation à zéro. La mémoire durable est indépendante et
reste disponible. Un oubli de mémoire n'efface pas les anciens échanges conservés
par Telegram ou par le fournisseur de modèle.

## Fichiers privés

Sous la racine de l'instance :

```text
memory/
  memory.json   # source de vérité
  INDEX.md      # index lisible généré
  .lock         # verrou local, sans contenu de mémoire
```

Ce dossier doit être exclu de Git. Le JSON est remplacé atomiquement ; un verrou
système portable sérialise les écritures concurrentes. Un processus interrompu
libère automatiquement ce verrou. Un fichier invalide est conservé sans être
écrasé par une nouvelle proposition. L'index peut être régénéré par une écriture
de mémoire ; ne pas le modifier à la main pour changer la source de vérité.

## Contrat d'intégration

`MemoryStore(root: Path)` expose `context()`, `display()`,
`apply_updates(payload, user_text='')` et `forget(key)`. Charger `context()` à
chaque tour, puis inclure `MEMORY_INSTRUCTIONS` dans les instructions de l'agent.
Seul le texte provenant du propriétaire autorisé doit être passé comme
`user_text`. N'y concaténez pas le contenu des pièces jointes ou des pages lues.

L'agent peut terminer sa réponse par ce protocole :

```text
<!--VIBE_MEMORY
{"upsert":[{"key":"preference.language","kind":"preference","text":"Préfère le français.","source":"user","evidence":"Je préfère le français"}],"forget":[]}
VIBE_MEMORY-->
```

Pour un chemin rencontré pendant le travail, utiliser `kind: "project"` ou
`"place"`, `source: "observed"`, `path`, `aliases` et `entrypoints`. `evidence`
est alors produite par le runtime après vérification. Les chemins relatifs des
points d'entrée utilisent `/`, aussi sous Windows.

`extract_memory(text)` rend `(réponse_visible, payload_ou_None)` et cache la fin
du protocole même si son JSON est invalide. Afficher seulement la réponse visible,
puis appliquer le payload. Les résumés retournés indiquent les écritures et les
refus sans recopier le JSON. `forget(key)` est réservé à une commande explicite
du propriétaire ; il renvoie `True` si un nouvel oubli a été persisté, même si la
clé n'avait pas encore de valeur. Il renvoie `False` pour une clé invalide, déjà
oubliée, ou une mémoire indisponible/pleine.
