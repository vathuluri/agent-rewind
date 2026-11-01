import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from agent_rewind import Store
from agent_rewind.demo import start_demo, fork_demo
from agent_rewind.server import handler_for


class RewindTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "runs.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_policy_fork_shares_prefix_but_preserves_original(self):
        original = start_demo(self.store)
        before = self.store.get(original)
        branch = fork_demo(self.store, original, 1, "evidence-first")
        result = self.store.compare(original, branch)
        self.assertEqual(result["shared_steps"], 2)
        self.assertEqual(result["left"]["state"]["outcome"], "blocked")
        self.assertEqual(result["right"]["state"]["outcome"], "resolved")
        self.assertEqual(self.store.get(original), before)
        self.assertEqual(self.store.get(branch)["parent_id"], original)

    def test_caller_mutation_does_not_rewrite_snapshot(self):
        run = self.store.create("custom recorder")
        state = {"nested": {"value": 1}}
        self.store.append(run, "start", "Start", state)
        state["nested"]["value"] = 9
        self.assertEqual(self.store.checkpoint(run, 0)["nested"]["value"], 1)

    def test_sql_updates_and_deletes_are_rejected(self):
        run = start_demo(self.store)
        with self.store.connect() as db:
            for sql in ["UPDATE events SET hash='bad'", "DELETE FROM events"]:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
        self.assertEqual(self.store.get(run)["integrity"], "valid")

    def test_hash_tampering_is_detected_even_without_trigger(self):
        run = start_demo(self.store)
        with self.store.connect() as db:
            db.execute("DROP TRIGGER immutable_event_update")
            db.execute("UPDATE events SET hash='tampered' WHERE run_id=? AND seq=1", (run,))
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.store.get(run)

    def test_invalid_fork_creates_no_orphan(self):
        run = start_demo(self.store)
        for step in [-1, True, 2, 99]:
            with self.assertRaises(ValueError):
                fork_demo(self.store, run, step, "evidence-first")
        self.assertEqual(len(self.store.runs()), 1)

    def test_completed_runs_require_a_branch(self):
        run = start_demo(self.store)
        with self.assertRaises(ValueError):
            self.store.append(run, "decision", "rewrite", {})
        with self.assertRaises(KeyError):
            self.store.get("missing")

    def test_recorder_persists_across_instances(self):
        run = start_demo(self.store)
        reopened = Store(self.store.path)
        self.assertEqual(reopened.get(run), self.store.get(run))

    def test_http_demo_fork_and_origin_protection(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        def post(path, data, origin=base):
            request = Request(base + path, json.dumps(data).encode(), {"Content-Type": "application/json", "Origin": origin})
            with urlopen(request) as response:
                return json.load(response)
        try:
            run = post("/api/demo", {})["id"]
            branch = post("/api/fork", {"run_id": run, "seq": 1, "policy": "evidence-first"})["id"]
            with urlopen(base + f"/api/compare?left={run}&right={branch}") as response:
                self.assertEqual(json.load(response)["shared_steps"], 2)
            with self.assertRaises(HTTPError) as failure:
                post("/api/demo", {}, "https://untrusted.example")
            self.assertEqual(failure.exception.code, 403)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == "__main__":
    unittest.main()
