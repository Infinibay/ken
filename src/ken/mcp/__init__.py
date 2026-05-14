"""ken's MCP (Model Context Protocol) server.

Spawned over stdio when the project's MCP config registers ken. Exposes
read-only code intelligence tools plus memory/rank feedback tools:

  * ``ken_search_files(query, limit=8)`` — semantically rank indexed
    files against the query (cosine sweep on ``ci_files.embedding``).
  * ``ken_search_symbols(query, limit=10)`` — same but for symbols
    (functions / classes / methods).
  * ``ken_file_symbols(path, include_docstrings=True)`` — return every
    indexed symbol for one project-relative file path.
  * ``ken_file_outline(path, ...)`` — return one file's symbols/imports.
  * ``ken_file_neighbors(path, limit=20)`` — imports, importers, and
    likely tests for a file.
  * ``ken_symbol_detail(path, qualname, include_snippet=False)`` — one
    symbol's indexed metadata and optional source.
  * ``ken_module_graph(path, depth=1)`` — bounded local import graph.
  * ``ken_find_tests(path, limit=20)`` — likely tests for a file.
  * ``ken_changed_context()`` — git status enriched with indexed
    symbols and likely tests.
  * ``ken_file_snippets(path, symbols=[...])`` — source snippets by
    symbol or line range.
  * ``ken_project_overview(depth=2)`` — compact index overview.
  * ``ken_remember(topic, content, tags=[], kind=None)`` — write a note
    into ``cr_findings`` so future sessions can recall it.
  * ``ken_forget(topic)`` — delete a saved finding by exact topic.
  * ``ken_findings(limit=20, tag=None)`` — list recent saved findings.
  * ``ken_recall(query, limit=5, min_score=0.25)`` — search findings by
    similarity, omitting weak nearest-neighbor matches by default.
  * ``ken_rank(query="", verbose=1)`` — render or recompute ranked
    context.
  * ``ken_explain_rank(query="")`` — show per-channel rank evidence.
  * ``ken_dismiss(target, reason="")`` — explicit "this wasn't what I
    was looking for" signal. Talks to the daemon (uses the active
    session's id) so the negative pattern weighs into future
    predictive ranking.

Read-only tools query SQLite directly (WAL means we don't fight the
daemon for the write lock). The dismiss tool POSTs to the daemon —
it needs the active session and the daemon owns that state.
"""
