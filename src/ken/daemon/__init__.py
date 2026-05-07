"""ken daemon — long-running per-project process.

Owns:
  * the SQLite write connection,
  * the (Phase 3) file watcher + index queue,
  * an HTTP API the hook commands talk to,
  * a 10-minute idle timer that shuts the process down once Claude Code
    isn't asking for anything.

A SessionEnd hook brings the active-session count to 0; after a 60-second
grace period (in case another window opens) the daemon exits.
"""
