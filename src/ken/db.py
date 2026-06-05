"""SQLite connection helpers.

Two access patterns coexist:

* **Hooks** (short-lived `ken hook ...` invocations) open a connection,
  do one or two writes, close. They use WAL so they don't block the
  daemon's writer.
* **The daemon** (`ken serve`) holds a single long-lived connection in its
  main thread plus per-worker connections for the indexer / watcher
  threads (sqlite3 connections are not safe to share across threads).

WAL is enabled lazily on the first connection per database — once set,
it persists in the file header.
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sane defaults.

    * `WAL` journal so concurrent readers don't block.
    * `foreign_keys = ON` (sqlite ships it OFF by default).
    * `busy_timeout = 5000` so a slow writer doesn't make hooks fail
      with `database is locked` — they just wait.
    * `check_same_thread = False` so the daemon's HTTP threads can
      share its single writer connection. Safety comes from a
      ``threading.Lock`` around every write inside the daemon — sqlite
      itself serialises journaling, but the Python wrapper would
      otherwise reject cross-thread use even when properly locked.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply `schema.sql`, then run additive column migrations. Idempotent."""
    sql = resources.files("ken").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    _migrate(conn)


# Additive ``ALTER TABLE ... ADD COLUMN`` migrations for databases created
# before a column existed. ``CREATE TABLE IF NOT EXISTS`` never alters an
# existing table, so new columns must be added here; each is guarded against
# the "duplicate column" error so re-running is a no-op.
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("ci_imports", "resolution", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in _COLUMN_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        except sqlite3.OperationalError:
            pass  # column already present
    # Indexes on migrated columns must come after the ALTER above so the column
    # exists on databases created before it.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ci_imports_resolution ON ci_imports(resolution)"
    )


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default
