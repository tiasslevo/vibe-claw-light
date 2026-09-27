# Vibe Claw Light

Ton assistant personnel sur Telegram, relié à ton ordinateur. Il peut lire tes notes, préparer des documents, lancer des commandes et retrouver tes projets d'une conversation à l'autre.

Tu choisis **Codex ou Claude Code**. Un seul compte compatible et un seul moteur installé suffisent. Le modèle tourne chez le fournisseur ; aucun GPU ni modèle local à installer.

**Version : `v0.3.1`.** Windows 11 est la cible principale, avec des scripts aussi pour macOS et Linux. Les tests et leurs limites sont détaillés dans [le relevé de validation](docs/VALIDATION.md). Prévois une répétition avec ton propre bot avant un atelier.

## Démarrer

Il te faut un ordinateur connecté, Telegram et un accès au CLI choisi. L'abonnement à une application de chat ne garantit pas tous les usages du CLI : [vérifie les prérequis](docs/INSTALLATION.md#compte-et-ordinateur).

1. Télécharge la [version `v0.3.1`](https://github.com/tiasslevo/vibe-claw-light/releases/tag/v0.3.1) et extrais l'archive dans un dossier que tu garderas.
2. **Windows :** double-clique sur `install.cmd`. **macOS/Linux :** ouvre un terminal dans le dossier et lance `bash scripts/install.sh`.
3. Choisis `codex` ou `claude`. Si nécessaire, termine la connexion dans le terminal et sur le site officiel. Tout code à recopier se colle dans ce terminal.
4. Crée ton bot avec [BotFather](https://t.me/BotFather), saisis son token dans la page locale de configuration, puis ouvre le lien d'association Telegram.
5. Reste sur la page jusqu'à ce qu'elle confirme **Telegram associé, modèle testé et service démarré**. Ouvre alors ton bot et envoie une première demande.

L'installateur récupère Python et le moteur choisi s'ils manquent. La page suit les vérifications et le démarrage. Si une étape bloque, elle indique laquelle et permet de la reprendre. Un test modèle réussi est réutilisé pendant quinze minutes si sa configuration reste identique. Ferme le terminal une fois l'assistant prêt ; le PC doit rester allumé, connecté et hors veille.

Tu préfères te faire guider par Codex ou Claude Code ? Copie le [prompt d'installation](docs/PROMPT-INSTALLATION.md) dans une session locale de ton outil.

## Ce que tu peux lui demander

> Lis les notes dans le dossier Atelier. Prépare un compte rendu dans Atelier/livrables et liste les décisions qui restent à prendre.

> Quand tu rédiges pour moi, utilise des paragraphes courts. Retiens cette préférence.

> Mon projet Atelier est dans ce dossier. Les notes sont dans sources, les documents finis dans livrables. Retiens où commencer quand je t'en reparle.

La mémoire garde des repères compacts : préférences utiles, habitudes confirmées, projets et endroits où travailler. Elle reste disponible après `/clear` et lors d'un changement de moteur. Quand un ajout dépasse le budget de contexte, le programme peut demander au modèle de raccourcir les notes, avec deux tentatives maximum. Les textes sources et les chemins restent conservés. [Voir son fonctionnement](docs/MEMOIRE.md).

La conversation est reprise par le CLI choisi. La personnalité facultative vit dans `identity/SOUL.md` ; le profil utilisateur fait partie de la mémoire commune, sans `USER.md` supplémentaire. La mémoire automatique propre au CLI est désactivée uniquement pour les appels du starter, sans toucher à sa configuration globale.

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
| `/switch codex` ou `/switch claude` | Changer de moteur ou recevoir le guide pour le préparer |

Après un redémarrage du PC, utilise `start.cmd` sous Windows ou `bash start.sh` sur macOS/Linux. Pour éteindre le service : `stop.cmd` ou `bash start.sh stop`. `/stop` interrompt une tâche ; le bot continue à recevoir tes messages.

## Ce qui est inclus

Le bot traite les messages texte et les documents d'un seul compte Telegram associé. Les fichiers reçus ou envoyés sont limités à 20 Mio. Leur lecture dépend des capacités du moteur et des outils présents ; commence par des fichiers texte. Il reprend sa conversation, conserve une mémoire personnelle et redémarre via `/reload`.

Les nouvelles installations proposent **Documents/MonAssistant** pour ranger les nouveaux travaux. Le mode **Assistant personnel** permet aussi de travailler dans les autres projets de ton dossier utilisateur, avec les commandes et le réseau actifs. Le mode **Limité aux dossiers choisis** reste disponible. Codex conserve son sandbox `workspace-write` ; les autorisations d'outils de Claude ne constituent pas une sandbox système Windows. [Détail des accès](docs/INSTALLATION.md#dossier-de-rangement-et-accès).

Les livrables peuvent être envoyés depuis les dossiers autorisés ; l'envoi des emplacements d'authentification connus et des données internes du starter est bloqué. Une mise à jour depuis la v0.1 conserve son dossier et son ancien mode d'accès tant que tu ne les changes pas.

Cette version reste légère : pas de veille Twitter, de vocal, de modèle local, de navigateur piloté ou de publication automatique. Le service démarre à la demande ; aucun lancement automatique à l'ouverture de Windows n'est installé.

Tes messages passent par Telegram et le moteur choisi ; les données utiles à la tâche sont envoyées à ce moteur. La configuration, les conversations et la mémoire locales restent hors Git. Le token Telegram se saisit localement et ne doit jamais apparaître dans un prompt partagé.

- [Installation et diagnostic](docs/INSTALLATION.md)
- [Ajouter ou changer de moteur](docs/MOTEURS.md)
- [Mémoire personnelle](docs/MEMOIRE.md)
- [Démo de masterclass](docs/DEMO-MASTERCLASS.md)
- [Architecture et limites](docs/ARCHITECTURE.md)

Licence MIT.
