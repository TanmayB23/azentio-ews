"""SQLite evidence store. Runs, alerts and reviews are append-only: triggers in
the database reject UPDATE and DELETE, so an analyst's later decision can never
alter the original score and evidence."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from ews.contracts import CustomerResult

DECISIONS = ("Continue Monitoring", "Requires Investigation", "False Positive", "Escalate for Review")
SCHEMA_VERSION = 2


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        decisions = ", ".join(f"'{d}'" for d in DECISIONS)
        with self.connect() as db:
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, profile TEXT NOT NULL,
                    engine TEXT NOT NULL, dataset_id TEXT NOT NULL, dataset_label TEXT NOT NULL,
                    customer_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                    customer_id TEXT NOT NULL, result_json TEXT NOT NULL,
                    UNIQUE(run_id, customer_id));
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(alert_id),
                    decision TEXT NOT NULL CHECK(decision IN ({decisions})),
                    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
                    analyst TEXT NOT NULL CHECK(length(trim(analyst)) > 0), created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS review_alert ON reviews(alert_id, review_id);
                CREATE TABLE IF NOT EXISTS ai_notes (
                    note_id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(alert_id),
                    created_at TEXT NOT NULL, source TEXT NOT NULL, model TEXT, prompt_version TEXT NOT NULL,
                    input_hash TEXT NOT NULL, requested_by TEXT NOT NULL, note_json TEXT NOT NULL,
                    verification_json TEXT NOT NULL, error TEXT);
                CREATE INDEX IF NOT EXISTS note_alert ON ai_notes(alert_id, note_id);
                CREATE TABLE IF NOT EXISTS review_ai_notes (
                    review_id INTEGER PRIMARY KEY REFERENCES reviews(review_id),
                    note_id INTEGER NOT NULL REFERENCES ai_notes(note_id));
                CREATE TABLE IF NOT EXISTS ai_outputs (
                    output_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id),
                    subject TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT NOT NULL, model TEXT,
                    input_hash TEXT NOT NULL, requested_by TEXT NOT NULL, output_json TEXT NOT NULL,
                    verification_json TEXT NOT NULL, error TEXT);
                CREATE INDEX IF NOT EXISTS output_subject ON ai_outputs(kind, run_id, subject, output_id);
                CREATE TABLE IF NOT EXISTS evidence_decisions (
                    decision_id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(alert_id),
                    repayment_id TEXT NOT NULL, output_id INTEGER REFERENCES ai_outputs(output_id),
                    accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
                    note TEXT NOT NULL CHECK(length(trim(note)) > 0),
                    analyst TEXT NOT NULL CHECK(length(trim(analyst)) > 0), created_at TEXT NOT NULL);
            """)
            version = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if version is None:
                db.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(version["value"]) != SCHEMA_VERSION:
                raise RuntimeError(f"{self.path} uses evidence schema v{version['value']}; expected v{SCHEMA_VERSION}")
            for table in ("runs", "alerts", "reviews", "ai_notes", "review_ai_notes", "ai_outputs",
                          "evidence_decisions"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                               "BEGIN SELECT RAISE(ABORT, 'Evidence is append-only'); END")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def save_run(self, results: list[CustomerResult], profile: str, engine: str, dataset_id: str,
                 dataset_label: str) -> str:
        run_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (run_id, self.now(), profile, engine, dataset_id, dataset_label, len(results)))
            db.executemany("INSERT INTO alerts(run_id, customer_id, result_json) VALUES (?, ?, ?)",
                           [(run_id, r.customer_id, json.dumps(asdict(r), allow_nan=False)) for r in results])
        return run_id

    def runs(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY created_at DESC")]

    def run(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def alerts(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM alerts WHERE run_id = ? ORDER BY alert_id", (run_id,))]

    def alert(self, run_id: str, customer_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM alerts WHERE run_id = ? AND customer_id = ?", (run_id, customer_id)).fetchone()
        if row is None:
            raise KeyError(customer_id)
        return dict(row)

    def add_review(self, alert_id: int, decision: str, reason: str, analyst: str,
                   ai_note_id: int | None = None) -> dict:
        if decision not in DECISIONS:
            raise ValueError(f"Decision must be one of: {', '.join(DECISIONS)}")
        if not reason.strip() or not analyst.strip():
            raise ValueError("A reason and an analyst name are required")
        with self.connect() as db:
            if ai_note_id is not None:
                note = db.execute("SELECT alert_id FROM ai_notes WHERE note_id = ?", (ai_note_id,)).fetchone()
                if note is None or note["alert_id"] != alert_id:
                    raise ValueError("The AI note does not belong to this alert")
            cur = db.execute("INSERT INTO reviews(alert_id, decision, reason, analyst, created_at) VALUES (?, ?, ?, ?, ?)",
                             (alert_id, decision, reason.strip(), analyst.strip(), self.now()))
            if ai_note_id is not None:
                db.execute("INSERT INTO review_ai_notes VALUES (?, ?)", (cur.lastrowid, ai_note_id))
            return dict(db.execute(f"{_REVIEW_SELECT} WHERE r.review_id = ?", (cur.lastrowid,)).fetchone())

    def reviews(self, alert_id: int) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                f"{_REVIEW_SELECT} WHERE r.alert_id = ? ORDER BY r.review_id DESC", (alert_id,))]

    def add_note(self, alert_id: int, source: str, model: str | None, prompt_version: str, input_hash: str,
                 requested_by: str, note: dict, verification: dict, error: str | None = None) -> dict:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO ai_notes(alert_id, created_at, source, model, prompt_version, input_hash, requested_by, "
                "note_json, verification_json, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, self.now(), source, model, prompt_version, input_hash, requested_by.strip() or "unknown",
                 json.dumps(note, allow_nan=False), json.dumps(verification, allow_nan=False), error))
            return _note(db.execute("SELECT * FROM ai_notes WHERE note_id = ?", (cur.lastrowid,)).fetchone())

    def notes(self, alert_id: int) -> list[dict]:
        with self.connect() as db:
            return [_note(row) for row in db.execute(
                "SELECT * FROM ai_notes WHERE alert_id = ? ORDER BY note_id DESC", (alert_id,))]

    def add_output(self, kind: str, run_id: str, subject: str, source: str, model: str | None, input_hash: str,
                   requested_by: str, output: dict, verification: dict, error: str | None = None) -> dict:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO ai_outputs(kind, run_id, subject, created_at, source, model, input_hash, requested_by, "
                "output_json, verification_json, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, run_id, subject, self.now(), source, model, input_hash, requested_by.strip() or "unknown",
                 json.dumps(output, allow_nan=False), json.dumps(verification, allow_nan=False), error))
            return _output(db.execute("SELECT * FROM ai_outputs WHERE output_id = ?", (cur.lastrowid,)).fetchone())

    def outputs(self, kind: str, run_id: str, subject: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM ai_outputs WHERE kind = ? AND run_id = ?", [kind, run_id]
        if subject is not None:
            sql, args = sql + " AND subject = ?", args + [subject]
        with self.connect() as db:
            return [_output(r) for r in db.execute(sql + " ORDER BY output_id DESC", args)]

    def output(self, output_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM ai_outputs WHERE output_id = ?", (output_id,)).fetchone()
        if row is None:
            raise KeyError(output_id)
        return _output(row)

    def add_evidence_decision(self, alert_id: int, repayment_id: str, accepted: bool, note: str, analyst: str,
                              output_id: int | None = None) -> dict:
        if not note.strip() or not analyst.strip():
            raise ValueError("A note and an analyst name are required")
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO evidence_decisions(alert_id, repayment_id, output_id, accepted, note, analyst, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (alert_id, repayment_id, output_id, int(accepted), note.strip(), analyst.strip(), self.now()))
            return dict(db.execute("SELECT * FROM evidence_decisions WHERE decision_id = ?", (cur.lastrowid,)).fetchone())

    def evidence_decisions(self, alert_id: int) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM evidence_decisions WHERE alert_id = ? ORDER BY decision_id DESC", (alert_id,))]

    def latest_reviews(self, run_id: str) -> dict[str, dict]:
        """Latest review per customer in a run (current analyst classification)."""
        with self.connect() as db:
            rows = db.execute("""
                SELECT a.customer_id, r.* FROM reviews r JOIN alerts a ON a.alert_id = r.alert_id
                WHERE a.run_id = ? AND r.review_id = (SELECT MAX(review_id) FROM reviews WHERE alert_id = r.alert_id)
            """, (run_id,))
            return {row["customer_id"]: dict(row) for row in rows}

    def review_log(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT a.customer_id, r.* FROM reviews r JOIN alerts a ON a.alert_id = r.alert_id
                WHERE a.run_id = ? ORDER BY r.review_id DESC""", (run_id,))]


_REVIEW_SELECT = ("SELECT r.*, l.note_id AS ai_note_id FROM reviews r "
                  "LEFT JOIN review_ai_notes l ON l.review_id = r.review_id")


def _note(row) -> dict:
    d = dict(row)
    d["note"] = json.loads(d.pop("note_json"))
    d["verification"] = json.loads(d.pop("verification_json"))
    return d


def _output(row) -> dict:
    d = dict(row)
    d["output"] = json.loads(d.pop("output_json"))
    d["verification"] = json.loads(d.pop("verification_json"))
    return d
