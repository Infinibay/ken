"""Connection setup + schema init + meta KV helpers."""

from __future__ import annotations

from ken.db import connect, get_meta, init_schema, set_meta


def test_connect_enables_wal_and_foreign_keys(tmp_path):
    db = tmp_path / "test.db"
    conn = connect(db)
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert journal.lower() == "wal"
    assert fk == 1
    conn.close()


def test_init_schema_idempotent(tmp_path):
    db = tmp_path / "test.db"
    conn = connect(db)
    init_schema(conn)
    table_count_1 = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    init_schema(conn)
    table_count_2 = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    assert table_count_1 == table_count_2
    assert table_count_1 > 0  # at least some tables created
    conn.close()


def test_set_get_meta_roundtrip(tmp_path):
    db = tmp_path / "test.db"
    conn = connect(db)
    init_schema(conn)
    set_meta(conn, "k", "v1")
    assert get_meta(conn, "k") == "v1"
    set_meta(conn, "k", "v2")  # upsert
    assert get_meta(conn, "k") == "v2"
    conn.close()


def test_get_meta_returns_default_for_missing(tmp_path):
    db = tmp_path / "test.db"
    conn = connect(db)
    init_schema(conn)
    assert get_meta(conn, "absent") is None
    assert get_meta(conn, "absent", default="fallback") == "fallback"
    conn.close()
