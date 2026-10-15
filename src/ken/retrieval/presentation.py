"""Expose only source-verified evidence with honest ranges and output budgets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ken.retrieval.model import CodeMatch, SearchRequest, SearchResponse
from ken.retrieval.tokenization import code_tokens
from ken.retrieval.intent import interpret
from ken.retrieval.evidence import entity_extent, source_bounds, verified_lines


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
        try:
            lines = verified_lines(root, match)
            extent = entity_extent(match)
            result["entity_span"] = extent.to_dict()
            ordered = sorted(match.evidence, key=lambda p: (
                -(p.implementation_start_line is None or p.span.end_line >= p.implementation_start_line
                  or request.purpose == "documentation"),
                -p.signals.get("joint_evidence", float("-inf")),
                -p.signals.get("cosine_behavior", -1),
                -len(query.intersection(code_tokens(p.fields["body"]))),
                p.span.start_line))
            if intent.identity:
                ordered.sort(key=lambda p: p.span.start_line)
            best = ordered[0]
            bounds = source_bounds(match, best, len(lines),
                implementation=request.purpose != "documentation" and not intent.identity)
            lower, upper = bounds.start_line, bounds.end_line
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
            if best.signals.get("selected_window"):
                start, end = best.span.start_line, best.span.end_line
            result["evidence"] = [{"start_line": start, "end_line": end,
                                   "content": "\n".join(lines[start - 1:end])}]
            result["truncated"] = start > extent.start_line or end < extent.end_line
            selected = [p for p in match.evidence if p.signals.get("selected_window")]
            if selected:
                result["evidence"] = [{"start_line": p.span.start_line, "end_line": p.span.end_line,
                    "content": "\n".join(lines[p.span.start_line-1:p.span.end_line])}
                    for p in sorted(selected, key=lambda p: p.span.start_line)]
                shown = sum(p.span.end_line - p.span.start_line + 1 for p in selected)
                if shown > 40:
                    raise ValueError("selected evidence exceeds line budget")
                result["truncated"] = shown < extent.end_line - extent.start_line + 1
            if match.signals.get('exact') and not intent.identity and not selected:
                declaration = extent.start_line
                body = result['evidence'][0]
                if declaration < body['start_line']:
                    width = min(8,max(1,len(first.fields.get('signature','').split('\n'))),
                                body['start_line']-declaration)
                    body['end_line'] = min(body['end_line'],body['start_line']+39-width)
                    body['content'] = '\n'.join(lines[body['start_line']-1:body['end_line']])
                    result['evidence'].insert(0,{'start_line':declaration,'end_line':declaration+width-1,
                        'content':'\n'.join(lines[declaration-1:declaration+width-1])})
        except (OSError, ValueError, UnicodeError) as exc:
            result["evidence"] = []
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
