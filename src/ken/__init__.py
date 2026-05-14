"""ken — local context retrieval for coding agents.

The package maintains a per-project SQLite index of files, symbols,
session interactions, and durable findings. Hooks and MCP tools use that
index to surface compact, ranked context before an agent spends tokens
rediscovering the codebase.
"""

__version__ = "0.1.3"
