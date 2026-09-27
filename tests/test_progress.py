"""Progression cumulée et bornée, aucun accès Telegram réel."""
import unittest
from unittest.mock import Mock

from vibe_claw_light.progress import Activity, ToolProgress, activities
from vibe_claw_light.telegram import TelegramError


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.send = Mock(return_value=71)
        self.edit = Mock()
        self.progress = ToolProgress(self.send, self.edit, clock=lambda: self.now)

    def test_no_automatic_acknowledgment_and_no_raw_status_strings(self):
        self.progress.record("Je m’en occupe SECRET")
        self.progress.record(Activity("SECRET_TOOL", "secret"))
        self.progress.flush(force=True)
        self.send.assert_not_called()

    def test_groups_are_preserved_and_start_complete_are_counted_once(self):
        for event in (Activity("read", "one"), Activity("read", "one"),
                      Activity("write", "two"), Activity("read", "three")):
            self.progress.record(event)
        self.progress.flush()
        text = self.send.call_args.args[0]
        self.assertIn("📖 Lecture de fichiers × 2", text)
        self.assertIn("✏️ Modification de fichiers", text)
        self.assertLess(text.index("Lecture"), text.index("Modification"))
        self.assertNotIn("one", text)

    def test_edits_are_coalesced_and_final_flush_keeps_the_same_message(self):
        self.progress.record(Activity("read", "one"))
        self.progress.flush()
        self.progress.record(Activity("write", "two"))
        self.progress.flush()
        self.edit.assert_not_called()
        self.now += 2
        self.progress.flush()
        self.assertEqual(self.edit.call_args.args[0], 71)
        self.progress.record(Activity("web", "three"))
        self.progress.flush(force=True)
        self.send.assert_called_once()
        self.assertEqual(self.edit.call_count, 2)
        self.assertIn("Recherche sur Internet", self.edit.call_args.args[1])

    def test_uncertain_first_delivery_is_never_retried(self):
        self.send.side_effect = TelegramError(0, category="network")
        self.progress.record(Activity("command", "one"))
        self.progress.flush()
        self.now += 10
        self.progress.flush(force=True)
        self.send.assert_called_once()

    def test_edit_failure_keeps_id_and_rate_limit_is_respected_even_at_finish(self):
        self.progress.record(Activity("read", "one"))
        self.progress.flush()
        self.progress.record(Activity("command", "two"))
        self.now += 2
        self.edit.side_effect = TelegramError(429, retry_after=10)
        self.progress.flush()
        self.now += 5
        self.progress.flush(force=True)
        self.edit.assert_called_once()
        self.now += 5
        self.edit.side_effect = None
        self.progress.flush()
        self.assertEqual(self.edit.call_count, 2)
        self.send.assert_called_once()
        self.assertEqual(self.edit.call_args.args[0], 71)

    def test_irrelevant_or_malformed_events_do_not_expose_tool_data(self):
        for provider in ("codex", "claude"):
            for event in ({}, {"type": "assistant", "message": "SECRET"},
                          {"type": "item.completed", "item": "SECRET"},
                          {"type": "stream_event", "event": {"type": "content_block_start", "content_block": "SECRET"}}):
                self.assertEqual(list(activities(provider, event)), [])


if __name__ == "__main__":
    unittest.main()
