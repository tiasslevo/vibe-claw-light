"""Owner authorization, durable ingestion and cancellation, without Telegram."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from vibe_claw_light.config import Config
from vibe_claw_light.context import current_snapshot, native_context
from vibe_claw_light.providers import Result
from vibe_claw_light.runtime import Bot, RELOAD
from vibe_claw_light.storage import FileLock, read_json, write_json


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.documents = []
        self.on_send = None

    def send(self, chat_id, text):
        if self.on_send:
            self.on_send(text)
        self.messages.append((chat_id, text))

    def send_document(self, chat_id, path):
        self.documents.append((chat_id, path))

    def download(self, file_id, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("Document externe", encoding="utf-8")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.config = Config(self.root, "codex", "Démo", "token-local-test", 123, 123, self.root / "workspace")
        self.config.workspace.mkdir()
        self.telegram = FakeTelegram()
        self.bot = Bot(self.config, self.telegram)
        self.bot.persist()

    def tearDown(self):
        self.bot.done.set()
        self.bot.cancel.set()
        self.bot.wake.set()
        self.temp.cleanup()

    def update(self, uid=1, text="Prépare les notes", **changes):
        message = {"chat": {"type": "private", "id": 123}, "from": {"id": 123, "is_bot": False}, "text": text}
        message.update(changes)
        return {"update_id": uid, "message": message}

    def disk(self):
        return read_json(self.bot.state_path)

    def run_once(self, result, sid="session_initial"):
        bot = self.bot

        class Runner:
            def run(self, prompt, session_id, cancel, on_session, on_progress):
                if sid:
                    on_session(sid)
                bot.done.set()
                return result

        bot.runner_factory = lambda config: Runner()
        bot.work()

    def test_only_private_owner_messages_can_queue_or_issue_commands(self):
        variants = [
            {"from": {"id": 999}},
            {"chat": {"type": "group", "id": 123}},
            {"chat": {"type": "private", "id": 999}},
            {"from": {"id": 123, "is_bot": True}},
        ]
        for uid, variant in enumerate(variants, 1):
            self.bot.ingest(self.update(uid, "/reload", **variant))
        self.assertFalse(self.bot.done.is_set())
        self.assertEqual(self.disk()["queue"], [])
        self.assertEqual(self.telegram.messages, [])
        self.bot.ingest(self.update(5))
        self.assertEqual([task["id"] for task in self.disk()["queue"]], [5])
        self.assertEqual(self.disk()["offset"], 6)

    def test_queue_and_offset_survive_restart_and_duplicate_updates(self):
        self.bot.ingest(self.update(40))
        self.bot.ingest(self.update(40))
        fresh = Bot(self.config, FakeTelegram())
        self.assertEqual(fresh.state["offset"], 41)
        self.assertEqual(len(fresh.state["queue"]), 1)
        self.assertEqual(fresh.state["queue"][0]["text"], "Prépare les notes")

    def test_reload_acknowledges_only_after_offset_is_durable(self):
        snapshots = []
        self.telegram.on_send = lambda text: snapshots.append(self.disk())
        self.bot.ingest(self.update(8, "/reload"))
        self.assertEqual(snapshots[-1]["offset"], 9)
        self.assertEqual(self.bot.exit_code, RELOAD)
        self.assertTrue(self.bot.done.is_set())

    def test_failed_persistence_cannot_advance_offset_or_make_task_runnable(self):
        original = self.disk()
        with patch("vibe_claw_light.runtime.write_json", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.bot.ingest(self.update(17))
        self.assertEqual(self.bot.state, original)
        self.assertEqual(self.disk(), original)
        self.assertTrue(self.bot.done.is_set())
        self.assertFalse(self.bot.wake.is_set())

    def test_active_task_is_not_replayed_automatically_after_crash(self):
        self.bot.ingest(self.update())
        state = self.disk()
        state["active"] = state["queue"].pop()
        state["queue"].append({"id": 2, "text": "Étape suivante", "document": None})
        write_json(self.bot.state_path, state)
        fresh = Bot(self.config, FakeTelegram())
        self.assertTrue(fresh.recovered)
        self.assertTrue(fresh.state["paused"])
        self.assertIsNone(fresh.state["active"])
        self.assertEqual([task["id"] for task in fresh.state["queue"]], [2])

    def test_second_worker_refusal_cannot_modify_the_running_workers_state(self):
        state = self.disk()
        state["active"] = {"id": 4, "text": "Travail en cours", "document": None}
        write_json(self.bot.state_path, state)
        before = self.bot.state_path.read_bytes()
        with FileLock(self.config.data / "worker.lock"):
            with self.assertRaises(RuntimeError):
                Bot(self.config, FakeTelegram()).run()
        self.assertEqual(self.bot.state_path.read_bytes(), before)

    def test_valid_json_with_incomplete_state_is_rejected_without_rewriting(self):
        write_json(self.bot.state_path, {"queue": []})
        before = self.bot.state_path.read_bytes()
        with self.assertRaises(ValueError):
            Bot(self.config, FakeTelegram())
        self.assertEqual(self.bot.state_path.read_bytes(), before)

    def test_session_callback_is_durable_and_late_results_cannot_undo_commands(self):
        for command in ("/clear", "/forget preference.style", "/stop"):
            with self.subTest(command=command):
                local_root = self.root / command.split()[0].strip("/")
                bot = Bot(replace(self.config, root=local_root, workspace=local_root / "workspace"), FakeTelegram())
                started, release = threading.Event(), threading.Event()

                class Runner:
                    def run(self, prompt, session_id, cancel, on_session, on_progress):
                        on_session("session_before")
                        started.set()
                        release.wait(3)
                        on_session("session_after")
                        on_progress("PROGRESS_AFTER_CANCEL")
                        return Result("ANSWER_AFTER_CANCEL", "session_after")

                bot.runner_factory = lambda config: Runner()
                bot.ingest(self.update(1))
                worker = threading.Thread(target=bot.work, daemon=True)
                worker.start()
                try:
                    self.assertTrue(started.wait(2))
                    self.assertEqual(read_json(bot.state_path)["sessions"], {"codex": "session_before"})
                    bot.ingest(self.update(2, command))
                    self.assertTrue(bot.cancel.is_set())
                    bot.done.set()
                    release.set()
                    worker.join(2)
                    self.assertFalse(worker.is_alive())
                    sessions = read_json(bot.state_path)["sessions"]
                    self.assertNotIn("session_after", sessions.values())
                    if command != "/stop":
                        self.assertEqual(sessions, {})
                    delivered = "\n".join(text for _, text in bot.telegram.messages)
                    self.assertNotIn("ANSWER_AFTER_CANCEL", delivered)
                    self.assertNotIn("PROGRESS_AFTER_CANCEL", delivered)
                    self.assertIsNone(read_json(bot.state_path)["active"])
                finally:
                    bot.done.set()
                    bot.cancel.set()
                    release.set()
                    bot.wake.set()
                    worker.join(2)

    def test_memory_is_refreshed_in_native_context_not_repeated_in_user_messages(self):
        task = {"text": "Où commencer ?"}
        unique = "Travaille le mardi à 06h15."
        self.assertNotIn(unique, current_snapshot(self.config)[0])
        self.bot.memory.apply_updates({"upsert": [{"key": "habit.hours", "kind": "habit", "text": unique, "evidence": unique}]}, unique)
        self.assertIn(unique, current_snapshot(self.config)[0])
        first = self.bot.prompt(task)
        self.assertIn(unique, first)
        self.bot.state["context_revisions"]["codex"] = {"session": "session_test", "revision": task["context_revision"]}
        next_message = self.bot.prompt(task, "session_test")
        self.assertNotIn(unique, next_message)
        self.assertNotIn("VIBE_MEMORY", next_message)
        self.assertLess(len(next_message), 450)
        self.assertIn("current.md", next_message)
        self.assertIn(unique, self.bot.prompt(task, "different_session"))
        self.bot.ingest(self.update(2, "/clear"))
        self.assertIn(unique, self.bot.prompt(task))

    def test_native_context_reload_picks_up_rules_soul_and_updated_memory(self):
        soul = self.root / "identity" / "SOUL.md"
        soul.parent.mkdir()
        soul.write_text("Rôle fictif : documentaliste.", encoding="utf-8")
        first = current_snapshot(self.config)[0]
        self.assertIn("documentaliste", first)
        soul.write_text("Rôle fictif : rédacteur.", encoding="utf-8")
        second = current_snapshot(self.config)[0]
        self.assertIn("rédacteur", second)
        self.assertNotIn("documentaliste", second)
        self.assertIn("Ne relance", native_context(self.config))

    def test_memory_protocol_never_reaches_telegram_even_when_malformed(self):
        self.bot.ingest(self.update())
        self.run_once(Result("Voici le résultat.\n<!--VIBE_MEMORY\n{invalid secret data"))
        messages = "\n".join(text for _, text in self.telegram.messages)
        self.assertIn("Voici le résultat.", messages)
        self.assertNotIn("VIBE_MEMORY", messages)
        self.assertNotIn("invalid secret data", messages)

    def test_forget_in_natural_language_resets_sessions(self):
        text = "Oublie ma préférence de style."
        self.bot.ingest(self.update(text=text))
        payload = {"forget": [{"key": "preference.style", "evidence": text}]}
        response = "C'est oublié.\n<!--VIBE_MEMORY\n" + json.dumps(payload) + "\nVIBE_MEMORY-->"
        self.run_once(Result(response))
        self.assertEqual(self.disk()["sessions"], {})
        self.assertNotIn("VIBE_MEMORY", "\n".join(text for _, text in self.telegram.messages))

    def test_secrets_are_redacted_without_destroying_normal_links(self):
        self.bot.deliver(f"Voir https://example.com/a ; token {self.config.telegram_token}")
        message = self.telegram.messages[-1][1]
        self.assertNotIn(self.config.telegram_token, message)
        self.assertIn("https://example.com/a", message)

    def test_delivery_restricts_files_to_workspace(self):
        outside = self.root / "config.env"
        outside.write_text("secret configuration", encoding="utf-8")
        inside = self.config.workspace / "résumé.txt"
        inside.write_text("Livrable", encoding="utf-8")
        self.bot.deliver(f"[[file:{outside}]]\n[[file:{inside}]]")
        self.assertEqual(self.telegram.documents, [(123, inside)])

    def test_delivery_accepts_an_authorized_project_and_denies_private_data(self):
        extra = self.root / "another-project"
        extra.mkdir()
        output = extra / "document.txt"
        output.write_text("Livrable", encoding="utf-8")
        bot = Bot(replace(self.config, extra_dirs=(extra,)), self.telegram)
        for name in ("data/context/codex.md", "data/state.json", "memory/INDEX.md", ".claude/secret.txt",
                     ".claude.json", ".git-credentials", ".netrc", ".npmrc"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private fixture", encoding="utf-8")
            self.assertFalse(bot.can_deliver(path))
        self.assertTrue(bot.can_deliver(output))
        bot.deliver(f"[[file:{output}]]")
        self.assertEqual(self.telegram.documents[-1], (123, output))

    def test_attachment_filename_cannot_escape_private_download_directory(self):
        task = {"id": 1, "document": {"file_id": "fake", "file_name": "../../outside.txt", "file_size": 4}}
        self.bot.attachments(task)
        self.assertTrue(Path(task["attachment"]).is_relative_to(self.config.data / "files"))
        self.assertFalse((self.root / "outside.txt").exists())

    def test_workspace_or_permission_change_invalidates_provider_sessions(self):
        self.bot.state["sessions"] = {"codex": "session_a", "claude": "session_b"}
        self.bot.persist()
        fresh = Bot(replace(self.config, workspace=self.root / "different"), FakeTelegram())
        self.assertEqual(fresh.state["sessions"], {})
        fresh.state["sessions"] = {"codex": "session_a"}
        fresh.persist()
        fresh = Bot(replace(fresh.config, allow_shell=True), FakeTelegram())
        self.assertEqual(fresh.state["sessions"], {})

    def run_memory_overflow(self, replies, interrupt=None):
        from vibe_claw_light import memory as memory_module
        original = "Préférence A : " + "documents sobres et courts, " * 10
        new = "Préférence B : " + "présentations lisibles et utiles, " * 9
        self.bot.memory.apply_updates({"upsert": [{"key": "preference.base", "kind": "preference", "text": original, "evidence": original}]}, original)
        before = self.bot.memory.path.read_bytes()
        budget = len(self.bot.memory.context()) + 20
        self.bot.ingest(self.update(text=new))
        proposal = {"upsert": [{"key": "preference.new", "kind": "preference", "text": new, "evidence": new}]}
        initial = "Travail terminé.\n<!--VIBE_MEMORY\n" + json.dumps(proposal) + "\nVIBE_MEMORY-->"
        calls = []
        bot = self.bot

        class Runner:
            def run(self, prompt, session_id, cancel, on_session, on_progress, *, maintenance=False):
                calls.append((prompt, session_id, maintenance))
                if not maintenance:
                    on_session("session_conversation")
                    bot.done.set()  # Un seul message de travail dans ce test.
                    return Result(initial, "session_conversation")
                if interrupt:
                    bot.ingest(self_outer.update(2, interrupt))
                return Result(replies[min(len(calls) - 2, len(replies) - 1)], "session_maintenance")

        self_outer = self
        bot.runner_factory = lambda config: Runner()
        with patch.object(memory_module, "MAX_CONTEXT_CHARS", budget):
            bot.work()
        return calls, before

    def test_rules_change_resets_session_but_profile_changes_do_not(self):
        self.bot.state["sessions"] = {"codex": "session_existing"}
        self.bot.persist()
        soul = self.root / "identity" / "SOUL.md"
        soul.parent.mkdir()
        soul.write_text("Ton bref.", encoding="utf-8")
        unchanged = Bot(self.config, FakeTelegram())
        self.assertEqual(unchanged.state["sessions"], {"codex": "session_existing"})
        with patch("vibe_claw_light.runtime.native_context", return_value="Consignes nouvelles"):
            changed = Bot(self.config, FakeTelegram())
        self.assertEqual(changed.state["sessions"], {})

    def test_overflow_retries_once_and_preserves_the_chat_session(self):
        compact = {"compact": [{"key": "preference.base", "text": "Documents sobres et courts."},
                               {"key": "preference.new", "text": "Présentations lisibles et utiles."}]}
        valid = "<!--VIBE_MEMORY\n" + json.dumps(compact) + "\nVIBE_MEMORY-->"
        calls, _ = self.run_memory_overflow(["invalid", valid])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(sid is None and maintenance for _, sid, maintenance in calls[1:]))
        self.assertIn("refusée", calls[-1][0])
        self.assertEqual(self.disk()["sessions"], {"codex": "session_conversation"})
        self.assertIn("preference.new", self.bot.memory.context())
        messages = "\n".join(text for _, text in self.telegram.messages)
        self.assertIn("consolidée", messages)
        self.assertNotIn("VIBE_MEMORY", messages)

    def test_failed_maintenance_is_bounded_and_preserves_the_existing_memory(self):
        calls, before = self.run_memory_overflow(["invalid"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.bot.memory.path.read_bytes(), before)
        self.assertIn("nouvel ajout non retenu", "\n".join(text for _, text in self.telegram.messages))

    def test_forget_during_maintenance_cannot_restore_old_memories(self):
        compact = {"compact": [{"key": "preference.base", "text": "Documents sobres."},
                               {"key": "preference.new", "text": "Présentations lisibles."}]}
        valid = "<!--VIBE_MEMORY\n" + json.dumps(compact) + "\nVIBE_MEMORY-->"
        calls, _ = self.run_memory_overflow([valid], interrupt="/forget preference.base")
        self.assertEqual(len(calls), 2)
        state = json.loads(self.bot.memory.path.read_text(encoding="utf-8"))
        self.assertEqual(state["entries"], {})
        self.assertIn("preference.base", state["forgotten"])
        self.assertEqual(self.disk()["sessions"], {})


if __name__ == "__main__":
    unittest.main()
