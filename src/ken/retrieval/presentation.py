"""Expose only source-verified evidence with honest ranges and output budgets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ken.retrieval.model import CodeMatch, Passage, SearchRequest, SearchResponse
from ken.retrieval.tokenization import code_tokens
from ken.retrieval.intent import interpret


def _window(lines: list[str], passage: Passage, query: set[str], budget: int) -> dict[str, Any]:
    start, end = passage.span.start_line, passage.span.end_line
    focus = max(range(start, end + 1),
                key=lambda line: len(query.intersection(code_tokens(lines[line - 1]))))
    if end - start + 1 > budget:
        start = max(start, min(focus - budget // 2, end - budget + 1))
        end = start + budget - 1
    return {"start_line": start, "end_line": end,
            "content": "\n".join(lines[start - 1:end])}


def present(matches: list[CodeMatch], root: Path, request: SearchRequest, *,
            profile_version: str) -> SearchResponse:
    response = SearchResponse(request.query, [], profile_version)
    query = set(code_tokens(request.query))
    intent = interpret(request)
    seen_files: set[str] = set()
    for match in matches:
        path = match.entity.path
        if request.target == "file" and path in seen_files:
            continue
        if len(response.results) >= request.limit:
            break
        seen_files.add(path)
        first = match.evidence[0]
        result: dict[str, Any] = {
            "path": path, "language": first.language, "entity": match.entity.to_dict(),
            "entity_span": first.entity_span.to_dict(),
            "ranking_score": round(match.score, 8), "source_hash": match.source_hash,
            "evidence": [], "stale": False, "truncated": False,
        }
        source_path = (root / path).resolve()
        try:
            if not source_path.is_relative_to(root.resolve()):
                raise ValueError("source escapes project")
            source = source_path.read_bytes()
            if hashlib.sha256(source).hexdigest() != match.source_hash:
                raise ValueError("source changed")
            lines = source.decode("utf-8").splitlines()
            if any(p.span.end_line > len(lines) for p in match.evidence):
                raise ValueError("invalid source range")
            ordered = sorted(match.evidence, key=lambda p: (
                -(p.implementation_start_line is None or p.span.end_line >= p.implementation_start_line
                  or request.purpose == "documentation"),
                -p.signals.get("cosine_behavior", -1),
                -len(query.intersection(code_tokens(p.fields["body"]))),
                p.span.start_line))
            if intent.identity:
                ordered.sort(key=lambda p: p.span.start_line)
            best = ordered[0]
            lower, upper = best.entity_span.start_line, best.entity_span.end_line
            if best.entity.qualname is None:
                lower, upper = 1, len(lines)
            if upper - lower + 1 > 40 and request.purpose != "documentation" and not intent.identity:
                lower = max(lower, best.implementation_start_line or lower)
            # Context expansion crosses chunk boundaries, never source boundaries.
            # This keeps a try/except or adjacent branches together even if the
            # token budget split their retrieval projections.
            center = (max(lower, best.span.start_line) + best.span.end_line) // 2
            if best.span.end_line - best.span.start_line + 1 > 40:
                focus = max(range(max(lower, best.span.start_line), best.span.end_line + 1),
                            key=lambda line: len(query.intersection(code_tokens(lines[line - 1]))))
                if query.intersection(code_tokens(lines[focus - 1])):
                    center = focus
            start = max(lower, min(center - 19, upper - 39))
            end = min(upper, start + 39)
            result["evidence"] = [{"start_line": start, "end_line": end,
                                   "content": "\n".join(lines[start - 1:end])}]
            result["truncated"] = start > best.entity_span.start_line or end < upper
        except (OSError, ValueError, UnicodeError) as exc:
            result["stale"] = True
            response.warnings.append(f"{path}: {exc}; reindex source before quoting evidence")
        if request.explain:
            result["signals"] = match.signals
        if request.target == "file":
            result["matches"] = [m.entity.to_dict() for m in matches if m.entity.path == path][:10]
        response.results.append(result)
    response.omitted_count = max(0, len(matches) - len(response.results))
    response.truncated = bool(response.omitted_count or any(
        r["truncated"] for r in response.results))
    # Shrink lower-priority evidence, never reorder or substitute another hit.
    def size() -> int:
        return len(json.dumps(response.to_dict(), ensure_ascii=False, separators=(",", ":")))
    while response.results and size() > request.max_chars:
        result = response.results[-1]
        fragments = result["evidence"]
        if len(fragments) > 1:
            fragments.pop()
            result["truncated"] = True
        elif fragments and fragments[0]["start_line"] < fragments[0]["end_line"]:
            fragment = fragments[0]
            # splitlines discards a trailing empty source line, breaking the
            # inclusive range invariant on subsequent trims.
            lines = fragment["content"].split("\n")
            if len(query.intersection(code_tokens(lines[-1]))) > len(query.intersection(code_tokens(lines[0]))):
                fragment["start_line"] += 1
                lines = lines[1:]
            else:
                fragment["end_line"] -= 1
                lines = lines[:-1]
            fragment["content"] = "\n".join(lines)
            result["truncated"] = True
        else:
            response.results.pop()
            response.omitted_count += 1
        response.truncated = True
    return response
