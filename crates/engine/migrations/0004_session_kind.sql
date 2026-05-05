-- Distinguish real (live agent) sessions from synthetic ones (git replay,
-- imported from CSV, etc). The ranker doesn't currently differentiate, but
-- having the column lets us:
--   * filter out synthetic sessions in dashboards/observability,
--   * weight them differently in future ranker tunings (a real edit is
--     stronger evidence than a 3-year-old git commit, see
--     `docs/11-git-history-plan.md` §6 risk register),
--   * exclude synthetic sessions from co-edit / session-close jobs (#31).
--
-- Default 'real' on existing rows is correct: the only sessions that
-- existed before this migration came from live ingest paths.

ALTER TABLE sessions ADD COLUMN kind TEXT NOT NULL DEFAULT 'real';

-- Backfill any synthetic sessions that landed before the column existed.
-- The git-history ingest path keys them as `agent_id LIKE 'git:%'`. Safe
-- to run with the default in place because we only flip rows that match
-- the synthetic pattern.
UPDATE sessions SET kind = 'synthetic' WHERE agent_id LIKE 'git:%';

-- Most queries hit one workspace at a time; co-locating the kind in the
-- workspace index lets the planner skip synthetic rows without an extra
-- table lookup. Partial index keeps the index small.
CREATE INDEX idx_sessions_workspace_kind ON sessions(workspace_id, kind);
