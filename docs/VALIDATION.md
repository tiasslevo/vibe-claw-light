# Vérifications de la version 0.2.0

Préparation du 27 septembre 2026. Ces vérifications concernent le code du starter ; l'accès au modèle dépend du compte utilisé.

## Vérifications locales

| Vérification | Environnement et résultat |
| --- | --- |
| Suite automatisée | 136 tests découverts. Deux sont réservés à Windows et trois aux terminaux POSIX ; les autres s'exécutent sur les trois OS. |
| Windows natif | Windows 11 Professionnel, Python 3.11.7, PowerShell 5.1.26100.9444 ; copie temporaire avec espaces et accent. Processus, verrous et ouverture d'une console de connexion réels. Syntaxe de `install.ps1` vérifiée. |
| Connexion interactive | Faux CLI qui demande un code : vrais terminaux POSIX, saisie via `/dev/tty`, annulation et timeout. Sous Windows, une vraie nouvelle console vérifie stdin/stdout puis son annulation. Aucun compte fournisseur utilisé dans ces tests. |
| Codex réel | Codex CLI 0.153.4 sous Linux : création d'un fichier, reprise de session, souvenir corrigé pris en compte, tour sans changement plus court et lecture du snapshot lorsqu'il manque au contexte. |
| Claude réel | Claude Code 2.1.281 sous Linux : mêmes vérifications, avec l'authentification déjà enregistrée. |
| Consolidation réelle | Débordement du budget de 8 000 caractères avec 21 notes fictives : les deux CLI ont produit une condensation acceptée. Ajout conservé et tous les textes sources préservés. Contexte final : 6 135 caractères avec Codex, 6 093 avec Claude. |
| Distribution | Construction du paquet source et du wheel. Configuration, conversations, identité, mémoire et documents privés exclus des archives. |

La suite vérifie notamment l'autorisation du compte Telegram, l'association par lien temporaire, les protections du formulaire local, la mémoire et ses corrections, la consolidation bornée, l'oubli pendant une consolidation, la persistance des messages, l'arrêt des processus et la conservation des accès d'une ancienne configuration. Les appels Telegram et les flux des modèles y sont simulés. Les appels réels aux modèles mentionnés ci-dessus ont été effectués séparément.

Dans le scénario de reprise, le message utilisateur fourni au CLI passait d'environ 1 160 caractères avec snapshot à 300 sans changement. Ce sont des caractères du message ajouté, pas la totalité des tokens facturés : les instructions natives et la conversation restent dans le contexte. La récupération du snapshot a été testée dans une session privée de ce bloc ; cela ne constitue pas un test exhaustif des compacteurs internes des fournisseurs.

Les sources de mémoire sont conservées, mais la validation structurelle ne prouve pas l'équivalence sémantique parfaite d'une reformulation. Un échec de consolidation laisse les données existantes en place et signale que l'ajout n'a pas été retenu.

Le workflow [Tests](https://github.com/tiasslevo/vibe-claw-light/actions/workflows/tests.yml) exécute aussi la suite et la construction du paquet sur Linux, Windows et macOS à chaque push. Il ne se connecte à aucun compte de modèle ni bot Telegram.

## Ce qui reste à répéter avant une présentation

Le parcours complet avec un bot Telegram neuf n'a pas été exécuté pendant cette préparation. L'installation de toutes les dépendances sur un Windows vierge et la connexion initiale aux fournisseurs restent également à vérifier sur la machine de présentation. Les tests de terminal prouvent la possibilité de saisir un code dans le processus, pas la disponibilité du parcours OAuth d'un compte neuf. Le lanceur Terminal macOS est simulé dans les tests ; aucune connexion réelle sur macOS n'a été effectuée.

Les installateurs de dépendances n'ont pas changé depuis v0.1.0. Leur précédent test Windows avait créé `.venv` avec Python 3.11.7, uv et Codex déjà disponibles ; il ne prouve pas un parcours à blanc. Les versions de CLI ci-dessus sont celles vérifiées pour v0.2.0 ; utiliser les versions officielles à jour si un CLI ancien refuse une option.

Après installation, `doctor --live` vérifie le moteur et la connexion à Telegram. Envoyer ensuite une demande depuis Telegram et vérifier le fichier produit permet de confirmer la chaîne complète. La [démo](DEMO-MASTERCLASS.md) décrit la répétition avec mémoire, nouvelle conversation et rechargement.
