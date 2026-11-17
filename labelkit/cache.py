"""Tiny SQLite-backed response cache for web provider calls."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Cache:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, ts REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str, ttl: float | None = None):
        row = self._conn.execute(
            "SELECT value, ts FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, timestamp = row
        if ttl is not None and time.time() - float(timestamp) > ttl:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None

    def set(self, key: str, value) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, ts) VALUES (?, ?, ?)",
            (key, json.dumps(value), time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
