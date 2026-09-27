# Démo finale : un assistant qui retrouve son travail

Prévoir 10 à 15 minutes de démonstration après l'installation. Les participants choisissent leur moteur ; un compte Codex ou Claude Code compatible suffit.

## Préparer avant la séance

- Tester la release sur la machine de présentation avec le moteur choisi et `doctor --live`.
- Vérifier l'échange Telegram réel, `/stop`, `/clear` et `/reload` avant de présenter ces commandes.
- Copier `examples/Atelier` dans le dossier de travail autorisé, puis créer `Atelier/livrables`. Les trois fichiers fournis dans `sources` sont fictifs et peuvent être montrés en public.
- Garder l'ordinateur sur secteur, connecté et hors veille. Vérifier le quota du compte.
- Préparer une seconde copie du code fonctionnel, sans la faire tourner avec le même bot. Garder les documents exemples et un compte rendu déjà généré comme secours.
- Ouvrir l'explorateur de fichiers et Telegram côte à côte. Masquer toute fenêtre contenant un token ou un lien d'association encore actif.

Les fichiers d'exemple fournis :

```text
Atelier/
  sources/
    brief.txt
    logistique.txt
    reunion.txt
  livrables/
```

## 1. Lui faire produire quelque chose

Dans Telegram :

> Lis les trois notes du projet Atelier dans sources. Prépare un compte rendu dans Atelier/livrables/compte-rendu.md. Rassemble les décisions et les actions à suivre. Quand une information manque, signale-le.

Montrer le fichier qui apparaît dans l'explorateur, puis l'ouvrir. Relever une information effectivement présente dans les notes et une incertitude conservée. Expliquer que le téléphone a donné la consigne et que le programme sur le PC a utilisé les fichiers.

## 2. Lui apprendre une préférence et un repère de projet

Dans Telegram :

> Retiens que je préfère des comptes rendus courts, avec les personnes responsables quand elles sont connues. Mon projet Atelier est dans ce dossier ; commence par sources pour comprendre le contexte et range les documents finis dans livrables.

Afficher `/memory`. Vérifier qu'il a retenu quelques repères utiles avec leurs clés. Si le contenu n'est pas encore enregistré, demander une confirmation explicite avant de poursuivre la démo.

La mémoire doit retenir le projet, son point d'entrée et la préférence de rédaction. Elle n'a pas besoin de recopier les trois notes ni de lister chaque fichier.

## 3. Repartir d'une conversation neuve

Envoyer `/clear`, puis :

> Reprends mon projet Atelier. Prépare une courte liste des actions encore ouvertes dans son dossier de livrables.

Vérifier qu'il retrouve le chemin grâce à la mémoire, puis relit les sources actuelles. Montrer la différence entre un repère durable et les détails d'un document qu'il faut vérifier au moment du travail.

## 4. Montrer l'oubli

Choisir une préférence temporaire créée pour la démo, afficher sa clé avec `/memory`, puis envoyer `/forget CLE`. Afficher `/memory` à nouveau.

L'oubli supprime le souvenir local concerné et les références aux sessions des deux moteurs, afin de repartir sans leur ancien contexte. Il ne retire pas les anciens messages de Telegram ni les historiques conservés par les fournisseurs.

## 5. Faire évoluer l'agent et recharger

Utiliser une copie de démonstration du projet. Le code à modifier doit faire partie des dossiers accessibles au moteur ; vérifier ce point avant la séance. Une autorisation de commandes système n'est pas nécessaire pour modifier un petit fichier Python avec les outils de fichiers, mais elle peut l'être pour lancer sa vérification.

> Ajoute une commande Telegram /bonjour qui répond avec mon nom d'agent et le chemin de mon dossier de travail. Modifie uniquement le gestionnaire des commandes et son aide. Vérifie que le code reste valide. Ne redémarre pas le service toi-même ; dis-moi quand je peux envoyer /reload.

Relire le petit changement. Envoyer `/reload`, attendre la confirmation de retour du bot, puis envoyer `/bonjour`. Cette dernière partie demande une vérification préalable avec les permissions du moteur choisi. Si elles bloquent la modification, réaliser la même modification depuis Codex ou Claude Code local puis utiliser `/reload` depuis Telegram.

Éviter d'improviser une nouvelle dépendance ou une connexion externe pendant cette démonstration. L'objectif est de montrer qu'une amélioration concrète peut être chargée sans refaire l'installation.

## Si l'installation d'un participant bloque

Poursuivre la démo sur l'installation déjà prête. Le participant conserve le prompt et la documentation de diagnostic pour terminer ensuite. Ne lui faire créer aucun compte payant dans l'urgence.

Si la connexion du moteur de présentation tombe, montrer le compte rendu déjà généré en disant qu'il a été préparé auparavant. Montrer les fichiers mémoire locaux permet encore d'expliquer comment l'agent retrouve un projet. Ne pas présenter le secours comme une exécution en direct.

## Ce que les participants emportent

- La release précise du projet et son prompt d'installation.
- Un bot personnel relié à leur propre moteur et à leur propre dossier, pour ceux dont le setup est terminé.
- Un exemple de projet rangé avec ses sources et ses livrables.
- Les commandes pour inspecter et corriger la mémoire, redémarrer et arrêter le service.

Pour une séance suivante : exploitation de documents complexes, connexions à d'autres outils, tâches planifiées et usages plus autonomes. Ils ne sont pas inclus dans cette première démo.
