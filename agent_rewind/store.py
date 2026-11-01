"""Append-only recorded snapshots, hash validation and independent branches."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(previous, payload):
    return hashlib.sha256((previous + canonical(payload)).encode()).hexdigest()


class Store:
    def __init__(self, path="agent-rewind.db"):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, policy TEXT NOT NULL,
                    parent_id TEXT REFERENCES runs(id), fork_at INTEGER, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT REFERENCES runs(id), seq INTEGER, payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, hash TEXT NOT NULL,
                    PRIMARY KEY(run_id, seq)
                );
                CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_event_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, name, policy="custom"):
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            raise ValueError("Run name must contain 1–200 characters")
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (
                run_id, name, policy, None, None, datetime.now(timezone.utc).isoformat()))
        return run_id

    def runs(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY created_at DESC")]

    def get(self, run_id):
        with self.connect() as db:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise KeyError("Run not found")
            events = []
            previous = ""
            for row in db.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)):
                payload = json.loads(row["payload"])
                if row["seq"] != len(events) or row["previous_hash"] != previous or digest(previous, payload) != row["hash"]:
                    raise ValueError("Trajectory integrity check failed")
                events.append({"seq": row["seq"], **payload, "hash": row["hash"]})
                previous = row["hash"]
            return {**dict(run), "events": events, "integrity": "valid"}

    def append(self, run_id, kind, label, state, *, inputs=None, output=None):
        if kind not in {"start", "observation", "decision", "tool", "finish", "error"}:
            raise ValueError("Unknown event kind")
        if not isinstance(state, dict) or not isinstance(label, str) or len(label) > 500:
            raise ValueError("A state object and short event label are required")
        payload = {"kind": kind, "label": label, "state": state, "inputs": inputs,
                   "output": output, "at": datetime.now(timezone.utc).isoformat()}
        encoded = canonical(payload)  # Serialize now; later caller mutations cannot change history.
        if len(encoded.encode()) > 256_000:
            raise ValueError("Event exceeds 256 KB")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone():
                raise KeyError("Run not found")
            last = db.execute("SELECT seq,hash,payload FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
            if last and json.loads(last["payload"])["kind"] in {"finish", "error"}:
                raise ValueError("Run is complete; fork from an earlier checkpoint")
            seq, previous = (last["seq"] + 1, last["hash"]) if last else (0, "")
            db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (run_id, seq, encoded, previous, digest(previous, payload)))
            return seq

    def checkpoint(self, run_id, seq):
        events = self.get(run_id)["events"]
        if type(seq) is not int or seq < 0 or seq >= len(events):
            raise ValueError("Checkpoint does not exist")
        return events[seq]["state"]

    def fork(self, run_id, seq, policy="custom"):
        run = self.get(run_id)
        self.checkpoint(run_id, seq)
        if run["events"][seq]["kind"] in {"finish", "error"}:
            raise ValueError("Choose a checkpoint before completion")
        new_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (new_id, run["name"] + " · fork", policy,
                       run_id, seq, datetime.now(timezone.utc).isoformat()))
            db.execute("INSERT INTO events SELECT ?,seq,payload,previous_hash,hash FROM events WHERE run_id=? AND seq<=?", (new_id, run_id, seq))
        return new_id

    def compare(self, left_id, right_id):
        left, right = self.get(left_id), self.get(right_id)
        common = 0
        for a, b in zip(left["events"], right["events"]):
            if a["hash"] != b["hash"]:
                break
            common += 1
        def summary(run):
            return {"id": run["id"], "policy": run["policy"], "steps": len(run["events"]),
                    "state": run["events"][-1]["state"] if run["events"] else {}}
        return {"shared_steps": common, "left": summary(left), "right": summary(right)}
