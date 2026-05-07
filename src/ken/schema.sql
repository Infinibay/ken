-- Single-file SQLite schema for ken. Applied on first `ken install`; later
-- migrations append numbered statements (we intentionally keep it
-- single-file v1 — when the schema stabilises we can switch to a real
-- migration framework). WAL is enabled in db.connect so readers (the CLI
-- hooks) don't block the writer (the daemon).

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- Project metadata. Single-row-keyed table; the daemon stamps version + auth
-- token here on init.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ----------------------------------------------------------------------------
-- Code intelligence: files, symbols, imports, references.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,        -- relative to project root, forward slashes
    language        TEXT,                         -- 'python' | 'rust' | …
    content_hash    BLOB NOT NULL,                -- blake2b-256 of bytes
    parser_version  INTEGER NOT NULL DEFAULT 0,
    symbol_count    INTEGER NOT NULL DEFAULT 0,
    embedding       BLOB,                         -- float32[384]
    mtime           INTEGER NOT NULL,             -- ns since epoch
    indexed_at      INTEGER NOT NULL              -- ms since epoch
);
CREATE INDEX IF NOT EXISTS idx_ci_files_lang ON ci_files(language);

CREATE TABLE IF NOT EXISTS ci_symbols (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES ci_files(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                   -- function | class | method | const | …
    name        TEXT NOT NULL,
    qualname    TEXT,                             -- ClassName.method or module.fn
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL,
    docstring   TEXT,                             -- first line if present
    embedding   BLOB                              -- float32[384]
);
CREATE INDEX IF NOT EXISTS idx_ci_symbols_file ON ci_symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_ci_symbols_name ON ci_symbols(name);
CREATE INDEX IF NOT EXISTS idx_ci_symbols_kind ON ci_symbols(kind);

CREATE TABLE IF NOT EXISTS ci_imports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_file_id    INTEGER NOT NULL REFERENCES ci_files(id) ON DELETE CASCADE,
    to_module       TEXT NOT NULL,                -- raw import target ("os.path", "./utils")
    to_file_id      INTEGER REFERENCES ci_files(id) ON DELETE SET NULL,  -- resolved if internal
    line            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_imports_from ON ci_imports(from_file_id);
CREATE INDEX IF NOT EXISTS idx_ci_imports_to_file ON ci_imports(to_file_id) WHERE to_file_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ci_references (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_file_id    INTEGER NOT NULL REFERENCES ci_files(id) ON DELETE CASCADE,
    to_symbol_id    INTEGER NOT NULL REFERENCES ci_symbols(id) ON DELETE CASCADE,
    line            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_references_to ON ci_references(to_symbol_id);

-- ----------------------------------------------------------------------------
-- Context-rank: sessions, contexts (task descriptions / prompts / tool calls),
-- interactions (file/symbol touches), and per-session productivity scores.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cr_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT,                             -- claude session uuid
    started_at  INTEGER NOT NULL,
    ended_at    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cr_sessions_agent ON cr_sessions(agent_id);

CREATE TABLE IF NOT EXISTS cr_contexts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES cr_sessions(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                   -- task_input | step_title | tool_call | user_prompt | assistant_msg
    content     TEXT NOT NULL,
    iteration   INTEGER NOT NULL,
    embedding   BLOB,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cr_contexts_session ON cr_contexts(session_id);
CREATE INDEX IF NOT EXISTS idx_cr_contexts_kind ON cr_contexts(kind);

CREATE TABLE IF NOT EXISTS cr_interactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES cr_sessions(id) ON DELETE CASCADE,
    context_id    INTEGER REFERENCES cr_contexts(id) ON DELETE SET NULL,
    iteration     INTEGER NOT NULL,
    event_type    TEXT NOT NULL,                  -- read | edit | write | cited | dismissed
    target_kind   TEXT NOT NULL,                  -- file | symbol
    target_id     INTEGER,                         -- ci_files.id or ci_symbols.id (nullable for unresolved)
    target_path   TEXT,                            -- for file events
    weight        REAL NOT NULL DEFAULT 1.0,
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cr_interactions_session ON cr_interactions(session_id);
CREATE INDEX IF NOT EXISTS idx_cr_interactions_target_path ON cr_interactions(target_path);

CREATE TABLE IF NOT EXISTS cr_session_scores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES cr_sessions(id) ON DELETE CASCADE,
    target_kind   TEXT NOT NULL,
    target_id     INTEGER,
    target_path   TEXT,
    score         REAL NOT NULL,
    pattern       TEXT NOT NULL,                  -- read_edit | edit_only | neutral | read_skipped | …
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cr_session_scores_session ON cr_session_scores(session_id);
CREATE INDEX IF NOT EXISTS idx_cr_session_scores_target ON cr_session_scores(target_path);
