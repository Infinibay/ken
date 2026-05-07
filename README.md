# ken

Per-project context-rank index for Claude Code. Local SQLite, local daemon, no
network. Indexes your codebase, watches it for changes, and feeds Claude a
ranked `<context-rank>` block on every prompt — based on what's been touched
this session, what was useful in past sessions, and what looks semantically
relevant to the request.

```fish
cd my-project
ken install .
claude
```

That's it. Once installed:

- `.ken/ken.db` holds the index for this project.
- `.claude/settings.json` gets hooks pointing at `ken hook ...`.
- When Claude Code starts, `ken serve` is spawned as a background daemon.
- File watcher reindexes on every save.
- `Stop` / `SessionEnd` hooks shut the daemon down (10-minute idle fallback).

## Status

Early WIP. Currently implemented: `ken install` (project scaffold + Python
indexing). Daemon, watcher, embedder, and ranker are stubs.
