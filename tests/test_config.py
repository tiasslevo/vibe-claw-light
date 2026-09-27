from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibe_claw_light.config import load_config, read_values, save_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_new_install_has_personal_access_and_simple_storage(self):
        with patch("vibe_claw_light.config.Path.home", return_value=self.root / "person"):
            config = load_config(self.root, require_token=False)
            self.assertEqual(config.workspace, self.root / "person" / "Documents" / "MonAssistant")
            self.assertTrue(config.shell_enabled)
            self.assertTrue(config.network_enabled)
            self.assertIn(self.root / "person", config.allowed_roots)

    def test_existing_install_never_gets_broader_permissions_on_upgrade(self):
        (self.root / "config.env").write_text('WORKSPACE="ancien"\nALLOW_SHELL="0"\n', encoding="utf-8")
        config = load_config(self.root, require_token=False)
        self.assertEqual(config.access_mode, "workspace")
        self.assertFalse(config.shell_enabled)
        self.assertFalse(config.network_enabled)
        self.assertEqual(config.workspace, self.root / "ancien")
        save_config(self.root, {"AGENT_NAME": "Nouveau nom"})
        again = load_config(self.root, require_token=False)
        self.assertEqual(again.allowed_roots, config.allowed_roots)
        self.assertEqual(again.access_mode, "workspace")

    def test_extra_project_directory_is_independent_from_storage(self):
        extra = self.root / "ailleurs"
        save_config(self.root, {"ACCESS_MODE": "workspace", "EXTRA_DIRS": json.dumps([str(extra)])})
        config = load_config(self.root, require_token=False)
        self.assertIn(extra, config.allowed_roots)
        self.assertNotEqual(extra, config.workspace)

    def test_invalid_directory_lists_are_not_interpreted_as_shell(self):
        for raw in ('not-json', '{}', '["relative"]', '[42]', '[""]'):
            save_config(self.root, {"EXTRA_DIRS": raw})
            with self.assertRaisesRegex(ValueError, "EXTRA_DIRS"):
                load_config(self.root, require_token=False)


if __name__ == "__main__":
    unittest.main()
