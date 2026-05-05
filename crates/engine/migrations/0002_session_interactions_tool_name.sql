-- Add the optional `tool_name` column to `session_interactions`. This is
-- forensics / telemetry only — the ranker never reads it. See the project
-- memory `project_tool_event_boundary.md` and `docs/03-ranking.md` for the
-- contract: the engine offers a fixed 5-verb `EventType` vocabulary; clients
-- map their own tool names to it. We keep the original tool name here so
-- future per-tool weight learning (MVP+) has a column to aggregate over.

ALTER TABLE session_interactions ADD COLUMN tool_name TEXT;
