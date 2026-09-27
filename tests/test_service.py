"""Exercise the supervisor with temporary fake workers, never Telegram or a CLI."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from vibe_claw_light import service
from vibe_claw_light.processes import stop_tree
from vibe_claw_light.storage import FileLock, atomic_write, is_locked, read_json, write_json


SERVICE_HELPER = r'''
from pathlib import Path
import os
import sys
import time
from vibe_claw_light import service
from vibe_claw_light.storage import FileLock, atomic_write, read_json, write_json

root, action = Path(sys.argv[1]), sys.argv[2]
if action == "run":
    service.command = lambda folder, verb: [sys.executable, __file__, str(folder), verb]
    sys.exit(service.supervise(root))
data = root / "data"
with FileLock(data / "worker.lock"):
    starts = read_json(data / "starts.json", 0) + 1
    write_json(data / "starts.json", starts)
    write_json(data / "worker.json", {"pid": os.getpid()})
    if not (data / "withhold-ready").exists():
        write_json(data / "worker.ready.json", {"pid": os.getpid()})
    deadline = time.monotonic() + 30
    while not (data / "stop.request").exists():
        if (data / "reload.request").exists():
            (data / "reload.request").unlink()
            sys.exit(75)
        if time.monotonic() > deadline:
            sys.exit(12)
        time.sleep(0.02)
    if (data / "slow-close").exists():
        time.sleep(0.35)
    atomic_write(data / "worker.closed", "closed\n")
'''


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-service-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.helper = self.root / "fake_service.py"
        self.helper.write_text(SERVICE_HELPER, encoding="utf-8")
        self.output = io.StringIO()
        self.output_context = redirect_stdout(self.output)
        self.output_context.__enter__()
        self.addCleanup(self.output_context.__exit__, None, None, None)
        self.original_popen = subprocess.Popen
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))

    def root_folder(self, name="instance"):
        root = self.root / name
        root.mkdir()
        return root

    def command(self, root, action):
        return [sys.executable, str(self.helper), str(root), action]

    def cleanup_service(self, root, proc):
        if proc.poll() is None:
            atomic_write(root / "data" / "stop.request", "stop\n")
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stop_tree(proc, grace=0.2)
        proc.wait(timeout=5)

    def start_fake(self, root, cancel=None):
        launched = []

        def spawn(*args, **kwargs):
            proc = self.original_popen(*args, **kwargs)
            launched.append(proc)
            self.addCleanup(self.cleanup_service, root, proc)
            return proc

        config = SimpleNamespace(owner_id=42, chat_id=42)
        with patch("vibe_claw_light.config.load_config", return_value=config), \
             patch.object(service, "command", side_effect=self.command), \
             patch.object(service.subprocess, "Popen", side_effect=spawn) as popen:
            result = service.start(root, cancel=cancel)
        return result, launched, popen

    def test_start_detaches_supervisor_and_stop_preserves_local_data(self):
        root = self.root_folder()
        write_json(root / "data" / "session.json", {"conversation": "fixture"})
        atomic_write(root / "memory" / "notes.md", "A durable preference.\n")
        result, launched, popen = self.start_fake(root)
        self.assertEqual(result, 0)
        self.assertEqual(len(launched), 1)
        self.assertTrue(wait_until(lambda: is_locked(root / "data" / "worker.lock")))
        self.assertTrue(service.status(root)["running"])
        self.assertTrue(service.status(root)["ready"])
        # Some Python distributions keep an intermediate launcher process.
        self.assertIsInstance(service.status(root)["pid"], int)
        self.assertIsNone(launched[0].poll())
        options = popen.call_args.kwargs
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        if os.name == "nt":
            self.assertTrue(options["creationflags"] & subprocess.DETACHED_PROCESS)
            self.assertTrue(options["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertTrue(options["start_new_session"])
        self.assertEqual(service.stop(root), 0)
        self.assertEqual(launched[0].wait(timeout=5), 0)
        self.assertFalse(service.status(root)["running"])
        self.assertFalse(is_locked(root / "data" / "worker.lock"))
        self.assertFalse((root / "data" / "service.json").exists())
        self.assertFalse((root / "data" / "stop.request").exists())
        self.assertEqual(read_json(root / "data" / "session.json"), {"conversation": "fixture"})
        self.assertEqual((root / "memory" / "notes.md").read_text(encoding="utf-8"),
                         "A durable preference.\n")

    def test_reload_restarts_worker_without_restarting_supervisor(self):
        root = self.root_folder()
        result, launched, _ = self.start_fake(root)
        self.assertEqual(result, 0)
        self.assertTrue(wait_until(lambda: (root / "data" / "worker.json").exists()))
        first_worker = read_json(root / "data" / "worker.json")["pid"]
        supervisor_pid = service.status(root)["pid"]
        atomic_write(root / "data" / "reload.request", "reload\n")
        self.assertTrue(wait_until(lambda: read_json(root / "data" / "starts.json", 0) >= 2))
        self.assertTrue(wait_until(lambda: read_json(root / "data" / "worker.json", {}).get("pid")
                                  not in (None, first_worker)))
        self.assertEqual(service.status(root)["pid"], supervisor_pid)
        self.assertIsNone(launched[0].poll())
        self.assertEqual(service.stop(root), 0)

    def test_two_instances_are_independent_and_repeated_start_is_idempotent(self):
        root_a, root_b = self.root_folder("a"), self.root_folder("b")
        result_a, procs_a, _ = self.start_fake(root_a)
        result_b, procs_b, _ = self.start_fake(root_b)
        self.assertEqual((result_a, result_b), (0, 0))
        self.assertTrue(wait_until(lambda: is_locked(root_b / "data" / "worker.lock")))
        result_again, repeated, _ = self.start_fake(root_a)
        self.assertEqual(result_again, 0)
        self.assertEqual(repeated, [])
        self.assertEqual(service.stop(root_a), 0)
        self.assertEqual(procs_a[0].wait(timeout=5), 0)
        self.assertIsNone(procs_b[0].poll())
        self.assertTrue(service.status(root_b)["running"])
        self.assertTrue(is_locked(root_b / "data" / "worker.lock"))
        self.assertFalse((root_b / "data" / "stop.request").exists())
        self.assertEqual(service.stop(root_b), 0)

    def test_start_reports_a_supervisor_that_exits_before_ready(self):
        root = self.root_folder()
        config = SimpleNamespace(owner_id=42, chat_id=42)
        command = [sys.executable, "-c", "raise SystemExit(2)"]
        launched = []

        def spawn(*args, **kwargs):
            proc = self.original_popen(*args, **kwargs)
            launched.append(proc)
            self.addCleanup(self.cleanup_service, root, proc)
            return proc

        with patch("vibe_claw_light.config.load_config", return_value=config), \
             patch.object(service, "command", return_value=command), \
             patch.object(service.subprocess, "Popen", side_effect=spawn):
            self.assertEqual(service.start(root), 1)
        self.assertEqual(launched[0].wait(timeout=5), 2)
        self.assertFalse(service.status(root)["running"])

    def test_failed_start_cleans_up_an_unresponsive_supervisor(self):
        root = self.root_folder()
        config = SimpleNamespace(owner_id=42, chat_id=42)
        proc = Mock()
        proc.poll.return_value = None
        with patch("vibe_claw_light.config.load_config", return_value=config), \
             patch.object(service.subprocess, "Popen", return_value=proc), \
             patch.object(service, "status", return_value={"running": False}), \
             patch.object(service.time, "sleep"), \
             patch.object(service, "stop_tree") as stop:
            self.assertEqual(service.start(root), 1)
        stop.assert_called_once_with(proc, grace=30)

    def test_cancelled_start_does_not_launch_or_stop_a_preexisting_instance(self):
        root = self.root_folder()
        cancel = threading.Event()
        cancel.set()
        with patch.object(service.subprocess, "Popen") as popen, \
                patch.object(service, "stop_tree") as stop, \
                patch.object(service, "status", return_value={"running": True, "ready": True}):
            self.assertEqual(service.start(root, cancel=cancel), 1)
        popen.assert_not_called()
        stop.assert_not_called()
        self.assertFalse((root / "data" / "stop.request").exists())

    def test_cancel_after_spawn_stops_only_the_owned_process(self):
        root = self.root_folder()
        cancel = threading.Event()
        config = SimpleNamespace(owner_id=42, chat_id=42)
        proc = Mock()

        def spawn(*args, **kwargs):
            cancel.set()
            return proc

        with patch("vibe_claw_light.config.load_config", return_value=config), \
                patch.object(service.subprocess, "Popen", side_effect=spawn), \
                patch.object(service, "status", return_value={"running": False, "ready": False}), \
                patch.object(service, "stop_tree") as stop:
            self.assertEqual(service.start(root, cancel=cancel), 1)
        stop.assert_called_once_with(proc, grace=30)
        self.assertFalse((root / "data" / "stop.request").exists())

    @unittest.skipIf(os.name == "nt", "SIGTERM et arrêt coopératif POSIX")
    def test_cancel_waits_for_the_separate_worker_to_close(self):
        root = self.root_folder()
        atomic_write(root / "data" / "withhold-ready", "fixture\n")
        atomic_write(root / "data" / "slow-close", "fixture\n")
        cancel = threading.Event()

        def cancel_after_worker_starts():
            wait_until(lambda: (root / "data" / "worker.json").exists())
            cancel.set()

        thread = threading.Thread(target=cancel_after_worker_starts, daemon=True)
        thread.start()
        result, launched, _ = self.start_fake(root, cancel=cancel)
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, 1)
        self.assertEqual(launched[0].wait(timeout=5), 0)
        self.assertFalse(is_locked(root / "data" / "worker.lock"))
        self.assertEqual((root / "data" / "worker.closed").read_text(), "closed\n")
        self.assertEqual(service.status(root), {"running": False, "ready": False})

    def test_status_ignores_stale_pid_records_and_uses_the_lock(self):
        root = self.root_folder()
        write_json(root / "data" / "service.json", {"pid": 12345})
        self.assertEqual(service.status(root), {"running": False, "ready": False})
        with FileLock(root / "data" / "service.lock"):
            self.assertEqual(service.status(root), {"running": True, "ready": False, "pid": 12345})
        self.assertEqual(service.stop(root), 0)
        self.assertFalse((root / "data" / "stop.request").exists())

    def test_supervise_refuses_a_second_owner_without_spawning_or_erasing_state(self):
        root = self.root_folder()
        write_json(root / "data" / "service.json", {"pid": 12345})
        with FileLock(root / "data" / "service.lock"), \
             patch.object(service.subprocess, "Popen") as popen:
            with self.assertRaises(RuntimeError):
                service.supervise(root)
        popen.assert_not_called()
        self.assertEqual(read_json(root / "data" / "service.json"), {"pid": 12345})

    def test_losing_supervisor_signal_cannot_stop_the_current_owner(self):
        root = self.root_folder()
        write_json(root / "data" / "service.json", {"pid": 12345})

        def lock_after_signal(path):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return FileLock(path)

        with FileLock(root / "data" / "service.lock"), \
                patch.object(service, "FileLock", side_effect=lock_after_signal), \
                patch.object(service.subprocess, "Popen") as popen:
            with self.assertRaises(RuntimeError):
                service.supervise(root)
        popen.assert_not_called()
        self.assertEqual(read_json(root / "data" / "service.json"), {"pid": 12345})
        self.assertFalse((root / "data" / "stop.request").exists())

    def completed_workers(self, root, codes):
        workers = []
        for code in codes:
            proc = Mock()
            proc.poll.return_value = code
            proc.returncode = code
            workers.append(proc)
        with patch.object(service.subprocess, "Popen", side_effect=workers) as popen, \
             patch.object(service.time, "sleep"):
            result = service.supervise(root)
        self.assertFalse(service.status(root)["running"])
        self.assertFalse((root / "data" / "service.json").exists())
        self.assertFalse((root / "data" / "stop.request").exists())
        return result, popen.call_count

    def test_three_failed_workers_stop_the_supervisor(self):
        self.assertEqual(self.completed_workers(self.root_folder(), [2, 2, 2]), (1, 3))

    def test_reload_exit_75_resets_the_consecutive_failure_count(self):
        self.assertEqual(self.completed_workers(self.root_folder(), [2, 2, 75, 2, 2, 0]), (0, 6))

    def test_stale_stop_request_does_not_cancel_a_fresh_launch(self):
        root = self.root_folder()
        atomic_write(root / "data" / "stop.request", "stale\n")
        self.assertEqual(self.completed_workers(root, [0]), (0, 1))


if __name__ == "__main__":
    unittest.main()
