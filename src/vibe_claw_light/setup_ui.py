"""Interface locale autonome : aucune police, image ou ressource distante."""
from html import escape
import base64
import hashlib
import os

from .auth import manual_command


WATCH_SCRIPT = """
(() => {
  let timer;
  let submitting = false;
  let previous = document.querySelector('main').innerHTML;
  document.addEventListener('submit', () => {
    submitting = true;
    clearTimeout(timer);
  });
  async function check() {
    if (submitting) return;
    try {
      const response = await fetch(location.href, {cache: 'no-store'});
      if (response.ok) {
        const next = new DOMParser().parseFromString(await response.text(), 'text/html');
        if (submitting) return;
        const main = next.querySelector('main');
        // Comparer au dernier rendu serveur, pas au DOM que la personne utilise.
        // Ouvrir un détail ou sélectionner le lien doit rester sans effet ici.
        if (main && main.innerHTML !== previous) {
          previous = main.innerHTML;
          document.querySelector('main').replaceWith(main);
          const steps = next.querySelector('.steps');
          if (steps) document.querySelector('.steps').replaceWith(steps);
        }
        // Le formulaire de saisie et les étapes terminées ne sont jamais sondés.
        if (next.body.dataset.watch !== 'true') return;
      }
    } catch (_) {
      // Une coupure passagère ne doit pas effacer la page courante.
    }
    if (!submitting) timer = setTimeout(check, 3000);
  }
  timer = setTimeout(check, 3000);
})();
"""
WATCH_CSP = "'sha256-" + base64.b64encode(hashlib.sha256(WATCH_SCRIPT.encode()).digest()).decode() + "'"


STYLE = """
:root{color-scheme:light;--ink:#191919;--muted:#686868;--line:#eaeaea;--paper:#fff;--canvas:#f8f8f6}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--canvas);font:16px/1.6 'Segoe UI','Helvetica Neue',Arial,sans-serif}
a{color:inherit;text-underline-offset:4px}button,input,select{font:inherit}button,a,input,select,summary{touch-action:manipulation}
:focus-visible{outline:2px solid var(--ink);outline-offset:4px}button{cursor:pointer}button:active,.button:active{transform:translateY(1px)}
.shell{max-width:1040px;margin:0 auto;padding:32px 32px 24px}.brandbar{display:flex;justify-content:space-between;align-items:center;gap:20px;padding-bottom:28px;border-bottom:1px solid var(--line)}
.brand{font-size:19px;font-weight:750;letter-spacing:-.7px}.brand span{font-weight:400}.local{font:11px/1.4 'SFMono-Regular',Consolas,monospace;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}
.layout{max-width:680px;margin:44px auto 24px}.steps{display:flex;list-style:none;padding:0;margin:0 0 28px;gap:12px;counter-reset:step}.steps li{flex:1;font-size:12px;color:var(--muted);padding-top:12px;border-top:2px solid #dededb}.steps li.current{color:var(--ink);font-weight:650;border-color:var(--ink)}.steps li.complete{border-color:#92928f}.steps span{font:11px Consolas,monospace;margin-right:6px}
main{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:40px 44px;min-width:0;animation:arrive .24s ease-out}.eyebrow{margin:0 0 18px;font:11px/1.4 Consolas,monospace;letter-spacing:1.1px;text-transform:uppercase;color:var(--muted)}
h1{font:normal 43px/1.08 Georgia,'Times New Roman',serif;letter-spacing:-1.5px;margin:0 0 18px;text-wrap:balance}h2{font-size:17px;line-height:1.4;margin:24px 0 8px}p{margin:0 0 18px}.intro{font-size:16px;color:#595959;margin-bottom:28px}.hint{font-size:13px;line-height:1.6;color:var(--muted);margin:8px 0 18px}.field{margin:0 0 22px}label{display:block;font-size:14px;font-weight:600;margin-bottom:8px}
select,input:not([type=checkbox]):not([type=hidden]){display:block;width:100%;padding:12px 14px;color:var(--ink);border:1px solid #d3d3d0;border-radius:6px;background:white;margin-top:8px;min-height:48px}input::placeholder{color:#92928f}.check{display:flex;align-items:flex-start;gap:10px;font-weight:400;font-size:13px;margin:20px 0}.check input{margin:5px 0 0;accent-color:var(--ink);flex-shrink:0}
button,.button{display:inline-flex;align-items:center;justify-content:center;gap:10px;border:1px solid var(--ink);background:var(--ink);color:white;border-radius:5px;padding:12px 18px;min-height:48px;font-size:14px;font-weight:600;text-align:center;text-decoration:none;transition:background .15s;max-width:100%}button:hover,.button:hover{background:#353535}.primary{width:100%;margin-top:4px}.secondary{background:white;border-color:#d3d3d0;color:var(--ink);font-weight:500}.secondary:hover{background:#f4f4f1}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}.actions form{flex:1}.actions button{width:100%}form+form{margin-top:12px}
details{margin:24px 0 0;border-top:1px solid var(--line);padding-top:18px}summary{cursor:pointer;font-size:13px;font-weight:600}details p{margin:14px 0 0;font-size:13px;color:#595959}code{font:12px/1.7 Consolas,monospace;background:#f5f5f2;padding:3px 5px;overflow-wrap:anywhere}.command{display:block;padding:16px;margin-top:12px;white-space:pre-wrap}.error{padding:15px 17px;background:#f8efeb;color:#76392c;border:1px solid #ecdcd4;border-radius:6px;font-size:14px;margin-bottom:24px}.note{background:#f7f7f4;border:1px solid var(--line);border-radius:6px;padding:18px;font-size:14px;margin:24px 0}.note p:last-child{margin-bottom:0}.link{font:12px/1.6 Consolas,monospace;overflow-wrap:anywhere;padding:14px;background:#f7f7f4;border:1px solid var(--line);border-radius:6px}
.checks{list-style:none;padding:0;margin:24px 0;border-top:1px solid var(--line)}.checks li{display:flex;align-items:flex-start;gap:12px;padding:14px 0;border-bottom:1px solid var(--line);font-size:14px}.checks small{display:block;color:var(--muted);font-size:12px;line-height:1.6;margin-top:3px}.status{width:19px;height:19px;flex:none;margin-top:2px;border:1px solid #d8d8d4;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font:12px Arial}.status.ok{background:var(--ink);border-color:var(--ink);color:white}.status.error-state{color:#76392c;border-color:#d4a79c}.status.running{border-color:#aaa;border-top-color:#111;animation:spin 1s linear infinite}.success-icon{display:inline-flex;width:38px;height:38px;background:var(--ink);color:white;border-radius:50%;align-items:center;justify-content:center;margin-bottom:22px;font-size:20px}
.footer{display:flex;justify-content:space-between;gap:20px;color:var(--muted);font-size:11px;padding:26px 0 4px}.footer span:last-child{text-align:right}.meta{color:var(--muted);font-size:12px;margin:18px 0 0}.split{display:flex;justify-content:space-between;gap:16px;align-items:center}
@keyframes spin{to{transform:rotate(360deg)}}@keyframes arrive{from{opacity:.3;transform:translateY(6px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
@media(max-width:640px){.shell{padding:20px 18px 16px}.brandbar{padding-bottom:20px}.layout{margin-top:28px}main{padding:28px 24px}h1{font-size:36px}.steps{gap:8px}.steps li{font-size:11px}.steps span{display:block;margin-bottom:5px}.local{font-size:9px}.footer{font-size:10px}.actions{display:block}.actions form+form{margin-top:12px}}
"""


def page(body: str, *, phase: str = "", provider: str = "", refresh: bool = False) -> bytes:
    steps = ""
    stage = {"auth": 0, "authenticating": 0, "configure": 1, "validating": 2,
             "pairing": 2, "diagnostics": 3, "starting": 3, "blocked": 3, "ready": 3}.get(phase)
    if stage is not None:
        items = []
        for index, label in enumerate(("Connexion", "Assistant", "Telegram", "Démarrage")):
            state = "current" if index == stage else ("complete" if index < stage else "")
            current = ' aria-current="step"' if index == stage else ""
            items.append(f'<li class="{state}"{current}><span>0{index + 1}</span>{label}</li>')
        steps = '<ol class="steps" aria-label="Étapes de l’installation">' + "".join(items) + '</ol>'
    watch = '<script>' + WATCH_SCRIPT + '</script>' if refresh else ""
    engine = {"claude": "Claude Code", "codex": "Codex"}.get(provider, "")
    eyebrow = '<p class="eyebrow">Votre assistant personnel' + (f' / {escape(engine)}' if engine else '') + '</p>'
    return (f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Votre assistant · Vibe Claw Light</title><style>{STYLE}</style></head><body data-watch="{"true" if refresh else "false"}">'
            '<div class="shell"><header class="brandbar"><div class="brand">parlons<span> ia</span></div>'
            '<span class="local">Vibe Claw Light / installation</span></header>'
            f'<div class="layout">{steps}<main>{eyebrow}{body}</main>'
            '<footer class="footer"><span>Un assistant sur votre ordinateur.</span><span>PC allumé · Internet connecté</span></footer>'
            f'</div></div>{watch}</body></html>').encode("utf-8")


def render_wizard(wizard) -> bytes:
    e = escape
    hidden = f'<input type="hidden" name="csrf" value="{e(wizard.csrf)}">'

    def form(action, contents):
        return f'<form method="post" action="{e(wizard.path + action)}" autocomplete="off">{hidden}{contents}</form>'

    phase = wizard.phase
    engine = "Claude Code" if wizard.provider == "claude" else "Codex"
    body = f'<p role="alert" class="error">{e(wizard.error)}</p>' if wizard.error else ""
    if phase == "auth":
        command = manual_command(wizard.provider, wizard.executable)
        body += f'<h1>Connectez votre compte.</h1><p class="intro">Votre assistant utilisera {engine}. Connectez le compte dont vous souhaitez utiliser l’abonnement.</p>'
        body += form("login", '<button class="primary">Se connecter avec ' + engine + '</button>')
        body += '<div class="note"><p>Une fenêtre de terminal s’ouvrira, puis le site officiel. Si un code est demandé, collez-le dans ce terminal.</p></div>'
        body += form("check-login", '<button class="secondary primary">J’ai terminé la connexion, vérifier</button>')
        body += '<p class="hint">Vous êtes déjà connecté ? La page le vérifie automatiquement pendant cinq minutes.</p>'
        body += '<details><summary>Ouvrir la connexion manuellement</summary><p>Ouvrez un terminal sur ce PC' + (' (PowerShell)' if os.name == 'nt' else '') + ', lancez cette commande, puis revenez ici.</p>'
        body += f'<code class="command">{e(command)}</code></details>'
    elif phase == "authenticating":
        body += '<h1>La connexion continue dans le terminal.</h1><p class="intro">Terminez le parcours sur le site officiel. Un éventuel code de confirmation doit être collé dans le terminal ouvert.</p>'
        body += '<p>Cette page passera automatiquement à la suite dès que la connexion sera détectée.</p>'
        body += form("check-login", '<button class="primary">J’ai terminé la connexion, vérifier</button>')
        body += form("cancel-login", '<button class="secondary primary">Annuler la connexion</button>')
    elif phase == "configure":
        existing = bool(wizard.initial["TELEGRAM_TOKEN"])
        body += '<h1>Faites-lui une place.</h1><p class="intro">Choisissez un nom, un dossier de rangement et le bot Telegram avec lequel vous échangerez.</p>'
        fields = f'<div class="field"><label>Nom de l’assistant<input name="name" maxlength="80" required value="{e(wizard.name, quote=True)}"></label></div>'
        fields += f'<div class="field"><label>Dossier de rangement<input name="workspace" required value="{e(wizard.workspace, quote=True)}" spellcheck="false"></label><p class="hint">Les nouveaux documents seront rangés ici. Vos autres projets restent accessibles selon le mode choisi.</p></div>'
        fields += '<div class="field"><label>Accès de l’assistant<select name="access_mode">'
        for mode, label in (("personal", "Assistant personnel"), ("workspace", "Limité aux dossiers choisis")):
            selected = ' selected' if wizard.access_mode == mode else ''
            fields += f'<option value="{mode}"{selected}>{label}</option>'
        fields += '</select></label><p class="hint">Personnel : vos projets et documents du dossier utilisateur, les commandes et Internet. Limité : le dossier du starter, le dossier de rangement et les dossiers ajoutés dans les réglages.</p></div>'
        fields += '<div class="field"><label>Token du bot Telegram<input type="password" name="token" autocomplete="new-password" spellcheck="false"' + ('' if existing else ' required') + ' placeholder="Collez le token de BotFather"></label>'
        fields += '<p class="hint">Ouvrez <a href="https://t.me/BotFather" target="_blank" rel="noreferrer noopener">BotFather</a> dans Telegram, envoyez <code>/newbot</code>, puis copiez le token ici. Il reste dans la configuration privée de ce PC.</p></div>'
        if existing:
            fields += '<p class="hint">Un token est déjà enregistré. Laissez ce champ vide pour le conserver.</p>'
        owner, chat = wizard.initial["TELEGRAM_OWNER_ID"], wizard.initial["TELEGRAM_CHAT_ID"]
        if existing and owner.isdecimal() and int(owner) > 0 and owner == chat:
            fields += '<label class="check"><input type="checkbox" name="keep_owner" value="1" checked><span>Conserver mon association Telegram si le token reste le même.</span></label>'
        if wizard.provider == "claude":
            checked = ' checked' if wizard.allow_shell else ''
            fields += f'<details><summary>Commandes en mode limité</summary><label class="check"><input type="checkbox" name="allow_shell" value="1"{checked}><span>Autoriser aussi les commandes de Claude Code.</span></label><p>Le mode personnel les autorise déjà. Les permissions Claude ne constituent pas une sandbox système.</p></details>'
        fields += '<button class="primary">Vérifier et associer Telegram</button><p class="meta">Ensuite : un test réel du moteur, puis le démarrage. Ce test utilise une petite part de votre quota.</p>'
        body += form("configure", fields)
    elif phase == "validating":
        body += '<h1>Vérifions votre bot.</h1><p class="intro">La connexion à Telegram est en cours. Vos réglages précédents restent conservés jusqu’à l’association.</p>'
        body += form("cancel", '<button class="secondary">Revenir au formulaire</button>')
    elif phase == "pairing":
        body += '<h1>Un dernier lien à ouvrir.</h1><p class="intro">Ouvrez votre bot avec votre compte Telegram personnel, puis appuyez sur <strong>Démarrer</strong>.</p>'
        body += f'<a class="button primary" href="{e(wizard.pair_link, quote=True)}" target="_blank" rel="noreferrer noopener">Ouvrir @{e(wizard.bot_username)}</a>'
        body += '<p class="hint">La page passera automatiquement à la suite après l’association.</p>'
        body += f'<details><summary>Ouvrir le lien sur un autre appareil</summary><p class="link">{e(wizard.pair_link)}</p><p>Ce lien privé expire après cinq minutes. Il associe votre compte à l’assistant.</p></details>'
        body += form("cancel", '<button class="secondary">Revenir au formulaire</button>')
    elif phase in {"diagnostics", "starting", "blocked", "ready"}:
        if phase == "ready":
            body += '<div class="success-icon" aria-hidden="true">✓</div>'
            body += f'<h1>{e(wizard.name)} est prêt.</h1><p class="intro">Le modèle a été testé et le service est démarré. Vous pouvez maintenant lui écrire dans Telegram.</p>'
        elif phase == "blocked":
            body += '<h1>Reprenons à cette étape.</h1><p class="intro">Votre configuration est enregistrée. Le test modèle déjà réussi reste réutilisable pendant quinze minutes.</p>'
        else:
            body += '<h1>Votre assistant se prépare.</h1><p class="intro">Gardez cette page ouverte. Elle suit les vérifications et le démarrage du service.</p>'
        body += '<ul class="checks"><li><span class="status ok" aria-hidden="true">✓</span><div>Telegram associé<small>Votre compte personnel est enregistré.</small></div></li>'
        labels = {"engine": "Moteur installé", "auth": "Compte connecté", "telegram": "Connexion Telegram", "workspace": "Dossier de rangement", "model": "Modèle testé"}
        for key, check in wizard.checks.items():
            if key not in labels and check.status not in {"error", "running"}:
                continue
            status = check.status
            css = "error-state" if status == "error" else status
            mark = "✓" if status == "ok" else ("!" if status == "error" else "")
            body += f'<li><span class="status {css}" aria-hidden="true">{mark}</span><div>{labels.get(key, "Vérification locale")}<small>{e(check.message)}</small></div></li>'
        state = wizard.service_state
        css = "error-state" if state == "error" else state
        mark = "✓" if state == "ok" else ("!" if state == "error" else "")
        service_text = {"pending": "Après la réussite des vérifications.", "running": "Démarrage en cours…", "ok": "L’assistant tourne en arrière-plan.", "error": "Le service n’a pas confirmé son démarrage."}[state]
        body += f'<li><span class="status {css}" aria-hidden="true">{mark}</span><div>Service démarré<small>{service_text}</small></div></li></ul>'
        if phase == "blocked":
            body += form("retry", '<button class="primary">Réessayer l’étape restante</button>')
            body += form("edit-config", '<button class="secondary primary">Modifier mes réglages</button>')
        elif phase == "ready":
            body += f'<a class="button primary" href="https://t.me/{e(wizard.bot_username)}" target="_blank" rel="noreferrer noopener">Écrire à @{e(wizard.bot_username)}</a>'
            body += '<div class="note"><p>Pour un premier essai, envoyez :</p><p>« Crée bienvenue.txt dans mon dossier de rangement avec une phrase de présentation, puis envoie-moi ce fichier. »</p></div>'
            body += '<p class="hint">Ce fichier sera créé à votre demande. Le diagnostic a utilisé un autre fichier temporaire.</p>'
            body += form("finish", '<button class="secondary primary">Terminer l’installation</button>')
    import time
    refresh = phase in {"authenticating", "validating", "pairing", "diagnostics", "starting"}
    refresh = refresh or (phase == "auth" and time.monotonic() < wizard.auth_watch_deadline)
    return page(body, phase=phase, provider=wizard.provider, refresh=refresh)
