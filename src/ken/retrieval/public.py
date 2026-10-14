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


def render(response: dict[str, Any]) -> str:
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
        if entity["qualname"]:
            title += " :: " + entity["qualname"]
        if result.get("stale"):
            title += " [stale]"
        elif result.get("truncated"):
            title += " [partial]"
        parts = [title]
        for i, fragment in enumerate(evidence):
            if i:
                parts.append(f"@{fragment['start_line']}-{fragment['end_line']}")
            parts.append(fragment["content"])
        blocks.append("\n".join(parts))
    if not blocks:
        blocks.append("No matches.")
    if response.get("omitted_count"):
        blocks.append(f"{response['omitted_count']} more results omitted.")
    return "\n\n".join(blocks + response.get("warnings", []))
