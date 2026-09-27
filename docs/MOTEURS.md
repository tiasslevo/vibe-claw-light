# Ajouter ou changer de moteur

Un seul moteur suffit pour utiliser l'assistant. Codex et Claude Code peuvent
être ajoutés séparément, lorsque la personne dispose du compte correspondant.
Le choix du moteur ne remplace ni le bot Telegram ni la mémoire personnelle.
Chaque moteur garde sa propre conversation ; l'historique complet de l'autre
moteur n'est pas transféré.

## Depuis Telegram

Envoie `/switch codex` ou `/switch claude`.

- Si le moteur est installé et connecté, le bot enregistre le choix puis se
  recharge. Son message de retour en ligne indique le moteur utilisé.
- Si le moteur est détecté mais sa connexion n'est pas confirmée, termine la
  connexion sur le PC puis renvoie la commande. Le bot fournit les indications.
- S'il est introuvable, le bot fournit une demande à copier dans Codex ou Claude
  Code sur le PC. Il ne lance pas d'installation silencieuse depuis Telegram.

La vérification de connexion ne garantit pas qu'il reste du quota. Si le
fournisseur refuse une demande, l'assistant indique l'erreur ; il ne change pas
automatiquement de compte ou de mode de facturation.

## Demande à copier dans l'assistant local

Ouvre le dossier **déjà installé** de Vibe Claw Light dans Codex ou Claude Code,
puis copie ceci en choisissant le moteur souhaité :

> Ajoute seulement le moteur Claude Code à cette installation de Vibe Claw
> Light en suivant docs/MOTEURS.md. Conserve ma configuration Telegram, ma
> mémoire et les conversations existantes. Accompagne-moi pour la connexion
> officielle dans un terminal interactif, puis vérifie le démarrage. Ne crée
> pas une deuxième installation et n'installe pas les deux moteurs.

Pour Codex, remplace « Claude Code » par « Codex ».

## Procédure pour l'assistant local

Cette procédure s'exécute depuis l'assistant ouvert sur le PC, avec la personne
disponible pour la connexion. Elle ne doit pas être exécutée par le bot Telegram
sur son propre processus.

1. Vérifier le dossier existant, le moteur demandé et son éventuelle connexion.
   Respecter le chemin `CODEX_BIN` ou `CLAUDE_BIN` s'il est configuré. Ne pas
   afficher `config.env` ni les fichiers d'authentification.
2. Si le moteur est déjà installé et connecté, utiliser `/switch` dans Telegram.
   Si seule la connexion manque, accompagner le login officiel, vérifier son
   statut puis utiliser `/switch`. Ces cas n'exigent ni installation ni setup.
3. Si le moteur manque, arrêter **cette instance seulement** avec sa commande
   locale avant de préparer ses dépendances. `/stop` dans Telegram met le
   travail en pause mais n'arrête pas le service. Conserver `config.env`,
   `data/`, `memory/`, `identity/` et les documents. Une tâche interrompue n'est
   pas rejouée automatiquement.
4. Lancer l'installateur du moteur demandé avec `SkipSetup`. Ce mode prépare
   ses dépendances sans formulaire, login, nouvelle association Telegram,
   diagnostic ni démarrage automatique.
5. Ouvrir un vrai terminal pour son login officiel. La personne termine les
   étapes dans le navigateur et, si nécessaire, colle le code dans ce terminal.
   Aucun code ni mot de passe ne doit passer dans le chat avec l'assistant.
6. Vérifier le statut de connexion. Sélectionner le moteur avec la commande
   locale `switch`, puis exécuter `doctor`. Un échec de connexion doit être
   résolu avant de sélectionner le moteur.
7. Démarrer l'instance et vérifier `status`, puis son message de retour dans
   Telegram. Demander une petite tâche personnalisée au nouveau moteur pour
   vérifier son fonctionnement. Ne déclarer le bot prêt qu'après ces étapes.

Les commandes ci-dessous se lancent dans le dossier de l'installation. Elles
montrent l'ajout de Claude ; pour Codex, utiliser `codex` et `codex login` /
`codex login status`.

Windows, préparation :

```powershell
.\stop.cmd
.\install.cmd -Provider claude -SkipSetup
```

Dans un terminal interactif sur le PC, avec le CLI détecté :

```text
claude auth login
claude auth status
```

Puis, uniquement après une connexion confirmée :

```powershell
.\.venv\Scripts\python.exe run.py switch claude
.\.venv\Scripts\python.exe run.py doctor
.\start.cmd
.\.venv\Scripts\python.exe run.py status
```

macOS/Linux, préparation :

```sh
bash start.sh stop
bash scripts/install.sh claude --skip-setup
```

Terminer le login dans un terminal interactif, puis :

```sh
bash start.sh switch claude
bash start.sh doctor
bash start.sh start
bash start.sh status
```

Vérifier chaque résultat avant de poursuivre. `doctor` sans `--live` ne lance
pas de modèle. Un petit test réel avec `doctor --live` est également possible
et utilise le quota du compte ; ne pas le répéter lorsqu'il vient de réussir.
Après une installation native, le terminal courant peut avoir un ancien PATH :
ouvrir un nouveau terminal ou utiliser le chemin absolu de l'exécutable détecté.
Ne pas réinstaller un moteur simplement parce que ce terminal ne le trouve pas.

Si la personne préfère le formulaire de configuration pour le login, le service
doit rester arrêté pendant `setup --provider claude` (ou `codex`). Conserver le
token existant et l'association proposée. Le setup complet n'est pas nécessaire
pour ajouter seulement un moteur déjà installé.

En cas d'échec avant le changement de moteur, l'ancien choix reste enregistré ;
le service peut être redémarré avec ce moteur. Après le changement, revenir à
l'ancien moteur avec `/switch` ou la commande locale `switch`, sans déconnecter
les comptes ni supprimer les sessions. Le quota propre à chaque compte reste
applicable.
