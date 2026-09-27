from __future__ import annotations

import argparse
from dataclasses import replace
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from . import __version__
from .config import load_config, save_config
from .providers import ProviderRunner, auth_status, executable_command, find_cli
from .storage import is_locked


def doctor(root: Path, live: bool = False) -> int:
    from .telegram import Telegram
    config = load_config(root, require_token=False)
    print(f"Vibe Claw Light {__version__} · {platform.system()} · Python {platform.python_version()}")
    checks = []
    executable = find_cli(config.provider, config.executable_hint)
    checks.append(bool(executable))
    print(("OK" if executable else "ERREUR") + f" · moteur {config.provider} détecté")
    if executable:
        try:
            version = subprocess.run(executable_command(executable) + ["--version"],
                                     capture_output=True, text=True, encoding="utf-8",
                                     timeout=20, errors="replace")
            print("Version : " + (version.stdout.strip()[:100] or "inconnue"))
            checks.append(version.returncode == 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            checks.append(False)
            print("ERREUR · exécutable natif non utilisable")
    authenticated, message = auth_status(config.provider, executable)
    checks.append(authenticated)
    print(("OK" if authenticated else "ERREUR") + " · " + message)
    paired = bool(config.telegram_token and config.owner_id and config.chat_id == config.owner_id)
    checks.append(paired)
    print(("OK" if paired else "ERREUR") + " · association Telegram privée")
    if config.telegram_token:
        try:
            telegram = Telegram(config.telegram_token)
            me = telegram.get_me()
            webhook = telegram.request("getWebhookInfo")
            checks.append(not bool(webhook.get("url")))
            print(f"OK · bot @{me['username']}" if not webhook.get("url") else "ERREUR · bot déjà associé à un webhook")
        except Exception:
            checks.append(False)
            print("ERREUR · connexion Telegram ou token")
    try:
        config.workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=config.workspace) as probe:
            probe.write(b"ok")
        print(f"OK · dossier accessible : {config.workspace}")
    except OSError:
        checks.append(False)
        print("ERREUR · dossier de travail inaccessible")
    from .memory import MemoryStore
    try:
        healthy, note = MemoryStore(root).health()
        checks.append(healthy)
        print(("OK" if healthy else "ERREUR") + " · " + note)
    except (OSError, ValueError):
        checks.append(False)
        print("ERREUR · mémoire illisible ; original conservé dans memory/")
    try:
        from .runtime import validate_state
        from .storage import read_json
        state = read_json(config.data / "state.json", None)
        if state is not None:
            validate_state(state)
        checks.append(True)
        print("OK · état des conversations")
    except (OSError, ValueError):
        checks.append(False)
        print("ERREUR · état local illisible ; conserver et faire réparer data/state.json")
    if live and executable and authenticated:
        print("Vérification réelle du moteur : création d'un fichier temporaire (utilise votre quota).", flush=True)
        diagnostic_root = config.data / "diagnostics"
        diagnostic_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="test-", dir=diagnostic_root) as directory:
            path = Path(directory) / "verification.txt"
            result = ProviderRunner(replace(config, timeout_seconds=150)).run(
                f"Test de fonctionnement autorisé. Crée uniquement le fichier {path} "
                "avec le contenu exact VIBE_LIGHT_OK. Ne lis aucun autre fichier, "
                "n'utilise aucun plugin ni recherche. Réponds ensuite VIBE_LIGHT_OK."
            )
            worked = not result.error and path.exists() and path.read_text(encoding="utf-8").strip() == "VIBE_LIGHT_OK"
            checks.append(worked)
            print("OK · le moteur a créé le fichier demandé" if worked else "ERREUR · " + (result.error or "fichier de vérification absent ou incorrect"))
    elif live:
        checks.append(False)
    print("Diagnostic réussi." if all(checks) else "Configuration à terminer. Relancez setup après correction.")
    return 0 if all(checks) else 1


def main(argv: list[str] | None = None, default_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Votre assistant personnel Telegram.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", type=Path, default=default_root or Path(os.environ.get("VIBE_LIGHT_ROOT", str(Path.cwd()))))
    commands = parser.add_subparsers(dest="action", required=True)
    setup = commands.add_parser("setup", help="Configurer dans un formulaire local.")
    setup.add_argument("--provider", choices=["codex", "claude"])
    check = commands.add_parser("doctor", help="Vérifier l'installation.")
    check.add_argument("--live", action="store_true", help="Tester une action réelle avec le moteur.")
    for action in ("start", "stop", "status", "run", "_worker", "memory"):
        commands.add_parser(action)
    forget = commands.add_parser("forget", help="Oublier une entrée personnelle.")
    forget.add_argument("key")
    switch = commands.add_parser("switch")
    switch.add_argument("provider", choices=["codex", "claude"])
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if args.action == "setup":
            from .onboarding import setup
            return setup(root, args.provider)
        if args.action == "doctor":
            return doctor(root, args.live)
        if args.action in {"start", "stop", "status", "run"}:
            from . import service
            if args.action == "status":
                state = service.status(root)
                print("Agent en cours." if state["running"] else "Agent arrêté.")
                return 0
            return getattr(service, "supervise" if args.action == "run" else args.action)(root)
        if args.action == "_worker":
            from .runtime import Bot
            return Bot(load_config(root)).run()
        if args.action in {"memory", "forget"}:
            from .memory import MemoryStore
            memory = MemoryStore(root)
            if args.action == "memory":
                print(memory.display())
                return 0
            if is_locked(root / "data" / "service.lock"):
                raise ValueError("Utilisez /forget dans Telegram ou arrêtez d'abord l'agent.")
            if not memory.forget(args.key):
                raise ValueError("Oubli non confirmé : clé invalide, déjà oubliée ou mémoire indisponible.")
            from .storage import read_json, write_json
            state_path = root / "data" / "state.json"
            state = read_json(state_path, None)
            if state:
                state["sessions"], state["queue"], state["active"] = {}, [], None
                write_json(state_path, state)
            print("Entrée oubliée. Les archives du fournisseur ne sont pas supprimées.")
            return 0
        if args.action == "switch":
            if is_locked(root / "data" / "service.lock"):
                raise ValueError("Utilisez /switch dans Telegram ou arrêtez d'abord l'agent.")
            config = load_config(root)
            hint = config.codex_bin if args.provider == "codex" else config.claude_bin
            ok, message = auth_status(args.provider, find_cli(args.provider, hint))
            if not ok:
                raise ValueError(message)
            save_config(root, {"PROVIDER": args.provider})
            print(f"Moteur sélectionné : {args.provider}. Votre mémoire est conservée.")
            return 0
    except KeyboardInterrupt:
        print("\nOpération interrompue.")
        return 130
    except Exception as exc:
        # Les clients réseau et les providers fournissent des erreurs déjà nettoyées.
        from .providers import safe_error
        try:
            message = safe_error(str(exc), load_config(root, require_token=False))
        except Exception:
            message = type(exc).__name__
        print("Erreur : " + message, file=sys.stderr)
        return 1
    return 0
