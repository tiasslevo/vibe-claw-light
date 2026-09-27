"""Atomic private storage and instance-local configuration."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibe_claw_light.config import load_config, read_values, save_config
from vibe_claw_light.storage import FileLock, atomic_write, is_locked, read_json, write_json


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_unicode_roundtrip_and_missing_default(self):
        path = self.root / "data" / "state.json"
        self.assertEqual(read_json(path, {"empty": True}), {"empty": True})
        value = {"name": "Zoé", "task": "Résumé 📚", "path": "C:\\Users\\Zoé\\Documents"}
        write_json(path, value)
        self.assertEqual(read_json(path), value)

    def test_failed_replace_keeps_original_and_removes_temporary_file(self):
        path = self.root / "state.json"
        write_json(path, {"offset": 4})
        with patch("vibe_claw_light.storage.os.replace", side_effect=PermissionError("file locked")):
            with self.assertRaises(PermissionError):
                write_json(path, {"offset": 5})
        self.assertEqual(read_json(path), {"offset": 4})
        self.assertEqual([item.name for item in self.root.iterdir()], ["state.json"])

    def test_corrupt_json_is_not_mistaken_for_missing_state(self):
        path = self.root / "state.json"
        atomic_write(path, "{corrupt")
        with self.assertRaises(json.JSONDecodeError):
            read_json(path, {})
        self.assertEqual(path.read_text(encoding="utf-8"), "{corrupt")

    def test_os_lock_is_exclusive_and_stale_file_is_not_a_live_lock(self):
        path = self.root / "worker.lock"
        with FileLock(path):
            self.assertTrue(is_locked(path))
            with self.assertRaises(RuntimeError):
                FileLock(path).acquire()
        self.assertTrue(path.exists())
        self.assertFalse(is_locked(path))
        with FileLock(path):
            self.assertTrue(is_locked(path))

    def test_config_isolation_and_quoted_values(self):
        roots = [self.root / "first", self.root / "second"]
        for root, name, token in ((roots[0], "Zoé\nEquipe", "first-token"), (roots[1], "Autre", "second-token")):
            save_config(root, {"AGENT_NAME": name, "TELEGRAM_TOKEN": token})
        with patch.dict(os.environ, {"TELEGRAM_TOKEN": "ambient-token", "PROVIDER": "claude", "VIBE_CLAW_ROOT": "/private/original"}):
            first = load_config(roots[0])
            second = load_config(roots[1])
        self.assertEqual(first.telegram_token, "first-token")
        self.assertEqual(second.telegram_token, "second-token")
        self.assertEqual(first.name, "Zoé\nEquipe")
        self.assertEqual(first.provider, "codex")
        self.assertEqual(first.workspace, Path.home() / "Documents" / "MonAssistant")
        save_config(roots[0], {"PROVIDER": "claude"})
        self.assertEqual(read_values(roots[1])["PROVIDER"], "codex")
        self.assertEqual(read_values(roots[0])["TELEGRAM_TOKEN"], "first-token")

    def test_unknown_config_key_cannot_replace_original(self):
        save_config(self.root, {"AGENT_NAME": "Original"})
        before = (self.root / "config.env").read_bytes()
        with self.assertRaises(ValueError):
            save_config(self.root, {"UNKNOWN": "value"})
        self.assertEqual((self.root / "config.env").read_bytes(), before)

    def test_explicit_installation_root_takes_precedence_over_inherited_instance(self):
        from vibe_claw_light.cli import main

        first, second = self.root / "first", self.root / "second"
        with patch.dict(os.environ, {"VIBE_LIGHT_ROOT": str(first), "VIBE_CLAW_ROOT": "/original/private"}), \
             patch("vibe_claw_light.cli.doctor", return_value=0) as doctor:
            self.assertEqual(main(["doctor"], default_root=second), 0)
        self.assertEqual(doctor.call_args.args[0], second)


if __name__ == "__main__":
    unittest.main()
