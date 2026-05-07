"""Long-running per-project daemon for hook and MCP traffic.

Owns:
  * the SQLite write connection,
  * the file watcher + incremental index queue,
  * an HTTP API the hook commands talk to,
  * a 10-minute idle timer that shuts the process down once coding agents
    isn't asking for anything.

SessionEnd brings the active-session count to 0; after a 60-second grace
period (in case another window opens) the daemon exits.
"""
