# Installer Vibe Claw Light

## Compte et ordinateur

Choisis Codex ou Claude Code selon le compte auquel tu as accès. Un seul moteur suffit ; l'installateur prépare uniquement celui que tu choisis. Vérifie que ton offre autorise le CLI, pas seulement l'application de chat : [accès Codex](https://learn.chatgpt.com/docs/pricing), [accès Claude Code](https://code.claude.com/docs/en/setup).

Le setup utilise la connexion native au compte. Il ne crée pas de compte API et ne bascule pas automatiquement vers une API payante. Les limites du compte continuent de s'appliquer. Une connexion à l'application desktop ne garantit pas que son CLI soit déjà connecté.

Windows 11 est la cible principale ; les scripts fonctionnent aussi sur macOS et Linux. Le parcours Windows par archive ne demande pas d'installer Git, Node ou WSL. Python 3.11 est préparé avec `uv`, puis le CLI choisi est installé si nécessaire. La configuration native du sandbox Codex peut demander une validation administrateur/UAC. [Codex sur Windows](https://learn.chatgpt.com/docs/windows/windows-sandbox), [Claude Code](https://code.claude.com/docs/en/setup), [Python avec uv](https://docs.astral.sh/uv/guides/install-python/).

Les parcours réellement vérifiés et leurs limites figurent dans [VALIDATION.md](VALIDATION.md). Répète l'installation avec ton propre bot avant une présentation.

## Récupérer la version

Télécharge la [release `v0.3.0`](https://github.com/tiasslevo/vibe-claw-light/releases/tag/v0.3.0) et extrais toute l'archive dans un dossier durable, par exemple `Documents\vibe-claw-light`. Ne lance pas l'installation à l'intérieur du ZIP.

Avec Git :

```sh
git clone --branch v0.3.0 --depth 1 https://github.com/tiasslevo/vibe-claw-light.git
cd vibe-claw-light
```

Le code de l'assistant et ses nouveaux documents ont des emplacements distincts. Par défaut, les documents seront rangés dans `Documents/MonAssistant`. N'importe pas la configuration ou l'identité d'un autre assistant.

## Windows

Double-clique sur `install.cmd` et choisis `codex` ou `claude`. Depuis PowerShell, le choix peut aussi être fourni directement :

```powershell
.\install.cmd -Provider codex
# Ou :
.\install.cmd -Provider claude
```

L'installateur prépare les dépendances et ouvre une page locale. Elle suit quatre étapes : connexion au moteur, réglages de l'assistant, association Telegram et démarrage. Après l'association, elle vérifie les prérequis, teste le modèle puis démarre le service en arrière-plan. Attends la confirmation **Telegram associé, modèle testé, service démarré** avant de considérer l'installation terminée.

La fenêtre affiche les erreurs et reste ouverte. Si le bot tourne déjà, arrête-le avec `stop.cmd` avant de reprendre la configuration. Relancer le setup conserve la mémoire et propose les valeurs existantes.

La page est servie sur `127.0.0.1`, donc sur ton PC. Python demande à ton navigateur de l'ouvrir. Si cela échoue, ouvre l'adresse indiquée par le programme. Cette adresse contient un secret de session : ne la partage pas.

Le lanceur utilise `-ExecutionPolicy Bypass` pour son processus PowerShell uniquement, sans modifier durablement la politique de la machine. Une restriction d'entreprise doit être traitée avec son support.

## macOS et Linux

Dans un terminal ouvert dans le dossier extrait :

```sh
bash scripts/install.sh codex
# Ou :
bash scripts/install.sh claude
```

Il faut Bash, `curl` et un système compatible avec le CLI choisi. Le script utilise les installateurs officiels et ne demande pas de `sudo`.

## Connexion au moteur

Si le CLI est déjà connecté, le setup passe directement à la configuration. Sinon, le bouton **Se connecter avec Codex** ou **Se connecter avec Claude Code** lance la commande native :

```text
codex login
```

ou :

```text
claude auth login
```

La connexion se déroule dans le terminal de l'installation ou dans une nouvelle fenêtre locale. Le CLI peut ouvrir le site officiel et demander de recopier un code : colle ce code dans ce terminal. La page de configuration du starter ne reçoit aucun mot de passe ni code OAuth.

Si l'installation a été lancée depuis un agent non interactif, le setup cherche à ouvrir un vrai terminal sur le PC. S'il ne peut pas, il affiche la commande à lancer manuellement. Termine la connexion : la page en revérifie automatiquement l'état pendant une durée limitée. Le bouton de vérification reste disponible. N'envoie pas les codes dans la conversation avec ton agent.

Tu peux aussi effectuer cette connexion avant de lancer l'installation. L'authentification est conservée par le CLI officiel ; le starter en vérifie le statut.

## Créer et associer le bot Telegram

1. Ouvre le compte vérifié [BotFather](https://t.me/BotFather) dans Telegram.
2. Envoie `/newbot`, choisis un nom et un identifiant qui finit par `bot`.
3. Colle le token dans le champ masqué de la page locale de configuration. Ne le colle pas dans un prompt, un groupe ou une capture d'écran.
4. Ouvre le lien d'association proposé et appuie sur **Démarrer** dans Telegram.

Le lien contient un secret temporaire et associe ton compte sans te demander de rechercher son identifiant numérique. Le bot accepte ensuite ce compte uniquement, en discussion privée. Ne lance pas deux programmes avec le même token. Si un token a été partagé, révoque-le dans BotFather et relance le setup avec le nouveau.

## Attendre que l'assistant soit prêt

L'association Telegram enregistre les réglages. La page reste ouverte pour afficher les vérifications et le démarrage : **Telegram associé**, **Connexion Telegram**, **Modèle testé**, puis **Service démarré**.

Un problème réseau, un token refusé ou une erreur du moteur laisse la page ouverte avec une explication. Utilise **Réessayer l'étape restante** après avoir corrigé le problème, ou retourne aux réglages si nécessaire. Le diagnostic réessaie brièvement les erreurs réseau récupérables, sans traiter automatiquement toute erreur comme un mauvais token.

Le test modèle crée un fichier temporaire distinct des documents de l'utilisateur. Si un prérequis essentiel échoue, ce test est différé et ne consomme pas de quota. Un succès est réutilisé pendant **quinze minutes**, tant que la configuration contrôlée reste identique. La connexion et les prérequis sont tout de même revérifiés lors d'une reprise.

Quand la page annonce que l'assistant est prêt, tu peux terminer l'installation et fermer cet onglet. Ouvre ensuite le bot et demande :

> Crée bienvenue.txt dans mon dossier de rangement avec une phrase de présentation, puis envoie-moi ce fichier.

Ce fichier est créé à ta demande, pas par le diagnostic. Vérifie le document et sa réception dans Telegram.

Un onglet périmé ne permet pas d'appliquer un ancien formulaire. Utilise la nouvelle page ouverte par le setup. Les champs de token restent vides lors d'un retour au formulaire ; le token existant peut rester conservé dans la configuration locale.

## Dossier de rangement et accès

Le dossier proposé pour les nouveaux travaux est **Documents/MonAssistant**, dans ton dossier utilisateur. Tu peux en choisir un autre. Un projet existant garde sa propre organisation : donne son chemin à l'assistant, qui peut retenir où commencer.

Le formulaire distingue deux modes :

| Mode | Ce qu'il permet |
| --- | --- |
| **Assistant personnel**, par défaut pour une nouvelle installation | Le dossier utilisateur et ses projets, le dossier du starter et le dossier de rangement ; commandes et réseau actifs avec les droits de ton compte |
| **Limité aux dossiers choisis** | Le dossier du starter et le dossier de rangement ; commandes Claude seulement si activées, réseau Codex désactivé |

Codex conserve son sandbox `workspace-write`. Une action qui réclame une autorisation interactive supplémentaire échoue et doit être examinée dans une session locale. Claude utilise des permissions d'outils ; celles-ci ne constituent pas une sandbox Windows du système d'exploitation.

Pour un projet sur un autre disque ou hors du dossier utilisateur, `EXTRA_DIRS` accepte une liste JSON de chemins absolus, 12 au maximum. Exemple dans `config.env` :

```text
EXTRA_DIRS='["D:/Projets", "E:/Documents"]'
```

Sous macOS/Linux, utilise des chemins tels que `/mnt/projets`. Le champ `WORKSPACE` reste le lieu où ranger les nouveaux travaux ; il n'est pas nécessaire de le déplacer pour ajouter un projet accessible. Après une modification des accès, utilise `/reload` ; le programme ouvre de nouvelles sessions avec ces réglages.

Les fichiers envoyés par le bot doivent appartenir aux dossiers autorisés. L'envoi de fichiers d'authentification connus et des données internes du starter est bloqué. Ce filtre de chemins ne remplace pas la vérification du contenu d'un document destiné à être partagé.

## Personnalité et mémoire

`identity/SOUL.md` est facultatif et peut préciser le ton ou le rôle de l'assistant. Seuls ses 2 000 premiers caractères sont chargés. Le setup crée une courte base si le fichier n'existe pas ; il ne génère pas une personnalité détaillée. Une modification de ce fichier est prise en compte au prochain message sans recommencer la conversation.

Le profil, les préférences et les repères de projets sont enregistrés dans la mémoire commune aux deux moteurs. Il n'y a pas de `USER.md` supplémentaire. Utilise `/memory` pour la consulter et `/forget CLE` pour retirer une entrée. Les règles de consolidation et les limites sont décrites dans [MEMOIRE.md](MEMOIRE.md).

## Démarrer, arrêter, diagnostiquer

| Action | Windows | macOS/Linux |
| --- | --- | --- |
| Démarrer en arrière-plan | Double-clic `start.cmd` | `bash start.sh` |
| Arrêter le service | Double-clic `stop.cmd` | `bash start.sh stop` |
| Voir son état | `.venv\Scripts\python.exe run.py status` | `bash start.sh status` |
| Diagnostic | `.venv\Scripts\python.exe run.py doctor` | `bash start.sh doctor` |
| Petit test réel du modèle | `.venv\Scripts\python.exe run.py doctor --live` | `bash start.sh doctor --live` |
| Exécution au premier plan | `.venv\Scripts\python.exe run.py run` | `bash start.sh run` |

`doctor` vérifie les prérequis sans appeler le modèle. `doctor --live` ajoute un test réel et utilise le quota si aucun succès compatible n'est disponible dans le cache de quinze minutes. Ces commandes ne démarrent pas le service ; le setup gère le diagnostic et le démarrage dans sa page. Pour observer un problème avec `run`, arrête d'abord le service existant, puis quitte avec Ctrl+C.

Pour reprendre le setup :

```powershell
# Windows
.venv\Scripts\python.exe run.py setup --provider codex
```

```sh
# macOS/Linux
bash start.sh setup --provider claude
```

Pour préparer les dépendances uniquement : `install.cmd -Provider codex -SkipSetup` ou `bash scripts/install.sh codex --skip-setup`. La variable de processus `VCL_NO_PAUSE=1` supprime la pause finale des lanceurs Windows lorsqu'un agent les pilote.

## Changer de moteur

Envoie `/switch codex` ou `/switch claude`. Si le moteur est installé et connecté, le bot bascule puis confirme le moteur utilisé. Sinon, il explique la connexion à terminer ou fournit une demande à copier dans ton assistant local sur le PC.

Le [guide des moteurs](MOTEURS.md) prépare seulement le moteur manquant, avec `SkipSetup` lorsque nécessaire. Il conserve le bot, la mémoire et les sessions existantes sans refaire toute l'installation. Les deux moteurs gardent chacun leur conversation ; leur mémoire durable est commune.

## Si quelque chose bloque

| Symptôme | Première action |
| --- | --- |
| CLI introuvable | Relance l'installateur ; pour un emplacement particulier, utilise `CODEX_BIN` ou `CLAUDE_BIN` dans la configuration locale |
| Aucun terminal de connexion ne s'ouvre | Lance la commande affichée dans un terminal du PC, puis revérifie depuis la page |
| Compte non connecté ou quota atteint | Vérifie le compte dans le CLI officiel, puis relance le diagnostic |
| Le bot ne répond pas | Vérifie `status`, la connexion du PC et son absence de mise en veille |
| Telegram affiche « Conflict » | Arrête l'autre programme utilisant ce token |
| Projet hors des accès | Vérifie `/info` et ajoute si nécessaire son dossier dans `EXTRA_DIRS` |
| Commande Claude refusée en mode limité | Vérifie le choix `ALLOW_SHELL` dans la configuration |
| Sandbox Codex non initialisé | Termine sa configuration depuis Codex local sur Windows ; une validation administrateur/UAC peut être nécessaire |
| `/reload` échoue après un changement | Arrête le service, corrige le code avec l'agent local, puis relance-le |

Ne partage jamais `config.env`. Avant de joindre un diagnostic, retire tokens, identifiants, textes privés et chemins personnels.

## Mettre à jour une installation existante

Arrête le service et sauvegarde ta configuration, ta mémoire et tes documents dans un endroit privé. Mets ensuite à jour le code et les dépendances, en vérifiant les différences si ton agent a modifié ses propres fichiers.

Une configuration v0.1 sans `ACCESS_MODE` conserve le mode `workspace`, son dossier existant et son réglage de commandes Claude. La mise à jour ne donne pas de nouveaux accès. Pour choisir le mode personnel, reprends le setup et sélectionne-le explicitement.

La mémoire existante est conservée. Le starter désactive la mémoire automatique des CLI uniquement pour ses appels ; il ne modifie pas leurs préférences globales. Si une mise à jour change les consignes communes de l'agent ou son protocole de mémoire, le rechargement ouvre de nouvelles conversations avec ces règles, tout en conservant les souvenirs. Il n'y a pas de mise à jour distante automatique ni de lancement à l'ouverture de session du PC.
