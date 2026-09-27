# Le prompt à copier

Ouvre **Codex ou Claude Code en local sur ton ordinateur**, dans un dossier où il peut préparer un projet. Connecte-toi à ton compte, puis copie le texte ci-dessous. Les étapes qui demandent une connexion ou un secret se passent dans ton navigateur local.

Le prompt utilise la première release `v0.1.0`. Si cette release n'est pas disponible, l'assistant doit le signaler au lieu de choisir une autre version.

```text
Installe Vibe Claw Light sur mon ordinateur depuis :
https://github.com/BorisJunior/vibe-claw-light
Version exacte : v0.1.0

Je ne suis pas technique. Explique simplement ce que tu fais et guide-moi pour les interventions qui demandent ma présence.

1. Détecte mon système. Demande-moi de choisir Codex ou Claude Code si mon choix n'est pas encore clair. Un seul moteur est nécessaire ; installe uniquement celui que je choisis. Il me faut un compte autorisant l'usage du CLI choisi. Ne suppose pas qu'un compte gratuit suffit et ne bascule jamais automatiquement vers une API payante.

2. Récupère exactement le tag v0.1.0 dans un nouveau dossier local durable nommé vibe-claw-light. Si Git est disponible, utilise git clone --branch v0.1.0 --depth 1. Sinon, télécharge l'archive https://github.com/BorisJunior/vibe-claw-light/archive/refs/tags/v0.1.0.zip puis extrais-la. Place le téléchargement temporaire hors de la racine du projet et supprime-le après extraction. N'écrase aucun dossier existant : commence par inspecter son état. Si le tag est indisponible, arrête cette étape et signale-le.

3. Lis README.md, AGENTS.md s'il existe, et docs/INSTALLATION.md. Utilise les installateurs fournis. Sur Windows, lance install.cmd -Provider codex ou install.cmd -Provider claude ; tu peux définir VCL_NO_PAUSE=1 uniquement pour ce processus afin de supprimer sa pause finale. Sur macOS/Linux, utilise bash scripts/install.sh suivi du moteur choisi. Le setup ouvre une page de configuration locale dans mon navigateur. Ne réinvente pas cette procédure. Préserve VIBE_CLAW_ROOT s'il est déjà défini : il peut appartenir à une autre instance. N'importe aucune identité, configuration ou donnée d'une autre installation.

4. Laisse tourner le setup pendant que je remplis la page locale, y compris si ton exécution de commandes est non interactive. Utilise un processus en arrière-plan si ton outil l'exige, puis suis son résultat ; ne ferme pas le serveur de configuration pendant ma saisie. Si le navigateur ne s'ouvre pas, guide-moi pour ouvrir l'adresse fournie sur mon PC. Ne simule pas mes réponses. Le projet peut préparer Python et le CLI manquant sans installer Node ni WSL sur Windows. La configuration native du sandbox Codex peut demander une validation administrateur/UAC ; accompagne-moi depuis le CLI local si nécessaire. Respecte les politiques de la machine : si l'entreprise bloque une étape, explique laquelle sans chercher à contourner cette règle ou désactiver le sandbox.

5. Vérifie la connexion au moteur choisi. Accompagne-moi pour la connexion dans le navigateur si elle manque. Guide-moi pour créer un bot dans le compte Telegram vérifié @BotFather. Fais saisir le token dans le champ masqué de la page de configuration locale, jamais dans notre conversation ni dans une commande affichée. Ne lis et n'affiche jamais le token, les fichiers d'authentification ou le contenu de config.env. L'URL de session de la page et le lien d'association Telegram temporaire sont privés ; ne les publie pas et ne les ajoute pas à des fichiers partagés.

6. Le setup me fait choisir le nom de mon assistant et son dossier de travail, puis propose l'association Telegram. Pour Claude, explique l'option de commandes système avant de me laisser la choisir ; les outils de fichiers suffisent pour la première démo. Conserve la configuration et la mémoire si je reprends une installation interrompue. Si le service tourne déjà, utilise sa commande stop avant de reprendre le setup.

7. Vérifie que python run.py doctor --live réussit avec le Python local du projet ; ce test utilise une petite part du quota du moteur. L'installateur fait déjà ce test : inutile de le répéter s'il vient de réussir. Démarre le service si ce n'est pas déjà fait et vérifie son état. Une erreur de connexion, de permissions ou de token doit être résolue avant d'annoncer que tout fonctionne.

8. Demande-moi d'envoyer depuis Telegram : « Crée un fichier bienvenue.txt dans mon dossier de travail, avec une phrase de présentation. » Vérifie la présence du fichier sans lire mes autres documents. Quand ce test a réussi, indique-moi où il est enregistré et comment redémarrer ou arrêter le bot. Explique brièvement /help, /clear, /reload, /memory et /forget.

Termine par un état factuel : moteur choisi, dossier de travail, tests réellement réussis et étape éventuelle encore bloquée. N'annonce pas un succès Telegram sans l'avoir vérifié. Ne publie rien et ne souscris à aucune offre à ma place.
```

L'assistant peut installer et diagnostiquer ; il ne peut pas se connecter à ta place ni créer le bot sans ton passage par BotFather. Garde ton téléphone et ton navigateur à portée de main.
