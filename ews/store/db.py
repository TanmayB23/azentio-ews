"""SQLite evidence store with database-enforced append-only records."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from ews.contracts import CustomerResult

DECISIONS = ("Confirm", "Monitor", "Dismiss", "Escalate")

class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    profile TEXT NOT NULL, engine TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                    customer_id TEXT NOT NULL, result_json TEXT NOT NULL,
                    UNIQUE(run_id, customer_id));
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(alert_id),
                    decision TEXT NOT NULL CHECK(decision IN ('Confirm','Monitor','Dismiss','Escalate')),
                    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
                    analyst TEXT NOT NULL CHECK(length(trim(analyst)) > 0), created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS review_alert ON reviews(alert_id, review_id);
            """)
            for table in ("runs", "alerts", "reviews"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'Evidence is append-only'); END")

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

    def save_run(self, results: list[CustomerResult], profile: str, engine: str) -> str:
        run_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?, ?)", (run_id, self.now(), profile, engine))
            db.executemany("INSERT INTO alerts(run_id, customer_id, result_json) VALUES (?, ?, ?)",
                [(run_id, r.customer_id, json.dumps(asdict(r), allow_nan=False)) for r in results])
        return run_id

    def runs(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY created_at DESC")]

    def alerts(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM alerts WHERE run_id = ? ORDER BY alert_id", (run_id,))]

    def alert(self, run_id: str, customer_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM alerts WHERE run_id = ? AND customer_id = ?", (run_id, customer_id)).fetchone()
            if row is None:
                raise ValueError("No saved alert for this customer and run")
            return dict(row)

    def add_review(self, alert_id: int, decision: str, reason: str, analyst: str) -> None:
        if decision not in DECISIONS or not reason.strip() or not analyst.strip():
            raise ValueError("Choose a valid decision and supply a reason and analyst name")
        with self.connect() as db:
            db.execute("INSERT INTO reviews(alert_id, decision, reason, analyst, created_at) VALUES (?, ?, ?, ?, ?)",
                (alert_id, decision, reason.strip(), analyst.strip(), self.now()))

    def reviews(self, alert_id: int) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM reviews WHERE alert_id = ? ORDER BY review_id DESC", (alert_id,))]
