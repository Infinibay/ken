"""ken's MCP (Model Context Protocol) server.

Spawned by Claude Code over stdio when the project's ``.mcp.json``
registers ken. Exposes five tools:

  * ``ken_search_files(query, limit=8)`` — semantically rank indexed
    files against the query (cosine sweep on ``ci_files.embedding``).
  * ``ken_search_symbols(query, limit=10)`` — same but for symbols
    (functions / classes / methods).
  * ``ken_remember(topic, content, tags=[])`` — write a note into
    ``cr_findings`` so future sessions can recall it.
  * ``ken_recall(query, limit=5)`` — search findings by similarity.
  * ``ken_dismiss(target, reason="")`` — explicit "this wasn't what I
    was looking for" signal. Talks to the daemon (uses the active
    session's id) so the negative pattern weighs into future
    predictive ranking.

Read-only tools query SQLite directly (WAL means we don't fight the
daemon for the write lock). The dismiss tool POSTs to the daemon —
it needs the active session and the daemon owns that state.
"""
