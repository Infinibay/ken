"""Stable evidence response and actionable preparation errors for CLI and MCP."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ken.retrieval.embedding_store import IndexVersionError
from ken.retrieval.model import SearchRequest
from ken.retrieval.service import search


def find(conn: sqlite3.Connection, root: Path, query: str, *, scope: str = "symbols",
         purpose: str = "auto", limit: int = 10, max_chars: int = 12000,
         explain: bool = False) -> dict[str, Any]:
    if scope not in ("files", "symbols"):
        raise ValueError("evidence responses require scope=files or symbols")
    request = SearchRequest(query, target="file" if scope == "files" else "symbol",
                            purpose=purpose, limit=limit, max_chars=max_chars, explain=explain)
    try:
        return search(conn, root, request).to_dict()
    except IndexVersionError as exc:
        return {"ok": False, "code": "retrieval_index_required", "error": str(exc),
                "next_action": "Run ken retrieval index --path PROJECT --profile PROFILE.json, then retry.",
                "results": []}


def find_best(conn: sqlite3.Connection, root: Path, query: str, *, scope: str = "symbols",
              purpose: str = "auto", limit: int = 10, max_chars: int = 12000,
              explain: bool = False, piece_kind: str = "auto") -> dict[str, Any]:
    """Normal CLI/MCP search with the complete generic production engine."""
    from ken.retrieval.best_search import search_best
    from ken.retrieval.intent import requested_piece_kind
    from ken.model_assets import ModelPreparationError
    if scope not in ("files", "symbols"):
        raise ValueError("best search requires scope=files or symbols")
    if piece_kind not in ("auto", "class", "module", "symbol", "file"):
        raise ValueError("unknown requested piece kind")
    inferred = requested_piece_kind(SearchRequest(query))
    selected = (piece_kind if piece_kind != "auto" else
                inferred if inferred in {"class", "module", "file"} else None)
    request = SearchRequest(query, target="file" if scope == "files" else "symbol",
        purpose=purpose, limit=limit, max_chars=max_chars, explain=explain, piece_kind=selected)
    try:
        return search_best(conn, root, request).to_dict()
    except (IndexVersionError, ModelPreparationError) as exc:
        return {"ok": False, "code": "search_preparation_required", "error": str(exc),
            "next_action": "Run ken retrieval prepare --path PROJECT, then retry.", "results": []}


def render(response: dict[str, Any], *, diagnostics: bool = False) -> str:
    """Render verified results as compact text without changing the evidence."""
    if response.get("ok") is False:
        return response["error"] + "\n" + response["next_action"]
    blocks = []
    for result in response["results"]:
        entity = result["entity"]
        evidence = result["evidence"]
        title = result["path"]
        if evidence:
            title += f":{evidence[0]['start_line']}-{evidence[0]['end_line']}"
        if entity.get("qualname"):
            title += " :: " + entity["qualname"]
        if result.get("piece_kind") in {"class", "module", "file"}:
            title += " (" + result["piece_kind"] + ")"
        if result.get("stale"):
            title += " [stale]"
        elif result.get("truncated"):
            title += " [partial]"
        parts = [title]
        for i, fragment in enumerate(evidence):
            if i:
                parts.append(f"@{fragment['start_line']}-{fragment['end_line']}")
            parts.extend(f"{fragment['start_line'] + offset} | {line}"
                         for offset, line in enumerate(fragment["content"].split("\n")))
        if diagnostics and result.get("signals"):
            import json
            parts.append("signals: " + json.dumps(result["signals"], ensure_ascii=False, sort_keys=True))
        blocks.append("\n".join(parts))
    if not blocks:
        blocks.append("No matches.")
    if response.get("omitted_count"):
        blocks.append(f"{response['omitted_count']} more results omitted.")
    return "\n\n".join(blocks + response.get("warnings", []))
