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
    -- 'internal'  = resolved to an indexed file (to_file_id set)
    -- 'external'  = a third-party / stdlib package (npm, crate, std, java.*)
    -- 'unresolved'= looks internal (relative / crate:: / alias / own module)
    --               but ken could not map it — a real resolution gap, not a dep
    resolution      TEXT,
    line            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_imports_from ON ci_imports(from_file_id);
-- NB: the index on ci_imports(resolution) is created in db._migrate, after the
-- column is guaranteed to exist (ALTER for pre-existing DBs runs there).
CREATE INDEX IF NOT EXISTS idx_ci_imports_to_file ON ci_imports(to_file_id) WHERE to_file_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ci_references (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_file_id    INTEGER NOT NULL REFERENCES ci_files(id) ON DELETE CASCADE,
    to_symbol_id    INTEGER NOT NULL REFERENCES ci_symbols(id) ON DELETE CASCADE,
    line            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_references_to ON ci_references(to_symbol_id);

CREATE TABLE IF NOT EXISTS ci_intent_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER REFERENCES ci_files(id) ON DELETE CASCADE,
    symbol_id       INTEGER REFERENCES ci_symbols(id) ON DELETE CASCADE,
    source_kind     TEXT NOT NULL,                -- module_docstring | symbol_docstring | …
    text            TEXT NOT NULL,
    embedding       BLOB,                         -- float32[384]
    weight          REAL NOT NULL DEFAULT 1.0,
    updated_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ci_intent_file ON ci_intent_sources(file_id);
CREATE INDEX IF NOT EXISTS idx_ci_intent_symbol ON ci_intent_sources(symbol_id);
CREATE INDEX IF NOT EXISTS idx_ci_intent_embedding
    ON ci_intent_sources(source_kind)
    WHERE embedding IS NOT NULL;

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
-- Lookup interactions by their anchoring user_prompt — the reactive
-- channel groups by turn (= context_id of the user_prompt that started
-- the turn) to apply per-turn decay on top of iteration decay.
CREATE INDEX IF NOT EXISTS idx_cr_interactions_context ON cr_interactions(context_id) WHERE context_id IS NOT NULL;

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

-- ----------------------------------------------------------------------------
-- Findings: explicit notes the agent (or the user) leaves for future runs.
-- Populated by the MCP `ken_remember` / `ken_recall` tools. Embedded so the
-- ranker can surface durable project knowledge near relevant prompts.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cr_findings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL,
    content     TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',   -- JSON array
    embedding   BLOB,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cr_findings_topic ON cr_findings(topic);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_cr_findings_topic ON cr_findings(topic);

-- ----------------------------------------------------------------------------
-- Findings graph: a deterministic relationship graph over cr_findings.
--
--   cr_finding_refs  — finding → code bridge. Extracted from each finding's
--     prose (paths + identifiers) and resolved against ci_files / ci_symbols.
--     Grouped on the DURABLE text key (ref_key), never the churny symbol id.
--     file_id / symbol_id are an ADVISORY cache of the id resolved at build
--     time — no reader trusts them; they null out (ON DELETE SET NULL) when the
--     referenced node is reindexed.
--   cr_finding_edges — finding ↔ finding typed, evidence-carrying edges
--     (semantic | shared_file | shared_symbol | shared_tag). Undirected types
--     are stored canonically (src < dst); `directed` is reserved for later
--     supersedes/contradicts edges. Kept fresh by a full recompute on every
--     remember()/forget() (findings number in the tens–hundreds).
--
-- Both are self-created by findings_graph.ensure_finding_graph() as well, since
-- the CLI/MCP write paths call db.connect() without applying this schema.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cr_finding_refs (
    finding_id  INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,
    ref_kind    TEXT    NOT NULL,                 -- 'file' | 'symbol'
    ref_key     TEXT    NOT NULL,                 -- DURABLE: path, or qualname\x1fpath
    file_id     INTEGER REFERENCES ci_files(id)   ON DELETE SET NULL,   -- advisory cache
    symbol_id   INTEGER REFERENCES ci_symbols(id) ON DELETE SET NULL,   -- advisory cache
    method      TEXT    NOT NULL,                 -- path | traceback | ident | snake
    resolved    INTEGER NOT NULL DEFAULT 0,       -- 1 if it matched an indexed node at build time
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (finding_id, ref_kind, ref_key)
);
CREATE INDEX IF NOT EXISTS idx_cr_finding_refs_key ON cr_finding_refs(ref_kind, ref_key);
CREATE INDEX IF NOT EXISTS idx_cr_finding_refs_file ON cr_finding_refs(file_id) WHERE file_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS cr_finding_edges (
    src         INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,
    dst         INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,
    edge_type   TEXT    NOT NULL,                 -- semantic | shared_file | shared_symbol | shared_tag
    directed    INTEGER NOT NULL DEFAULT 0,       -- reserved for directed supersedes/contradicts edges
    weight      REAL    NOT NULL,                 -- native per-type strength, clamped [0,1]
    evidence    TEXT    NOT NULL DEFAULT '{}',    -- JSON: {"cosine":0.71} | {"keys":[...]} (nodes capped <=8)
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (src, dst, edge_type),
    CHECK (src <> dst AND weight >= 0 AND weight <= 1 AND (directed = 1 OR src < dst))
);
CREATE INDEX IF NOT EXISTS idx_cr_finding_edges_dst ON cr_finding_edges(dst);

-- ----------------------------------------------------------------------------
-- Commit history: each commit is a market-basket transaction of changed files.
-- Mined by ken_cochange for logical coupling imports can't see. Ingested
-- incrementally from `git log` (last SHA tracked in meta['cochange_last_sha']).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cr_commits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sha           TEXT NOT NULL UNIQUE,
    committed_at  INTEGER NOT NULL,             -- unix seconds
    author        TEXT,
    subject       TEXT,
    n_files       INTEGER NOT NULL DEFAULT 0    -- changed-file count (pre-cap)
);
CREATE INDEX IF NOT EXISTS idx_cr_commits_time ON cr_commits(committed_at);

CREATE TABLE IF NOT EXISTS cr_commit_files (
    commit_id     INTEGER NOT NULL REFERENCES cr_commits(id) ON DELETE CASCADE,
    path          TEXT NOT NULL                 -- repo-relative, forward slashes
);
CREATE INDEX IF NOT EXISTS idx_cr_commit_files_commit ON cr_commit_files(commit_id);
CREATE INDEX IF NOT EXISTS idx_cr_commit_files_path ON cr_commit_files(path);

-- ----------------------------------------------------------------------------
-- Literal/BM25 search: per-file body mirrored into an FTS5 index, kept fresh by
-- comparing ci_fts_state.content_hash against the live worktree. Powers ken_grep.
-- ----------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS fts_files USING fts5(
    path,
    body,
    tokenize = "unicode61 tokenchars '_.-'"
);
CREATE TABLE IF NOT EXISTS ci_fts_state (
    path          TEXT PRIMARY KEY,
    content_hash  BLOB NOT NULL
);
