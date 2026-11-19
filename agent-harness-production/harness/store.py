"""Where a run lives between steps, so a restart continues instead of starting again."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("CREATE TABLE IF NOT EXISTS run (id TEXT PRIMARY KEY, status TEXT NOT NULL, messages TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS effect (key TEXT PRIMARY KEY, result TEXT NOT NULL)")

    def load(self, run_id: str) -> tuple[str, list[dict[str, Any]]] | None:
        row = self._db.execute("SELECT status, messages FROM run WHERE id = ?", (run_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def save(self, run_id: str, status: str, messages: list[dict[str, Any]]) -> None:
        self._db.execute(
            "INSERT INTO run (id, status, messages) VALUES (?, ?, ?) ON CONFLICT (id) DO UPDATE SET status = excluded.status, messages = excluded.messages",
            (run_id, status, json.dumps(messages)),
        )

    def effect(self, key: str) -> str | None:
        """The recorded result of a write that already happened under this key."""
        row = self._db.execute("SELECT result FROM effect WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def record_effect(self, key: str, result: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO effect (key, result) VALUES (?, ?)", (key, result))

    def close(self) -> None:
        self._db.close()
