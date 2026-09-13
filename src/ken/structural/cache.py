"""Disposable, content-addressed compressed IR cache with transactional LRU.

The configured budget caps the SQLite database's page count, including its
indexes and free pages. Journals are transient transaction overhead.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Any

DEFAULT_CACHE_MB = 500


class IRCache:
    def __init__(self, path: Path, max_mb: float = DEFAULT_CACHE_MB):
        if max_mb < 0:
            raise ValueError("cache size cannot be negative")
        self.path = path
        self.limit = int(max_mb * 1_000_000)
        self.hits = self.misses = self.evictions = 0
        self.conn: sqlite3.Connection | None = None
        self.error = ""
        if self.limit < 32_768:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, timeout=5)
            self.conn.execute("PRAGMA auto_vacuum=FULL")
            self.conn.execute("PRAGMA journal_mode=DELETE")
            self.conn.execute("CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, value BLOB NOT NULL, size INTEGER NOT NULL, touched INTEGER NOT NULL)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS cache_lru ON entries(touched)")
            self.conn.commit()
            with self.conn:
                self._evict(0)
            self.conn.execute(f"PRAGMA max_page_count={max(8, self.limit // 4096)}")
        except (OSError, sqlite3.Error) as exc:
            self.error = str(exc)
            self.close()

    @staticmethod
    def key(*parts: str | bytes) -> str:
        digest = hashlib.sha256()
        for part in parts:
            data = part.encode() if isinstance(part, str) else part
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
        return digest.hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if self.conn is not None:
            try:
                row = self.conn.execute("SELECT value FROM entries WHERE key=?", (key,)).fetchone()
                if row:
                    value = json.loads(zlib.decompress(row[0]))
                    with self.conn:
                        self.conn.execute("UPDATE entries SET touched=? WHERE key=?", (time.time_ns(), key))
                    self.hits += 1
                    return value
            except (sqlite3.Error, zlib.error, ValueError) as exc:
                self.error = str(exc)
        self.misses += 1
        return None

    def _evict(self, reserve: int) -> None:
        if self.conn is None:
            return
        while True:
            pages = self.conn.execute("PRAGMA page_count").fetchone()[0]
            page_size = self.conn.execute("PRAGMA page_size").fetchone()[0]
            if pages * page_size + reserve <= self.limit:
                return
            victim = self.conn.execute("SELECT key FROM entries ORDER BY touched, key LIMIT 1").fetchone()
            if victim is None:
                return
            self.conn.execute("DELETE FROM entries WHERE key=?", victim)
            self.evictions += 1

    def put(self, key: str, value: dict[str, Any]) -> None:
        if self.conn is None:
            return
        payload = zlib.compress(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
        reserve = len(payload) * 2 + 16_384
        if reserve + 32_768 > self.limit:
            return
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("DELETE FROM entries WHERE key=?", (key,))
            self._evict(reserve)
            self.conn.execute("INSERT INTO entries VALUES (?, ?, ?, ?)", (key, payload, len(payload), time.time_ns()))
            self.conn.commit()
        except sqlite3.Error as exc:
            self.conn.rollback()
            self.error = str(exc)

    def stats(self) -> dict[str, Any]:
        return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions,
                "max_bytes": self.limit, "bytes": self.path.stat().st_size if self.path.exists() else 0,
                "enabled": self.conn is not None, "error": self.error or None}

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
