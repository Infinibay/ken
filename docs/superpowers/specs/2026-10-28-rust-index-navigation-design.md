# Native index navigation

Continue the Rust migration on Linux x86_64 by completing one model-free public
navigation block. The user authorizes independent implementation and explicitly
prefers larger implementation batches with one combined validation per block.

`IndexNavigation` reads existing file/symbol/import/intent rows and current source.
It owns outlines, symbol details, source snippets, import graphs, likely-test
ranking, neighbors and project overview. It opens existing SQLite databases
read-only; each public call observes a fresh database, without a model installation.
Source reads reuse the confined regular-file reader and preserve Python's newline,
replacement-decoding, character budgets and numbered-line semantics.

`ToolDocument` preserves object order for both JSON serialization and compact
presentation. Domain functions own fields, ordering and limits; presentation only
projects them. This avoids changing serde_json features globally or encoding
domain-specific field precedence in a generic renderer.

CLI `ken-rs tools read/related/find` and MCP `ken_read`, `ken_related` and
`ken_find(scope="tests")` share the same navigation application. Read supports
symbols/imports/docstrings/source; related supports neighbors/imports. Other
capabilities remain explicitly unavailable, including read profile and other
relationships. Existing default file/symbol search remains separate.

Preserve frozen original behavior through newly observed navigation cases before
implementation. Original indexing/model tests and accepted observations must not
be repeated. Record raw observations locally; only the compact essential fixture
belongs in Git. Retain established numerical tolerances, source identities and
the pending Intel/SkylakeX acceptance limits.

Implementation runs inline as one functional batch, with one combined targeted
validation (navigation library/CLI/MCP, existing CLI/status, fmt and strict lint).
Repeat focused checks for concrete failures; broader CPU matrices and evidence
archives remain milestone work. One final read-only review covers this block.
