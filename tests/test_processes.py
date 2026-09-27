"""Process isolation tests; all subprocesses and files belong to a temp folder."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from vibe_claw_light import processes
from vibe_claw_light.storage import FileLock, is_locked


PROCESS_HELPER = r'''
from pathlib import Path
import signal
import subprocess
import sys
import time
from vibe_claw_light.storage import FileLock

root, mode = Path(sys.argv[1]), sys.argv[2]
root.mkdir(parents=True, exist_ok=True)
if mode == "hold":
    if (root / "ignore-term").exists():
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with FileLock(root / "alive.lock"):
        (root / "ready").touch()
        time.sleep(30)
else:
    # The test attaches the Windows job before allowing descendants to start.
    deadline = time.monotonic() + 10
    (root / "parent-ready").touch()
    while not (root / "spawn-child").exists():
        if time.monotonic() > deadline:
            sys.exit(10)
        time.sleep(0.01)
    child_root = root / "child"
    child_root.mkdir(exist_ok=True)
    if mode == "parent-exits":
        (child_root / "ignore-term").touch()
    child = subprocess.Popen(
        [sys.executable, __file__, str(child_root), "hold"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    (root / "child.pid").write_text(str(child.pid), encoding="utf-8")
    while not (child_root / "ready").exists():
        if time.monotonic() > deadline:
            sys.exit(11)
        time.sleep(0.01)
    if mode != "parent-exits":
        time.sleep(30)
'''


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-process-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.helper = self.root / "helper.py"
        self.helper.write_text(PROCESS_HELPER, encoding="utf-8")

    def cleanup_process(self, proc, job, root):
        if job is not None:
            job.close()
        elif os.name != "nt":
            # This process group was created by this test with start_new_session.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif proc.poll() is None:
            processes.stop_tree(proc, grace=0.1)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for marker in (root / "alive.lock", root / "child" / "alive.lock"):
            if marker.exists():
                wait_until(lambda: not is_locked(marker), timeout=5)

    def spawn(self, name, mode="hold"):
        root = self.root / name
        root.mkdir()
        env = processes.child_environment(root)
        source = str(Path(processes.__file__).resolve().parents[1])
        env["PYTHONPATH"] = source + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        proc = subprocess.Popen(
            [sys.executable, str(self.helper), str(root), mode],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, **processes.spawn_options(),
        )
        job = None
        try:
            if os.name == "nt":
                job = processes.WindowsJob(proc)
        finally:
            self.addCleanup(self.cleanup_process, proc, job, root)
        marker = "ready" if mode == "hold" else "parent-ready"
        self.assertTrue(wait_until(lambda: (root / marker).exists()), "Helper failed to become ready")
        if mode != "hold":
            (root / "spawn-child").touch()
            self.assertTrue(wait_until(lambda: (root / "child" / "ready").exists()),
                            "Descendant failed to become ready")
        return proc, job, root

    def test_child_environment_preserves_calling_instance_and_parent_environment(self):
        with patch.dict(os.environ, {
            "VIBE_CLAW_ROOT": "parent-instance", "CLAUDECODE": "1", "PYTHONUTF8": "0",
        }):
            env = processes.child_environment(self.root)
            self.assertEqual(env["VIBE_CLAW_ROOT"], "parent-instance")
            self.assertEqual(env["VIBE_LIGHT_ROOT"], str(self.root))
            self.assertEqual(env["PYTHONUTF8"], "1")
            self.assertEqual(env["PYTHONIOENCODING"], "utf-8")
            self.assertNotIn("CLAUDECODE", env)
            self.assertEqual(os.environ["CLAUDECODE"], "1")
            self.assertEqual(os.environ["PYTHONUTF8"], "0")

    def test_stop_tree_terminates_only_its_own_parent_and_descendant(self):
        unrelated, _, other_root = self.spawn("unrelated")
        parent, _, root = self.spawn("owned", "parent-waits")
        self.assertTrue(is_locked(root / "child" / "alive.lock"))
        processes.stop_tree(parent, grace=0.2)
        self.assertIsNotNone(parent.poll())
        self.assertTrue(wait_until(lambda: not is_locked(root / "child" / "alive.lock")),
                        "The owned descendant survived stop_tree")
        self.assertIsNone(unrelated.poll())
        self.assertTrue(is_locked(other_root / "alive.lock"))

    def test_descendant_is_cleaned_up_when_parent_has_already_exited(self):
        unrelated, _, other_root = self.spawn("unrelated")
        parent, job, root = self.spawn("exited-parent", "parent-exits")
        self.assertEqual(parent.wait(timeout=5), 0)
        self.assertTrue(is_locked(root / "child" / "alive.lock"))
        if job is not None:
            job.close()
            job.close()  # Cleanup is allowed to call close again.
        else:
            processes.stop_tree(parent, grace=0.1)
        self.assertTrue(wait_until(lambda: not is_locked(root / "child" / "alive.lock"), timeout=2),
                        "A descendant ignoring SIGTERM survived after its parent exited")
        self.assertIsNone(unrelated.poll())
        self.assertTrue(is_locked(other_root / "alive.lock"))

    def test_file_lock_rejects_another_instance_and_releases_after_exit(self):
        proc, _, root = self.spawn("lock-holder")
        lock_path = root / "alive.lock"
        contender = FileLock(lock_path)
        with self.assertRaises(RuntimeError):
            contender.acquire()
        self.assertIsNone(contender.stream)
        self.assertTrue(is_locked(lock_path))
        with FileLock(self.root / "other-instance.lock"):
            self.assertTrue(is_locked(lock_path))
        processes.stop_tree(proc, grace=0.2)
        with FileLock(lock_path):
            self.assertTrue(is_locked(lock_path))
        self.assertFalse(is_locked(lock_path))


class WindowsJobContractTests(unittest.TestCase):
    """Validate handle cleanup on every platform; real jobs run above on Windows."""

    def fake_api(self):
        api = MagicMock()
        api.CreateJobObjectW.return_value = 123
        api.SetInformationJobObject.return_value = 1
        api.AssignProcessToJobObject.return_value = 1
        return api

    def test_job_owns_descendants_and_closes_handle_once(self):
        api = self.fake_api()
        with patch.object(ctypes, "WinDLL", return_value=api, create=True):
            job = processes.WindowsJob(SimpleNamespace(_handle=456))
        limits = api.SetInformationJobObject.call_args.args[2]._obj
        self.assertTrue(limits.BasicLimitInformation.LimitFlags & 0x2000)
        api.AssignProcessToJobObject.assert_called_once_with(123, 456)
        job.close()
        job.close()
        api.CloseHandle.assert_called_once_with(123)

    def test_failed_setup_never_leaks_a_job_handle(self):
        for failing_call in ("CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject"):
            with self.subTest(failing_call=failing_call):
                api = self.fake_api()
                getattr(api, failing_call).return_value = 0
                with patch.object(ctypes, "WinDLL", return_value=api, create=True), \
                     patch.object(ctypes, "get_last_error", return_value=5, create=True):
                    with self.assertRaises(OSError):
                        processes.WindowsJob(SimpleNamespace(_handle=456))
                if failing_call == "CreateJobObjectW":
                    api.CloseHandle.assert_not_called()
                else:
                    api.CloseHandle.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
