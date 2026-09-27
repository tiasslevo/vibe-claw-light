# Vibe Claw Light

Ton assistant personnel sur Telegram, relié à un dossier de ton ordinateur. Il peut lire tes notes, préparer des documents et retrouver tes projets d'une conversation à l'autre.

Tu choisis **Codex ou Claude Code**. Un seul compte compatible et un seul moteur installé suffisent. Le modèle tourne chez le fournisseur ; aucun GPU ni modèle local à installer.

**Première version : `v0.1.0`.** Windows 11 est la cible principale, avec des scripts aussi pour macOS et Linux. Les tests et leurs limites sont détaillés dans [le relevé de validation](docs/VALIDATION.md). Prévois une répétition avec ton propre bot avant un atelier.

## Démarrer

Il te faut un ordinateur connecté, Telegram et un accès au CLI choisi. L'abonnement à une application de chat ne garantit pas tous les usages du CLI : [vérifie les prérequis](docs/INSTALLATION.md#compte-et-ordinateur).

1. Télécharge la [version `v0.1.0`](https://github.com/BorisJunior/vibe-claw-light/releases/tag/v0.1.0) et extrais l'archive dans un dossier que tu garderas.
2. **Windows :** double-clique sur `install.cmd`. **macOS/Linux :** ouvre un terminal dans le dossier et lance `bash scripts/install.sh`.
3. Choisis `codex` ou `claude`, connecte ton compte et suis les indications pour créer ton bot avec [BotFather](https://t.me/BotFather).
4. Saisis le token dans la page de configuration locale ouverte dans ton navigateur, ouvre le lien d'association Telegram puis écris à ton bot.

L'installateur récupère Python et le moteur choisi s'ils manquent. Il vérifie une petite réponse du modèle avant de démarrer le service. Tu peux ensuite fermer le terminal. Le PC doit rester allumé, connecté et hors veille.

Tu préfères te faire guider par Codex ou Claude Code ? Copie le [prompt d'installation](docs/PROMPT-INSTALLATION.md) dans une session locale de ton outil.

## Ce que tu peux lui demander

> Lis les notes dans le dossier Atelier. Prépare un compte rendu dans Atelier/livrables et liste les décisions qui restent à prendre.

> Quand tu rédiges pour moi, utilise des paragraphes courts. Retiens cette préférence.

> Mon projet Atelier est dans ce dossier. Les notes sont dans sources, les documents finis dans livrables. Retiens où commencer quand je t'en reparle.

La mémoire garde des repères compacts : préférences utiles, habitudes confirmées, projets et endroits où travailler. Elle reste disponible après `/clear` et lors d'un changement de moteur. [Voir son fonctionnement](docs/MEMOIRE.md).

L'agent suit les consignes de rangement du projet, sépare sources et livrables et vérifie les chemins avant d'agir. Les fichiers qu'il consulte restent des données ; leur contenu ne lui donne aucune autorisation supplémentaire.

## Les commandes utiles

| Dans Telegram | Effet |
| --- | --- |
| `/help` | Afficher l'aide |
| `/info` | Voir le moteur et le dossier de travail |
| `/stop` | Interrompre la tâche en cours et mettre la file en pause |
| `/continue` | Reprendre les demandes en attente |
| `/clear` | Recommencer la conversation en gardant la mémoire |
| `/reload` | Recharger le programme après une modification |
| `/memory` | Consulter les souvenirs et leurs clés |
| `/forget CLE` | Supprimer un souvenir identifié par sa clé |
| `/switch codex` ou `/switch claude` | Choisir un moteur déjà installé et connecté |

Après un redémarrage du PC, utilise `start.cmd` sous Windows ou `bash start.sh` sur macOS/Linux. Pour éteindre le service : `stop.cmd` ou `bash start.sh stop`. `/stop` interrompt une tâche ; le bot continue à recevoir tes messages.

## Ce qui est inclus

Le bot traite les messages texte et les documents d'un seul compte Telegram associé. Les fichiers reçus ou envoyés sont limités à 20 Mio. Leur lecture dépend des capacités du moteur et des outils présents ; commence par des fichiers texte. Il reprend sa conversation, conserve une mémoire personnelle et redémarre via `/reload`. Le dossier de travail est choisi pendant l'installation. Claude utilise les outils de fichiers par défaut ; les commandes système demandent un choix explicite au setup. Codex utilise son mode `workspace-write`.

Cette version reste légère : pas de veille Twitter, de vocal, de modèle local, de navigateur piloté ou de publication automatique. Le service démarre à la demande ; aucun lancement automatique à l'ouverture de Windows n'est installé.

Tes messages passent par Telegram et le moteur choisi ; les données utiles à la tâche sont envoyées à ce moteur. La configuration, les conversations et la mémoire locales restent hors Git. Le token Telegram se saisit localement et ne doit jamais apparaître dans un prompt partagé.

- [Installation, diagnostic et changement de moteur](docs/INSTALLATION.md)
- [Mémoire personnelle](docs/MEMOIRE.md)
- [Démo de masterclass](docs/DEMO-MASTERCLASS.md)
- [Architecture et limites](docs/ARCHITECTURE.md)

Licence MIT.
