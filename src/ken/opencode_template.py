"""Generate / merge `opencode.json` MCP entries for ken.

OpenCode (https://opencode.ai) reads its project config from
``<project>/opencode.json`` (or ``opencode.jsonc``). It supports both
plain JSON and JSONC — comments and trailing commas — so the file we
edit may already contain user-authored notes we must preserve.

Unlike Claude Code or Codex, OpenCode has no hook lifecycle equivalent
to ``SessionStart`` / ``UserPromptSubmit``: the documented extension
mechanism for "give the agent extra tools" is the MCP server block in
``opencode.json``. So the wiring here is deliberately narrower than the
other two:

* Register ``ken`` as a **local** MCP server
  (``type: "local"``, ``command: ["ken", "mcp"]``, ``enabled: true``).
* Preserve every other top-level key the user already has.

We never write ``opencode.json`` from scratch when the file exists —
the read-merge-write path uses a tiny JSONC stripper because opencode's
own format spec allows comments and trailing commas (see its schema,
``allowComments: true``, ``allowTrailingCommas: true``), and Python's
``json`` module does not.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

# The exact MCP entry we want under ``mcp.ken`` in ``opencode.json``.
# Mirrors the canonical example in the opencode docs for a local server.
KEN_OPENCODE_MCP_ENTRY: dict[str, Any] = {
    "type": "local",
    "command": ["ken", "mcp"],
    "enabled": True,
}


def merge_opencode_config(
    existing: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    """Return ``(merged_config, touched)``.

    ``touched`` is True if the ``mcp.ken`` block we want is not already
    present (either missing entirely or shaped differently). On no-op
    re-installs we report ``touched=False`` so the CLI can say "already
    wired — left alone" instead of pretending it changed something.
    """
    merged = deepcopy(existing) if existing else {}
    mcp_section = merged.setdefault("mcp", {})
    if mcp_section.get("ken") == KEN_OPENCODE_MCP_ENTRY:
        return merged, False
    mcp_section["ken"] = deepcopy(KEN_OPENCODE_MCP_ENTRY)
    return merged, True


def remove_ken_mcp_entry(existing: dict[str, Any]) -> dict[str, Any]:
    """Inverse of merge: drop only the ``mcp.ken`` key we own.

    Leaves any sibling MCP servers the user registered alone. If the
    ``mcp`` object becomes empty we drop it too, so the file remains
    clean for `ken uninstall`'s "delete the file if empty" step.
    """
    out = deepcopy(existing)
    mcp_section = out.get("mcp")
    if not isinstance(mcp_section, dict):
        return out
    mcp_section.pop("ken", None)
    if not mcp_section:
        out.pop("mcp", None)
    return out


def read_opencode_jsonc(path: Path) -> dict[str, Any] | None:
    """Read an opencode config file, tolerating JSONC syntax.

    Returns ``None`` if the file is missing. Raises ``SystemExit`` (via
    the caller) on parse failure — an unreadable ``opencode.json`` is a
    project-level config error, not something we should silently overwrite.

    The stripper is intentionally small: it removes ``//`` line comments
    and ``/* ... */`` block comments, then drops trailing commas. It is
    NOT a full JSONC implementation — opencode's parser accepts a strict
    superset of what we generate, but no one in practice writes things
    like strings containing ``*/`` or escaped Unicode in their project
    config, so the subset is fine for the install / uninstall path.
    """
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    return json.loads(_strip_jsonc_comments(raw))


def write_opencode_json(path: Path, config: dict[str, Any]) -> None:
    """Write the config back as plain JSON (indent=2, trailing newline).

    We don't emit JSONC ourselves — the file opencode reads is canonical
    JSON written by ken, and any comments the user added will have been
    stripped by ``read_opencode_jsonc``. That is an acceptable loss for
    a managed block: the comments are not part of any schema opencode
    understands, and re-running ``ken install`` is rare enough that
    "your comment above the ken block got dropped" is acceptable noise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


# ── JSONC helpers ────────────────────────────────────────────────

# We need a string-aware scanner rather than a regex-based stripper.
# JSONC allows ``//`` and ``/* */`` comments anywhere *outside* string
# literals; a naive regex would happily eat a ``//`` that is part of a
# URL like ``"https://x"`` and corrupt the result. So we walk the text
# once, tracking whether we are inside a string, and replace comments
# with whitespace (preserving column alignment for nicer error messages
# — not strictly required, but cheap).


def _strip_jsonc_comments(text: str) -> str:
    """Drop JSONC comments and trailing commas, preserving strings.

    Walks *text* once. Inside a JSON string literal, characters are
    emitted unchanged (so ``"https://x"`` survives intact, including any
    ``//`` it contains). Outside a string, ``//...\\n`` and
    ``/* ... */`` become spaces and the newline is preserved (so the
    parser's line numbers still match the original file). Trailing
    commas before ``}`` or ``]`` are removed.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        # Outside a string:
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                # line comment — drop up to (but keeping) the newline.
                j = text.find("\n", i)
                if j == -1:
                    return _drop_trailing_commas("".join(out) + " " * (n - i))
                out.append(" " * (j - i))
                i = j
                continue
            if nxt == "*":
                # block comment — drop until closing */.
                end = text.find("*/", i + 2)
                if end == -1:
                    # Unterminated: treat the rest of the file as comment.
                    out.append(" " * (n - i))
                    i = n
                    continue
                out.append(" " * (end + 2 - i))
                i = end + 2
                continue
        out.append(ch)
        i += 1
    return _drop_trailing_commas("".join(out))


def _drop_trailing_commas(text: str) -> str:
    """Remove ``,`` immediately followed by whitespace and a closing ``}`` or ``]``."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
