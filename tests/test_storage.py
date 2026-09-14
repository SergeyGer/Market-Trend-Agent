"""Tests for the SQLite state store."""

from __future__ import annotations

from storage import StateStore


def test_state_store_roundtrip(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    try:
        assert not store.is_seen("hash-1")
        assert not store.is_analyzed("hash-1")

        store.mark_seen("hash-1", "https://example.com", "Title", "source")
        assert store.is_seen("hash-1")
        assert not store.is_analyzed("hash-1")

        store.mark_analyzed("hash-1")
        assert store.is_analyzed("hash-1")
    finally:
        store.close()
