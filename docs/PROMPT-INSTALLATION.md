# Le prompt à copier

Ouvre **Codex ou Claude Code en local sur ton ordinateur**, dans un dossier où il peut préparer un projet. Copie le texte ci-dessous. Garde ton navigateur, un terminal local et Telegram disponibles pour les étapes de connexion et d'association.

Le prompt utilise la release exacte `v0.3.0`. Si elle n'est pas disponible, l'assistant doit le signaler au lieu de choisir une autre version.

```text
Installe Vibe Claw Light sur mon ordinateur depuis :
https://github.com/tiasslevo/vibe-claw-light
Version exacte : v0.3.0

Je ne suis pas technique. Explique simplement ce que tu fais et accompagne-moi pour les étapes qui demandent ma présence.

1. Détecte mon système. Demande-moi de choisir Codex ou Claude Code si mon choix n'est pas clair. Un seul moteur est nécessaire : installe seulement celui choisi. Vérifie que mon compte autorise son CLI. Ne suppose pas qu'un compte gratuit suffit et ne bascule jamais automatiquement vers une API payante.

2. Récupère exactement le tag v0.3.0 dans un nouveau dossier local durable nommé vibe-claw-light. Avec Git : git clone --branch v0.3.0 --depth 1 https://github.com/tiasslevo/vibe-claw-light.git. Sinon, télécharge https://github.com/tiasslevo/vibe-claw-light/archive/refs/tags/v0.3.0.zip et extrais-le. Garde le téléchargement temporaire hors de la racine du projet, puis supprime-le après extraction. Inspecte tout dossier existant avant d'y toucher. Si le tag est indisponible, signale-le et arrête cette étape.

3. Lis README.md, AGENTS.md et docs/INSTALLATION.md. Sur Windows, utilise install.cmd -Provider codex ou install.cmd -Provider claude ; VCL_NO_PAUSE=1 peut supprimer la pause finale pour ce processus uniquement. Sur macOS/Linux, utilise bash scripts/install.sh suivi du moteur. Ne réinvente pas le setup. Préserve VIBE_CLAW_ROOT s'il existe : il peut appartenir à une autre instance. N'importe aucune identité, configuration ou donnée d'un autre assistant.

4. Laisse le setup tourner pendant tout le parcours de la page locale, jusqu'à la confirmation de démarrage. Utilise un processus en arrière-plan si ton outil l'exige, suis son résultat et ne ferme pas le serveur pendant ma saisie ou les vérifications. Le setup peut préparer Python et le CLI sans Node ni WSL sur Windows. Si le navigateur ne s'ouvre pas, aide-moi à ouvrir l'adresse locale indiquée. Respecte les restrictions de la machine. Si la configuration native du sandbox Codex demande une validation administrateur/UAC, accompagne-moi depuis Codex local sans désactiver le sandbox.

5. Si le moteur n'est pas connecté, le setup lance codex login ou claude auth login dans un terminal interactif. Laisse-moi terminer le parcours officiel. Si un code doit être recopié, je dois le coller dans ce terminal, jamais dans notre conversation ou dans la page du starter. Si aucune fenêtre ne peut s'ouvrir, guide-moi pour lancer la commande manuellement sur le PC, puis cliquer sur « J'ai terminé la connexion, vérifier ». Ne lis ni n'affiche les fichiers d'authentification.

6. La page propose Documents/MonAssistant pour ranger mes nouveaux travaux. Explique que le mode « Assistant personnel » permet également d'agir dans mes autres projets du dossier utilisateur, avec commandes et réseau ; le mode limité reste disponible. Le dossier de rangement ne définit pas à lui seul tous les accès. Les projets sur un autre disque peuvent être ajoutés ensuite via EXTRA_DIRS. Ne modifie pas les réglages globaux de mémoire des CLI.

7. Guide-moi pour créer un bot dans le compte Telegram vérifié @BotFather. Je saisis le token dans le champ masqué de la page locale. Ne demande jamais ce token dans notre conversation et ne lis ni n'affiche config.env. L'URL de session locale et le lien d'association Telegram sont privés : ne les publie pas. Laisse-moi ouvrir le lien et associer mon compte. Si le service tourne déjà, arrête-le avec sa commande locale avant de reprendre le setup. Conserve la configuration et les souvenirs existants.

8. Après l'association, la même page suit les diagnostics et démarre le service. Attends les confirmations distinctes « Telegram associé », « Modèle testé » et « Service démarré ». Si une étape bloque, accompagne-moi pour la corriger puis utilise la reprise proposée dans la page. Un test modèle réussi est réutilisé pendant quinze minutes si sa configuration reste identique : ne le relance pas inutilement. Ne déclare pas l'assistant prêt après la seule connexion au compte ou la seule association Telegram.

9. Demande-moi d'envoyer depuis Telegram : « Crée bienvenue.txt dans mon dossier de rangement, avec une phrase de présentation, puis envoie-moi ce fichier. » Ce document est créé à ma demande ; le diagnostic a utilisé un autre fichier temporaire. Vérifie sa présence et sa réception dans Telegram sans lire mes autres documents. Indique-moi le dossier, comment démarrer et arrêter le service, puis explique brièvement /help, /clear, /reload, /memory et /forget. Pour ajouter l'autre moteur plus tard, indique /switch et docs/MOTEURS.md. Précise que le PC doit rester allumé et connecté.

Termine par un état factuel : moteur, dossier de rangement, mode d'accès, tests réellement réussis et éventuelle étape bloquée. N'annonce pas de succès Telegram sans l'avoir vérifié. Ne publie rien et ne souscris à aucune offre à ma place.
```

La connexion au fournisseur et la création du bot demandent ta présence. Une exécution de commandes par un agent ne permet pas de remplir ces étapes à ta place.
