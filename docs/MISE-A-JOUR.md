# Mettre à jour son assistant

Si ton assistant a ajouté le vocal ou une autre fonctionnalité, sa copie contient des changements locaux. La mise à jour doit les intégrer avec ceux de la nouvelle version. Garde le dossier actuel et ouvre-le dans Codex ou Claude Code sur le PC, puis copie cette demande :

```text
Mets à jour cette installation de Vibe Claw Light vers le tag v0.3.2 du dépôt
https://github.com/tiasslevo/vibe-claw-light.

Inspecte la version et les changements locaux avant toute modification. Lis les
consignes du dépôt. Préserve VIBE_CLAW_ROOT s'il est déjà défini.

Conserve ma configuration Telegram, mon moteur, mes permissions, ma personnalité,
mes souvenirs, mes documents et les fonctionnalités que j'ai ajoutées, notamment
le vocal s'il est présent. Ne publie aucune donnée privée.

Prépare une sauvegarde locale du code modifié. Récupère la version exacte, compare
les différences et fusionne-les dans cette installation. Ne remplace pas tout le
dossier et n'utilise pas de reset qui effacerait mes changements. Pour une copie
sans Git, compare les sources dans un dossier temporaire distinct avant de les
intégrer. Préserve aussi les dépendances ajoutées à pyproject.toml et uv.lock.

Vérifie la mise à jour et la présence de mes fonctionnalités existantes. Ne
réinitialise pas le bot et ne relance pas le parcours d'association Telegram.
Si cette session travaille depuis Telegram, ne tente pas d'arrêter ton propre
listener : indique-moi quand envoyer /reload. Depuis l'assistant local du PC,
utilise uniquement les commandes de cette installation si un arrêt est nécessaire.

Explique simplement le résultat et les vérifications réellement effectuées.
```

La v0.3.2 modifie les consignes de communication. Au rechargement, le mécanisme existant ouvre une nouvelle conversation pour appliquer ces consignes. La mémoire durable et les fichiers personnels sont conservés ; les historiques du fournisseur ne sont pas supprimés.
