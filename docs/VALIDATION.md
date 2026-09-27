# Vérifications de la version 0.1.0

Préparation du 27 septembre 2026. Ces vérifications concernent le code du starter ; l'accès au modèle dépend du compte utilisé.

## Vérifications locales

| Vérification | Environnement et résultat |
| --- | --- |
| Suite automatisée | 87 tests : 86 exécutés sous Linux, un test réservé à Windows. Les 87 sont exécutés sous Windows natif. |
| Windows | Windows 11, Python 3.11.7, PowerShell 5.1 ; chemin contenant des espaces et un accent. Les processus et verrous Windows sont réels. |
| Installation Windows | `install.ps1 -Provider codex -SkipSetup` a créé `.venv` avec Python 3.11.7. `uv 0.5.21` et Codex natif 0.157.1 étaient déjà disponibles pour ce test. |
| Codex réel | Codex CLI 0.153.4 sous Linux : création d'un fichier, proposition et enregistrement de mémoire, reprise de la même conversation. |
| Claude réel | Claude Code 2.1.281 sous Linux : création d'un fichier, proposition et enregistrement de mémoire, reprise de la même conversation. |
| Distribution | Construction du paquet source et du wheel. Configuration, conversations, identité, mémoire et documents privés exclus des archives. |

La suite vérifie notamment l'autorisation du compte Telegram, l'association par lien temporaire, les protections du formulaire local, la mémoire et ses corrections, la persistance des messages, l'arrêt des processus, `/clear`, `/reload` et l'isolation entre installations. Les appels Telegram et les flux des modèles y sont simulés. Les appels réels aux modèles mentionnés ci-dessus ont été effectués séparément.

Le workflow [Tests](https://github.com/tiasslevo/vibe-claw-light/actions/workflows/tests.yml) exécute aussi la suite et la construction du paquet sur Linux, Windows et macOS à chaque push. Il ne se connecte à aucun compte de modèle ni bot Telegram.

## Ce qui reste à répéter avant une présentation

Le parcours complet avec un bot Telegram neuf n'a pas été exécuté pendant cette préparation. L'installation de toutes les dépendances sur un Windows vierge et la connexion initiale aux fournisseurs restent également à vérifier sur la machine de présentation. Le test Windows local avait déjà Python et uv à disposition ; il ne prouve pas ce parcours à blanc.

Après installation, `doctor --live` vérifie le moteur et la connexion à Telegram. Envoyer ensuite une demande depuis Telegram et vérifier le fichier produit permet de confirmer la chaîne complète. La [démo](DEMO-MASTERCLASS.md) décrit la répétition avec mémoire, nouvelle conversation et rechargement.
