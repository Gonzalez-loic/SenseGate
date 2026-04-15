from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DeviceDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    synced INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stats_snapshot (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    in_count INTEGER NOT NULL DEFAULT 0,
                    out_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO stats_snapshot (id, in_count, out_count, updated_at) VALUES (1, 0, 0, datetime('now'));
                """
            )

    def save_stats(self, in_count: int, out_count: int, updated_at: str) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE stats_snapshot SET in_count = ?, out_count = ?, updated_at = ? WHERE id = 1",
                (in_count, out_count, updated_at),
            )

    def load_stats(self) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("SELECT in_count, out_count, updated_at FROM stats_snapshot WHERE id = 1").fetchone()
        if row is None:
            return {"in": 0, "out": 0, "updated_at": None}
        return {"in": row[0], "out": row[1], "updated_at": row[2]}

    def enqueue(self, event_type: str, payload: dict[str, Any], created_at: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO event_queue (event_type, payload_json, synced, created_at) VALUES (?, ?, 0, ?)",
                (event_type, json.dumps(payload), created_at),
            )

    def pending_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, event_type, payload_json, created_at FROM event_queue WHERE synced = 0 ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": row[0], "event_type": row[1], "payload": json.loads(row[2]), "created_at": row[3]}
            for row in rows
        ]

    def mark_synced(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join(["?"] * len(ids))
        with self._connect() as con:
            con.execute(f"UPDATE event_queue SET synced = 1 WHERE id IN ({placeholders})", ids)

    def hard_reset(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM event_queue")
            con.execute("UPDATE stats_snapshot SET in_count = 0, out_count = 0, updated_at = datetime('now') WHERE id = 1")
        logger.warning("Local database reset completed")
