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
    if response.get("ok") is False:
        return response["error"] + "\n" + response["next_action"]
    blocks = []
    for result in response["results"]:
        entity = result["entity"]
        title = result["path"] + (" :: " + entity["qualname"] if entity["qualname"] else "")
        evidence = result["evidence"]
        if evidence:
            title += " (" + ", ".join(f"{e['start_line']}-{e['end_line']}" for e in evidence) + ")"
        blocks.append(title + "\n" + "\n".join(e["content"] for e in evidence))
    return "\n\n".join(blocks + response.get("warnings", []))
