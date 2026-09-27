# Installer Vibe Claw Light

## Compte et ordinateur

Choisis le moteur auquel tu as déjà accès. L'installateur installe uniquement celui-ci ; tu pourras en ajouter un autre plus tard.

| Moteur | Accès à vérifier |
| --- | --- |
| Codex CLI | Un compte dont l'offre inclut le CLI et `codex exec`, ou une configuration API payante choisie explicitement. La documentation distingue l'accès desktop Free/Go et les fonctions CLI disponibles à partir de Plus. [Offres officielles](https://learn.chatgpt.com/docs/pricing) |
| Claude Code | Pro, Max, Team, Enterprise ou un compte Console avec facturation. L'offre Claude gratuite n'inclut pas Claude Code. [Installation et accès officiels](https://code.claude.com/docs/en/setup) |

Le setup privilégie la connexion au compte du moteur. Il ne crée pas de compte API et ne bascule pas automatiquement vers une API payante. Les limites d'usage de ton compte continuent de s'appliquer. La connexion à l'application desktop peut être distincte de celle du CLI.

Windows 11 est la cible principale. Pour Codex, un Windows 10 récent et entièrement à jour reste en « best effort ». Le sandbox natif peut demander une configuration approuvée par un administrateur. Sur un PC géré par une entreprise, respecte ses restrictions et fais intervenir le support si nécessaire. [Support Windows officiel](https://learn.chatgpt.com/docs/windows/windows-sandbox)

WSL, Node, Git et Python ne sont pas des prérequis de notre parcours Windows par archive. Python 3.11 est préparé avec `uv`. Les installateurs natifs officiels fournissent Codex ou Claude Code. Git Bash reste optionnel pour Claude Code sur les versions actuelles ; PowerShell peut servir pour les commandes. [Codex CLI](https://learn.chatgpt.com/docs/cli), [Claude Code](https://code.claude.com/docs/en/setup), [Python avec uv](https://docs.astral.sh/uv/guides/install-python/)

## Récupérer la version initiale

Télécharge le code source de la [release `v0.1.0`](https://github.com/BorisJunior/vibe-claw-light/releases/tag/v0.1.0), puis extrais toute l'archive. Utilise un dossier local durable, par exemple `Documents\vibe-claw-light`. Évite de le lancer depuis l'intérieur du ZIP ou depuis un dossier temporaire.

Si tu utilises Git :

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/BorisJunior/vibe-claw-light.git
cd vibe-claw-light
```

Ne copie aucune configuration issue d'un autre assistant. Le projet crée sa propre configuration et sa propre mémoire.

## Windows

Double-clique sur `install.cmd`. Le script demande `codex` ou `claude`, puis prépare l'environnement.

Depuis PowerShell, tu peux aussi choisir le moteur directement :

```powershell
.\install.cmd -Provider codex
# Ou :
.\install.cmd -Provider claude
```

L'installation se déroule ainsi :

1. Détection ou installation de `uv` et du seul moteur choisi.
2. Préparation de Python 3.11 et de l'environnement `.venv` du projet.
3. Ouverture d'une page de configuration sur ton PC, connexion au moteur et choix du nom et du dossier de travail.
4. Saisie masquée du token Telegram dans cette page et association de ton compte.
5. Diagnostic avec un petit appel au moteur, puis démarrage en arrière-plan.

La fenêtre indique les erreurs et reste ouverte. Si une étape échoue, corrige-la puis relance `install.cmd`. Les fichiers de mémoire et la configuration existants sont conservés ; le setup permet de reprendre les valeurs déjà saisies. Si le bot tourne déjà, arrête-le avec `stop.cmd` avant de relancer le setup.

La page de configuration est servie sur `127.0.0.1`, donc sur ton ordinateur. Son adresse contient un secret de session : ouvre-la localement et ne la partage pas. Si le navigateur ne s'ouvre pas, utilise le lien indiqué par le programme. Aucun compte supplémentaire n'est nécessaire pour cette page.

Le lanceur utilise `-ExecutionPolicy Bypass` uniquement pour son processus PowerShell. Il ne modifie pas durablement la politique d'exécution de la machine. Si une politique d'entreprise bloque cette exécution, le script doit s'arrêter.

## macOS et Linux

Dans un terminal ouvert dans le dossier du projet :

```sh
bash scripts/install.sh codex
# Ou :
bash scripts/install.sh claude
```

Il faut Bash, `curl` et un système compatible avec le CLI choisi. Le script utilise les installateurs officiels et prépare le même environnement local. Il ne demande pas de `sudo`.

## Créer et associer le bot Telegram

1. Ouvre le compte vérifié [BotFather](https://t.me/BotFather) dans Telegram.
2. Envoie `/newbot`, choisis un nom et un identifiant qui finit par `bot`.
3. Copie le token fourni et colle-le **dans le champ masqué de la page de configuration locale**. Ne le colle pas dans Codex, Claude, un groupe ou une capture d'écran.
4. Ouvre le lien d'association proposé par cette page, puis appuie sur **Démarrer** dans Telegram.

Le lien comporte un secret temporaire. Il sert à associer ton compte sans te demander de chercher ton identifiant numérique. Le bot accepte ensuite uniquement le compte associé, dans la discussion privée. Garde ce lien pour toi jusqu'à la fin de l'association.

Si ton token a été partagé, révoque-le dans BotFather puis relance le setup avec le nouveau token. N'utilise pas le même bot pour plusieurs programmes lancés simultanément.

## Dossier de travail et accès

Commence par un dossier dédié avec quelques fichiers sans importance. Tu peux garder le dossier `workspace` proposé ou sélectionner ton propre dossier. Place tes documents de démo à l'intérieur.

Codex utilise `workspace-write`, avec les dossiers nécessaires au fonctionnement de l'assistant. Les actions qui nécessitent une permission interactive supplémentaire échouent et doivent être reprises depuis une session locale. Le bot ne contourne pas cette limite.

Claude Code dispose initialement de ses outils de lecture et modification de fichiers. Le setup propose explicitement l'activation des commandes système (`ALLOW_SHELL=1`). Cette option lui donne les capacités correspondantes avec les droits de ton compte Windows. Ce mode n'est pas un sandbox du système d'exploitation ; les consignes de dossier ne sont pas une barrière de sécurité équivalente à celle de Codex. [Limites de Claude Code sur Windows](https://code.claude.com/docs/en/setup)

## Démarrer, arrêter, diagnostiquer

| Action | Windows | macOS/Linux |
| --- | --- | --- |
| Démarrer en arrière-plan | Double-clic `start.cmd` | `bash start.sh` |
| Arrêter le service | Double-clic `stop.cmd` | `bash start.sh stop` |
| Voir son état | `.venv\Scripts\python.exe run.py status` | `bash start.sh status` |
| Diagnostic | `.venv\Scripts\python.exe run.py doctor` | `bash start.sh doctor` |
| Test avec réponse du modèle | `.venv\Scripts\python.exe run.py doctor --live` | `bash start.sh doctor --live` |
| Exécution au premier plan | `.venv\Scripts\python.exe run.py run` | `bash start.sh run` |

`doctor --live` fait un petit appel au modèle et utilise le quota du compte. Il peut prendre une à deux minutes. N'utilise `run` que pour observer un problème, après avoir arrêté le service existant ; ferme-le avec Ctrl+C. L'installation normale lance un superviseur détaché.

Pour relancer la configuration :

```powershell
# Windows
.venv\Scripts\python.exe run.py setup --provider codex
```

```sh
# macOS/Linux
bash start.sh setup --provider claude
```

Pour préparer uniquement les dépendances, sans connexion ni association : `install.cmd -Provider codex -SkipSetup` ou `bash scripts/install.sh codex --skip-setup`. Pour automatiser les lanceurs `.cmd` dans un terminal, la variable de processus `VCL_NO_PAUSE=1` supprime leur pause finale.

## Changer de moteur

Les deux moteurs peuvent être disponibles sur le même PC. Chaque moteur doit être installé et connecté à son propre compte. Pour installer le second, arrête le service puis relance l'installateur en le choisissant ; les souvenirs existants restent dans le projet.

Quand il est déjà prêt :

```sh
python run.py switch claude
# Ou :
python run.py switch codex
```

Utilise le Python de `.venv` comme dans le tableau précédent si `python` n'est pas une commande disponible. La mémoire personnelle est commune aux deux moteurs ; leurs sessions techniques sont distinctes. Effectue le changement pendant que le bot est au repos, puis suis l'indication de redémarrage affichée.

Depuis Telegram, `/switch codex` ou `/switch claude` vérifie la connexion du moteur déjà installé avant de recharger le bot. Cette commande n'installe aucun logiciel.

## Si quelque chose bloque

| Symptôme | Première action |
| --- | --- |
| `codex` ou `claude` introuvable | Relance l'installateur avec le moteur choisi. Si tu utilises un emplacement particulier, renseigne `CODEX_BIN` ou `CLAUDE_BIN` localement dans `config.env`. |
| Compte non connecté ou quota atteint | Ouvre le CLI choisi sur le PC et vérifie sa connexion et les limites du compte ; relance ensuite `doctor --live`. |
| Le bot ne répond pas | Vérifie `status`, l'alimentation du PC, sa connexion et son absence de mise en veille. |
| Erreur Telegram « Conflict » | Arrête l'autre programme utilisant ce token, puis démarre cette instance. |
| Un fichier reste introuvable | Vérifie le dossier indiqué par `/info`, puis donne un chemin réel sous ce dossier. |
| Commande Claude refusée | Elle peut nécessiter l'option de commandes système au setup. Active-la seulement si tu souhaites donner cette capacité. |
| Connexion Codex valide mais `doctor --live` échoue sur le sandbox | Ouvre Codex local une fois pour terminer sa configuration Windows native. Le mode recommandé peut demander une validation administrateur/UAC. Relance ensuite le diagnostic ; sur un PC d'entreprise, contacte le support si la politique bloque. |
| Une action Codex manque de permissions | Vérifie les règles du sandbox depuis le CLI local ; ne désactive pas ses protections pour faire passer le test. |
| `/reload` échoue après une modification | Arrête le service, corrige l'erreur avec ton assistant local et relance `start.cmd` ou `bash start.sh`. |

Le dossier `data` contient les données de fonctionnement. Avant de partager un diagnostic, retire tokens, identifiants, textes privés et chemins personnels. Ne joins jamais `config.env`.

## Mettre à jour

Arrête le service. Sauvegarde ta configuration, ta mémoire et tes documents dans un endroit privé. Lis les notes de la nouvelle release puis mets à jour le code et les dépendances. Évite d'extraire une nouvelle archive au-dessus de fichiers que ton agent a modifiés sans vérifier les différences.

La version initiale ne comporte pas de mise à jour automatique ni de lancement à l'ouverture de session Windows. Les CLI peuvent avoir leurs propres mises à jour, gérées par leur fournisseur.
