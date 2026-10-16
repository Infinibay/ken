"""Compact, loss-aware text at Ken's public presentation boundary.

Domain results remain data. This renderer never reorders results, invents source
line numbers for FTS excerpts, or removes interpretation-critical status.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def search_previews(hits: list[dict[str, Any]], root: Path, *, lines: int = 8) -> list[dict[str, Any]]:
    """Attach bounded live-source previews without changing candidate identity/order.

    Legacy search locations come from the index. Label these as live previews,
    never as hash-verified symbol evidence. Prepared evidence has its own verifier.
    """
    from ken import _paths
    out = []
    for hit in hits:
        row = dict(hit)
        path = row.get("path", row.get("file", ""))
        symbols = row.get("symbols") or []
        start = row.get("line") or (symbols[0].get("line") if symbols else None) or 1
        stop = min(start + lines - 1, row.get("line_end") or start + lines - 1)
        try:
            source = _paths.resolve_project_path(root, path)
            selected = []
            with source.open(encoding="utf-8") as stream:
                for lineno in range(1, stop + 1):
                    text = stream.readline(65537)
                    if not text:
                        break
                    if len(text) > 65536:
                        raise ValueError("source line exceeds preview budget; use ken_read")
                    if lineno >= start:
                        selected.append(text.rstrip("\r\n"))
            if selected:
                row["preview"] = {"label": "live source preview", "start_line": start,
                                  "end_line": start + len(selected) - 1, "content": "\n".join(selected)}
            else:
                row["preview_unavailable"] = "indexed location is outside live source; reindex"
        except (OSError, UnicodeError, ValueError) as exc:
            row["preview_unavailable"] = str(exc)
        out.append(row)
    return out


_DIAGNOSTICS = {"score", "ranking_score", "source_hash", "profile_version", "indexed_at",
                "sha256", "content_hash", "fingerprint", "model_fingerprint",
                "timing", "elapsed_ms"}
_LOCATION = {"path", "file_path", "file", "line", "line_start", "start_line", "line_end", "end_line"}
_IDENTITY = {"name", "qualname", "label", "kind"}


def render_compact(value: Any, *, diagnostics: bool = False, tool_name: str = "") -> str:
    """Render native output as text; retain all non-diagnostic information.

    Number only source that carries an actual start line. Empty fields are
    concise but visible, and false/zero values survive (unknown is not absent).
    No global text clipping: callers own search and source budgets.
    """
    if tool_name and not diagnostics:
        from ken.presentation_views import compact_tool_result
        value = compact_tool_result(tool_name, value)
    lines = _lines(value, path="", diagnostics=diagnostics, legacy_numbered=tool_name == "ken_read")
    if (isinstance(value, dict) and isinstance(value.get("path"), str) and len(lines) > 1
            and lines[0] == value["path"] and lines[1].startswith(value["path"] + ":")):
        lines.pop(0)
    return "\n".join(lines) or "No results."


def _scalar(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _start(item: dict[str, Any]) -> int | None:
    for key in ("start_line", "line_start", "line"):
        value = item.get(key)
        if type(value) is int and value > 0:
            return value
    return None


def _lines(value: Any, *, path: str, diagnostics: bool, legacy_numbered: bool = False) -> list[str]:
    if isinstance(value, str):
        return value.split("\n") if value else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for row in value:
            out.extend(_lines(row, path=path, diagnostics=diagnostics, legacy_numbered=legacy_numbered))
        return out
    if not isinstance(value, dict):
        return [_scalar(value)]

    own_path = value.get("path", value.get("file_path", value.get("file", path)))
    if not isinstance(own_path, str):
        own_path = path
    entity = value.get("entity")
    identity = entity if isinstance(entity, dict) else value
    name = identity.get("qualname") or identity.get("name") or value.get("label")
    code_key = next((k for k in ("code", "content", "text", "snippet")
                     if isinstance(value.get(k), str) and _start(value) is not None), None)
    start = _start(value)
    # A wrapper's snippet uses the accompanying symbol's indexed range.
    symbol = value.get("symbol")
    if start is None and isinstance(symbol, dict) and isinstance(value.get("snippet"), str):
        start = _start(symbol)
        name = symbol.get("qualname") or symbol.get("name")
        code_key = "snippet" if start is not None else None
    end = value.get("end_line", value.get("line_end", start))
    partial = False
    code_lines: list[str] = []
    if code_key:
        code = value[code_key]
        code_lines = code.replace("\r\n", "\n").split("\n") if code else []
        # Legacy search.file_snippets already prefixes each line with N:.
        # Its line/line_end schema differs from raw retrieval start_line/content.
        if legacy_numbered and "start_line" not in value and start is not None and code_lines and all(
                line.startswith(f"{start + i}: ") for i, line in enumerate(code_lines)):
            code_lines = [line[len(f"{start + i}: "):] for i, line in enumerate(code_lines)]
        # Empty code claims no source range; do not manufacture a numbered line.
        if code_lines and start is not None:
            shown_end = start + len(code_lines) - 1
            partial = type(end) is int and end > shown_end
            end = shown_end
    title = own_path if own_path and (own_path != path or start is not None or name) else ""
    if start is not None:
        title += f":{start}-{end}" if type(end) is int else f":{start}"
    if name:
        title += (" :: " if title else "") + str(name)
    if identity.get("kind") and title:
        title += f" ({identity['kind']})"
    flags = [k for k in ("stale", "truncated") if value.get(k)]
    if partial:
        flags.append("partial")
    if flags:
        title += " [" + ", ".join(flags) + "]"
    out = [title] if title else []
    consumed = _LOCATION | _IDENTITY if title else {k for k in _LOCATION if value.get(k) == path}
    if isinstance(entity, dict):
        # Preserve entity metadata beyond the identity, e.g. validity or role.
        extra = {k: v for k, v in entity.items() if k not in _LOCATION | _IDENTITY}
        if extra:
            out.extend(_lines(extra, path=own_path, diagnostics=diagnostics, legacy_numbered=legacy_numbered))
        consumed = consumed | {"entity"}
    if code_key:
        consumed = consumed | {code_key}
        if start is not None:
            out.extend(f"{start + i} | {line}" for i, line in enumerate(code_lines))
    columns, rows = value.get("columns"), value.get("rows")
    if (isinstance(columns, list) and all(isinstance(c, str) for c in columns)
            and isinstance(rows, list) and all(isinstance(row, list) and len(row) == len(columns) for row in rows)):
        consumed = consumed | {"columns", "rows"}
        if not rows:
            out.append("rows: none")
        for index, row in enumerate(rows, 1):
            out.append(f"row {index}:")
            for column, cell in zip(columns, row, strict=True):
                if isinstance(cell, (dict, list, tuple)):
                    out.append(f"  {column}:")
                    out.extend("    " + line for line in _lines(cell, path=own_path, diagnostics=diagnostics, legacy_numbered=legacy_numbered))
                else:
                    out.append(f"  {column}: {_scalar(cell)}")
    for key, item in value.items():
        if key in consumed or (key in _DIAGNOSTICS and not diagnostics):
            continue
        if key == "ok" and item is True:
            continue
        if key in flags:
            continue
        if item is None and key in {"status", "complete", "coverage", "validity", "resolved", "matched", "passed"}:
            out.append(f"{key}: none")
            continue
        if item is None or item == "" or item == [] or item == {}:
            # Empty positive result sets and negative/unknown status matter.
            if key in {"results", "matches", "findings", "snippets", "candidates"}:
                out.append(f"{key}: none")
            continue
        if isinstance(item, (dict, list, tuple)):
            children = _lines(item, path=own_path, diagnostics=diagnostics, legacy_numbered=legacy_numbered)
            if children:
                # Common projection envelopes add no information to their rows.
                if key in {"results", "outline", "source", "symbols", "symbol", "snippets", "evidence"}:
                    out.extend(children)
                else:
                    out.append(f"{key}:")
                    out.extend("  " + line for line in children)
        else:
            text = _scalar(item)
            if "\n" in text:
                out.append(f"{key}:")
                out.extend(text.split("\n"))
            else:
                out.append(f"{key}: {text}")
    return out
