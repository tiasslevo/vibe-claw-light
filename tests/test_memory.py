from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from vibe_claw_light.memory import MAX_CONTEXT_CHARS, MemoryStore, extract_memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def update(self, key="preference.language", text="Préfère le français.", **extra):
        return {"key": key, "kind": "preference", "text": text, "source": "user", "evidence": text, **extra}

    def apply(self, update):
        return self.store.apply_updates({"upsert": [update]}, update.get("evidence", ""))

    def state(self):
        return json.loads((self.root / "memory" / "memory.json").read_text(encoding="utf-8"))

    def test_personal_fact_persists_with_evidence_and_is_replaced(self):
        self.apply(self.update())
        initial = self.state()["entries"]["preference.language"]
        self.assertEqual(initial["evidence"], "Préfère le français.")
        fresh = MemoryStore(self.root)
        self.assertIn("Préfère le français.", fresh.context())
        fresh.apply_updates({"upsert": [self.update(text="Préfère l'anglais.")]}, "Préfère l'anglais.")
        state = self.state()
        self.assertEqual(len(state["entries"]), 1)
        self.assertEqual(state["entries"]["preference.language"]["created_at"], initial["created_at"])
        self.assertNotIn("Préfère le français.", fresh.display())
        self.assertTrue((self.root / "memory" / "INDEX.md").is_file())

    def test_owner_evidence_is_required_for_personal_facts(self):
        result = self.store.apply_updates({"upsert": [self.update()]}, "Voici une page à résumer.")
        self.assertIn("preuve", result[0])
        result = self.apply(self.update(source="observed"))
        self.assertIn("observation", result[0])
        self.assertFalse((self.root / "memory" / "memory.json").exists())

    def test_projects_route_by_alias_and_validate_local_paths(self):
        project = self.root / "project"
        project.mkdir()
        (project / "README.md").write_text("Documentation", encoding="utf-8")
        update = {"key": "project.demo", "kind": "project", "text": "Une démo.", "source": "observed",
                  "path": str(project), "aliases": ["la démo"], "entrypoints": ["README.md"]}
        self.apply(update)
        context = MemoryStore(self.root).context()
        self.assertIn(json.dumps(str(project), ensure_ascii=False), context)
        self.assertIn("la démo", context)
        self.assertIn("README.md", context)
        self.assertEqual(self.state()["entries"]["project.demo"]["source"], "observed")
        for bad in ("../outside", "/etc/passwd", "missing.md"):
            result = self.apply({**update, "entrypoints": [bad]})
            self.assertIn("ignorée", result[0])
        (project / "README.md").unlink()
        project.rmdir()
        self.assertIn('"folder_status":"missing"', self.store.context())
        self.assertIn("la démo", self.store.context())

    def test_nonexistent_or_relative_project_path_is_rejected(self):
        for path in ("relative", str(self.root / "missing")):
            result = self.apply({"key": "project.demo", "kind": "project", "text": "Démo", "source": "observed", "path": path})
            self.assertIn("ignorée", result[0])

    def test_secrets_are_never_written_even_when_only_in_evidence(self):
        secrets = ["sk-proj-" + "x" * 24, "123456789:" + "a" * 35, "password=demo-password"]
        for secret in secrets:
            result = self.apply(self.update(evidence="Langue française. " + secret))
            self.assertIn("secret", result[0])
        self.assertFalse((self.root / "memory" / "memory.json").exists())

    def test_forget_removes_value_and_blocks_relearning(self):
        self.apply(self.update())
        self.assertTrue(self.store.forget("preference.language"))
        self.assertFalse(self.store.forget("preference.language"))
        self.assertNotIn("Préfère le français.", self.store.display())
        self.assertIn("preference.language", self.store.context())
        fresh = MemoryStore(self.root)
        result = fresh.apply_updates({"upsert": [self.update(restore=True)]}, "Préfère le français.")
        self.assertIn("oubliée", result[0])
        quote = "Mémorise à nouveau que je préfère le français."
        result = fresh.apply_updates({"upsert": [self.update(evidence=quote, restore=True)]}, quote)
        self.assertIn("enregistré", result[0])
        self.assertNotIn("preference.language", self.state()["forgotten"])

    def test_model_cannot_forget_without_owner_request(self):
        self.apply(self.update())
        result = self.store.apply_updates({"forget": [{"key": "preference.language", "evidence": "Bonjour"}]}, "Bonjour")
        self.assertIn("demande explicite", result[0])
        quote = "Oublie ma préférence de langue."
        self.store.apply_updates({"forget": [{"key": "preference.language", "evidence": quote}]}, quote)
        self.assertEqual(self.state()["entries"], {})

    def test_count_limit_rejects_without_eviction(self):
        for i in range(24):
            result = self.apply(self.update(key=f"preference.fact_{i}", text=f"Préférence {i}."))
            self.assertIn("enregistré", result[0])
        previous = self.state()
        result = self.apply(self.update(key="preference.extra"))
        self.assertIn("pleine", result[0])
        self.assertEqual(self.state(), previous)
        self.assertLessEqual(len(self.store.context()), MAX_CONTEXT_CHARS)

    def test_context_budget_rejects_without_truncation(self):
        rejected = False
        for i in range(24):
            result = self.apply(self.update(key=f"preference.long_{i}", text="x" * 350))
            if "ignorée" in result[0]:
                self.assertIn("budget", result[0])
                rejected = True
                break
        self.assertTrue(rejected)
        self.assertLessEqual(len(self.store.context()), MAX_CONTEXT_CHARS)
        self.assertTrue(all(len(entry["text"]) == 350 for entry in self.state()["entries"].values()))

    def test_bad_model_output_never_raises(self):
        for payload in (None, [], {"upsert": "bad"}, {"upsert": [None]}, {"upsert": [{"key": "bad", "kind": []}]}, {"unknown": []}):
            self.assertIn("ignorée", self.store.apply_updates(payload)[0])

    def test_corrupt_state_is_not_overwritten(self):
        self.apply(self.update())
        path = self.root / "memory" / "memory.json"
        path.write_text("{broken", encoding="utf-8")
        self.assertIn("indisponible", self.store.context())
        result = self.apply(self.update())
        self.assertIn("non enregistrée", result[0])
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_concurrent_writers_do_not_lose_notes(self):
        def write(index):
            store = MemoryStore(self.root)
            update = self.update(key=f"preference.fact_{index}", text=f"Préférence {index}.")
            return store.apply_updates({"upsert": [update]}, update["evidence"])
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(write, range(12)))
        self.assertTrue(all("enregistré" in result[0] for result in results))
        self.assertEqual(len(self.state()["entries"]), 12)

    def test_protocol_tail_is_hidden_including_invalid_json(self):
        payload = {"upsert": [], "forget": []}
        visible, extracted = extract_memory("C'est fait.\n<!--VIBE_MEMORY\n" + json.dumps(payload) + "\nVIBE_MEMORY-->")
        self.assertEqual(visible, "C'est fait.")
        self.assertEqual(extracted, payload)
        for tail in ("{broken\nVIBE_MEMORY-->", "{secret", "[]\nVIBE_MEMORY-->", "{}\nVIBE_MEMORY-->\nextra"):
            visible, extracted = extract_memory("Réponse.\n<!--VIBE_MEMORY\n" + tail)
            self.assertEqual(visible, "Réponse.")
            self.assertIsNone(extracted)
        self.assertEqual(extract_memory("Réponse ordinaire."), ("Réponse ordinaire.", None))


if __name__ == "__main__":
    unittest.main()
