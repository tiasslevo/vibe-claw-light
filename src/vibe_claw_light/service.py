"""Superviseur portable : un seul service, pas de systemd ni de droits admin."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .processes import child_environment, spawn_options, stop_tree
from .storage import FileLock, atomic_write, is_locked, read_json, write_json


def launch_env(root: Path):
    env = child_environment(root)
    source = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = source + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def command(root: Path, action: str) -> list[str]:
    return [sys.executable, "-m", "vibe_claw_light", "--root", str(root), action]


def status(root: Path) -> dict:
    active = is_locked(root / "data" / "service.lock")
    record = read_json(root / "data" / "service.json", {}) if active else {}
    ready = (active and is_locked(root / "data" / "worker.lock")
             and bool(read_json(root / "data" / "worker.ready.json", {})))
    return {**(record or {}), "running": active, "ready": ready}


def start(root: Path, cancel: threading.Event | None = None) -> int:
    from .config import load_config
    cancel = cancel or threading.Event()
    if cancel.is_set():
        print("Démarrage annulé.")
        return 1
    config = load_config(root)
    if not config.owner_id or not config.chat_id:
        raise ValueError("Associez Telegram avec setup avant le démarrage.")
    current = status(root)
    if current["running"] and current["ready"]:
        print("L'agent est déjà lancé.")
        return 0
    if current["running"]:
        print("Le service est actif mais son démarrage n’est pas confirmé. Consultez status ou arrêtez cette instance avant de réessayer.")
        return 1
    logs = root / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "service.log"
    if log_path.exists() and log_path.stat().st_size > 2_000_000:
        log_path.replace(logs / "service.previous.log")
    with log_path.open("ab") as log:
        options = spawn_options()
        if os.name == "nt":
            options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        proc = subprocess.Popen(command(root, "run"), cwd=root, env=launch_env(root),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
    ready = False
    try:
        for _ in range(300):
            if cancel.is_set():
                print("Démarrage annulé ; fermeture du processus lancé par cette tentative.")
                return 1
            current = status(root)
            if cancel.is_set():
                continue
            if current["running"] and current["ready"]:
                ready = True
                print("L'agent tourne en arrière-plan. Vous pouvez fermer cette fenêtre.")
                print("Pour l'arrêter : python run.py stop")
                return 0
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        print("Le démarrage n'a pas abouti. Consultez data/logs/service.log, puis doctor.")
        return 1
    finally:
        if not ready:
            # Le superviseur doit pouvoir attendre son worker (25 s), puis
            # nettoyer ses fichiers avant d'être terminé de force. Ne viser
            # que le Popen de cette tentative, jamais un service préexistant.
            stop_tree(proc, grace=30)


def stop(root: Path) -> int:
    if not status(root)["running"]:
        print("L'agent est déjà arrêté.")
        return 0
    atomic_write(root / "data" / "stop.request", "stop\n")
    for _ in range(100):
        if not status(root)["running"]:
            print("Agent arrêté. Mémoire et conversation conservées.")
            return 0
        time.sleep(0.2)
    print("Arrêt demandé ; une tâche est encore en cours de fermeture. Consultez status.")
    return 1


def supervise(root: Path) -> int:
    data = root / "data"
    shutdown = threading.Event()
    if threading.current_thread() is threading.main_thread():
        def request_stop(signum, frame):
            # Un superviseur concurrent peut recevoir SIGTERM avant de gagner
            # le verrou : il ne doit pas arrêter l'instance qui le possède.
            shutdown.set()
        signal.signal(signal.SIGTERM, request_stop)
    with FileLock(data / "service.lock"):
        def stopping():
            if shutdown.is_set():
                atomic_write(data / "stop.request", "stop\n")
            return (data / "stop.request").exists()

        (data / "stop.request").unlink(missing_ok=True)
        write_json(data / "service.json", {
            "pid": os.getpid(), "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        proc = None
        failures = 0
        try:
            while not stopping():
                (data / "worker.ready.json").unlink(missing_ok=True)
                proc = subprocess.Popen(command(root, "_worker"), cwd=root, env=launch_env(root),
                                        stdin=subprocess.DEVNULL, **spawn_options())
                while proc.poll() is None:
                    if stopping():
                        try:
                            proc.wait(timeout=25)
                        except subprocess.TimeoutExpired:
                            stop_tree(proc)
                        return 0
                    time.sleep(0.2)
                code = proc.returncode
                if code == 75:
                    failures = 0
                    continue
                if code == 0:
                    return 0
                failures += 1
                if failures >= 3:
                    print("Arrêt après trois échecs. Corrigez la configuration puis relancez start.", flush=True)
                    return 1
                print(f"Le worker s'est arrêté (code {code}). Nouvelle tentative.", flush=True)
                for _ in range(10 * failures):
                    if stopping():
                        return 0
                    time.sleep(0.2)
            return 0
        except KeyboardInterrupt:
            atomic_write(data / "stop.request", "stop\n")
            if proc is not None:
                try:
                    proc.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    stop_tree(proc)
            return 0
        finally:
            if proc is not None and proc.poll() is None:
                stop_tree(proc)
            (data / "service.json").unlink(missing_ok=True)
            (data / "worker.ready.json").unlink(missing_ok=True)
            (data / "stop.request").unlink(missing_ok=True)
