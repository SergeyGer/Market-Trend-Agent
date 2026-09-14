"""Lightweight SQLite-backed state store for cross-run deduplication."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class StateStore:
    """Persist article hashes and analysis status between pipeline runs."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_articles (
                hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                analyzed_at TEXT
            )
            """
        )
        self._ensure_analyzed_column()
        self._conn.commit()

    def _ensure_analyzed_column(self) -> None:
        columns = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(seen_articles)")
        }
        if "analyzed_at" not in columns:
            self._conn.execute(
                "ALTER TABLE seen_articles ADD COLUMN analyzed_at TEXT"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def is_analyzed(self, article_hash: str) -> bool:
        """Return True only if the article was successfully analyzed."""
        with self._lock:
            row = self._conn.execute(
                "SELECT analyzed_at FROM seen_articles WHERE hash = ?",
                (article_hash,),
            ).fetchone()
            return row is not None and row[0] is not None

    def is_seen(self, article_hash: str) -> bool:
        """Return True if the article has ever been ingested."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM seen_articles WHERE hash = ?",
                (article_hash,),
            ).fetchone()
            return row is not None

    def mark_seen(self, article_hash: str, url: str, title: str, source: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO seen_articles
                    (hash, url, title, source, first_seen_at, last_seen_at)
                VALUES
                    (?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(hash) DO UPDATE SET
                    last_seen_at = datetime('now')
                """,
                (article_hash, url, title, source),
            )
            self._conn.commit()

    def mark_analyzed(self, article_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE seen_articles SET analyzed_at = datetime('now') WHERE hash = ?",
                (article_hash,),
            )
            self._conn.commit()

    def prune_before(self, threshold: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM seen_articles WHERE last_seen_at < ?",
                (threshold,),
            )
            self._conn.commit()
