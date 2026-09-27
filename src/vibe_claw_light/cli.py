from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import sys

from . import __version__
from .config import load_config, save_config
from .providers import auth_status, find_cli
from .storage import is_locked


def doctor(root: Path, live: bool = False) -> int:
    from .diagnostics import run_diagnostics
    print(f"Vibe Claw Light {__version__} · {platform.system()} · Python {platform.python_version()}")
    def report(check):
        label = {"ok": "OK", "error": "ERREUR", "running": "EN COURS", "skipped": "NON TESTÉ"}[check.status]
        print(label + " · " + check.message, flush=True)
    result = run_diagnostics(root, live=live, report=report)
    print("Diagnostic réussi. Le démarrage du service est une étape distincte." if result.ok
          else "Configuration à terminer. Corrigez l'étape signalée puis reprenez le diagnostic.")
    return 0 if result.ok else 1


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
                print("Agent en cours, démarrage confirmé." if state.get("ready") else
                      ("Service actif, démarrage de l’agent non confirmé." if state["running"] else "Agent arrêté."))
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
            from .context import current_snapshot
            current_snapshot(load_config(root, require_token=False))
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
