"""Fixture expectations come from declared rows; mutations cannot be hidden."""
import json
import sqlite3
import sys
from pathlib import Path

from tools.rust_migration.fixtures import build_fixture
from tools.rust_migration.reference import Reference

ROOT = Path(__file__).resolve().parents[2]


def ref():
    return Reference(ROOT, ROOT / "docs/validation/rust-migration-2026-10-18/baseline.json", "test", Path(sys.executable))


def test_fixture_state_detects_mutation(tmp_path):
    with build_fixture(tmp_path, "installed_empty", ref()) as fixture:
        assert fixture.changed() == []
        meta = fixture.root / ".ken/meta.json"
        meta.write_text('{"project_id":"changed"}')
        assert "meta.json" in fixture.changed()


def test_rows_and_slots_have_independent_expected_counts(tmp_path):
    with build_fixture(tmp_path, "partial", ref()) as fixture:
        assert fixture.expected_report["counts"]["files"] == 2
        assert fixture.expected_report["counts"]["files_embedded"] == 1
        with sqlite3.connect(fixture.root / ".ken/ken.db") as conn:
            conn.execute("DELETE FROM ci_symbols")
        assert "database" in fixture.changed()


def test_wal_commit_is_visible_while_writer_remains_open(tmp_path):
    with build_fixture(tmp_path, "wal", ref()) as fixture:
        assert fixture.writer is not None
        db = fixture.root / ".ken/ken.db"
        assert Path(str(db) + "-wal").stat().st_size > 0
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            assert conn.execute("SELECT count(*) FROM ci_files").fetchone()[0] == 1
