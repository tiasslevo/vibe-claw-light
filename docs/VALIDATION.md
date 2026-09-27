# Vérifications de la version 0.3.0

Préparation du 27 septembre 2026. Les tests du programme, les navigateurs réels et les comptes de modèles sont distingués ci-dessous.

## Défauts reproduits et corrigés

Le formulaire v0.2.0 envoyait `Referrer-Policy: no-referrer` tout en exigeant l'origine locale pour ses POST. Des clics dans Chromium et Edge ont reproduit `Origin: null`, puis le refus 403. La nouvelle politique `same-origin` permet ces soumissions sans retirer les contrôles Host, Origin, chemin privé et CSRF. Un test témoin conserve l'ancienne politique pour vérifier que le navigateur reproduit toujours le défaut initial.

L'héritage de modules PowerShell 7 incompatibles empêchait Windows PowerShell 5.1 de trouver `Get-FileHash`. Les tests reproduisent cet environnement, puis vérifient la commande dans le véritable processus enfant après isolation du chemin des modules. Aucun profil ni paramètre système permanent n'est modifié.

## Vérifications effectuées

| Vérification | Environnement et résultat |
| --- | --- |
| Suite locale | 197 tests découverts sous Linux ; 177 exécutés avec succès, 20 ignorés car réservés à Windows ou aux navigateurs optionnels. |
| Navigateur Linux | 12 tests réussis dans Chromium 149.0.7827.55 avec Playwright 1.63.0. Vrai serveur HTTP et vrais clics, sans fabriquer l'en-tête Origin. |
| Navigateur Windows | Les mêmes 12 tests réussis dans Edge 154.0.4258.37 sur Windows natif, depuis une copie temporaire des sources publiques. |
| Formulaires | Connexion, vérification et détection automatique d'un login manuel, annulation, configuration, association, reprise après erreur, modification des réglages, démarrage et fin. Ancien onglet après redémarrage du serveur, CSRF incorrect et absence de token dans le HTML également vérifiés. |
| Installateur Windows | 6 tests réussis sous Windows PowerShell 5.1.26100.9444 et PowerShell 7.6.5, dont PS7 → cmd → PS5. Enfant PowerShell réel, dépendances et téléchargement simulés. Vérification de Get-FileHash, erreurs expurgées, UTF8, conservation de l'environnement du parent, sélection d'un seul moteur et SkipSetup. |
| Installateur shell | Test Linux avec dépendances factices : setup porte le diagnostic et le démarrage, sans double appel modèle ; --skip-setup reste disponible. Syntaxe Bash vérifiée. |
| Diagnostics | 21 tests couvrent les prérequis, les erreurs, la reprise, l'expiration et l'invalidation du cache modèle, les changements de moteur/configuration, l'annulation et le verrou empêchant deux tests simultanés. |
| Erreurs Telegram | 8 tests couvrent DNS, TLS, délai, réseau, réponses HTTP, limitation, réponses invalides, réessais bornés et expurgation des erreurs. |
| Service | 14 tests, dont de vrais processus temporaires : démarrage confirmé par le worker, rechargement, arrêt, annulation et concurrence. Une tentative annulée ferme ses propres processus. |
| Réponse et moteurs | Acquittements préfabriqués retirés ; changement de moteur vérifié sans perdre la mémoire, l'association ni les sessions ordinaires. Un moteur absent ou déconnecté laisse la configuration précédente intacte. |
| Interface | Captures inspectées sur ordinateur et petit écran. Ressources locales uniquement, sans police ni script externe. |

Les moteurs, les réponses d'authentification et Telegram restent simulés dans les tests navigateur. Un terminal interactif et une console Windows sont aussi exercés par les tests d'authentification avec un CLI factice demandant une saisie. Cela ne constitue pas une connexion OAuth réelle à un compte neuf.

Le workflow [Tests](https://github.com/tiasslevo/vibe-claw-light/actions/workflows/tests.yml) exécute la suite, construit le paquet et soumet les formulaires dans Chromium sur Linux, Windows et macOS. Playwright est une dépendance de développement et de CI uniquement ; le runtime reste sans dépendance Python externe.

Les instructions pour lancer les tests navigateur, y compris avec Edge installé sous Windows, figurent en tête de [test_browser.py](../tests/test_browser.py).

## Diagnostics avec les modèles réels

Codex CLI 0.153.4 et Claude Code 2.1.281 ont chacun exécuté le nouveau diagnostic sous Linux, avec leur authentification existante et une configuration fictive isolée. Chacun a créé le fichier temporaire exact, puis celui-ci a été supprimé. Un seul appel modèle par moteur a été autorisé et effectué.

Pour les deux moteurs, le diagnostic suivant a utilisé le cache sans nouvel appel modèle. Une panne Telegram simulée a différé le test ; le retour du réseau simulé a réutilisé le même succès. Les répertoires temporaires ont été nettoyés et aucune session de conversation existante n'a été reprise. Dans cet essai, les CLI et les modèles étaient réels ; Telegram était simulé.

## Limites de cette validation

L'installation complète sur un Windows réellement vierge, sans Python, uv, Git, Node, WSL ni CLI, n'a pas été exécutée. Les tests des installateurs valident les processus et l'environnement avec des dépendances factices ; ils ne prouvent pas la disponibilité des téléchargements officiels sur tout réseau.

Le parcours avec un nouveau compte fournisseur, un bot Telegram neuf et la réception d'un document réel n'a pas été répété pour v0.3.0. Une répétition sur la machine de présentation reste nécessaire. La page « prêt » confirme les diagnostics et le démarrage du service ; la demande bienvenue.txt dans Telegram vérifie ensuite la chaîne réelle de bout en bout.

Le cache de succès modèle dure quinze minutes et vérifie à nouveau l'authentification. Son empreinte couvre le moteur, la version du CLI, le modèle, les permissions, les dossiers et les métadonnées de fichiers d'authentification, sans lire leur contenu. Un changement de compte exclusivement enregistré dans le trousseau du système n'est pas identifié de façon garantie par cette empreinte.

Les vérifications réelles de mémoire de v0.2.0 restent distinctes : Codex CLI 0.153.4 et Claude Code 2.1.281 sous Linux avaient créé un fichier, repris une session, pris en compte un souvenir corrigé et condensé 21 notes fictives sous 8 000 caractères en conservant toutes les sources. La validation structurelle d'une condensation ne prouve pas son équivalence sémantique parfaite. La récupération d'un snapshot absent avait été testée, sans prétendre exercer exhaustivement les compacteurs internes des CLI.
