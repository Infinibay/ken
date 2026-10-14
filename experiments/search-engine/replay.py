"""Restore frozen development candidate pools without consulting relevance labels."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ken.db import connect, init_schema
from ken.retrieval.model import Candidate, CodeMatch, EntityKey, merge_spans
from ken.retrieval.storage import load_passage_map
from ken.parsers import detect_language
from ken.retrieval.model import SearchRequest
from ken.retrieval.candidates import _exact
from ken.retrieval.roles import classify_role


def load_pools(folder: Path, cases: dict, *, roots: dict[str, Path] | None = None,
               refresh_metadata: bool = False, refresh_exact: bool = False,
               refresh_roles: bool = False) -> dict[str, list[Candidate]]:
    rows = [json.loads(line) for line in (folder / "candidates.jsonl").read_text().splitlines()]
    result = {}
    for repo in sorted({cases[row["id"]]["repo_id"] for row in rows}):
        conn = connect(folder / "indices" / (repo + ".db"))
        init_schema(conn)
        passages = load_passage_map(conn)
        if (refresh_metadata or refresh_roles) and roots is not None:
            parsed = {}
            for pid, passage in passages.items():
                path = passage.entity.path
                if path not in parsed:
                    detected = detect_language(Path(path))
                    scopes = detected[1]((roots[repo] / path).read_bytes(), path).scopes if detected else []
                    parsed[path] = {(s.symbol.kind, s.symbol.qualname, s.symbol.line_start,
                                     s.symbol.line_end): s for s in scopes}
                scope = parsed[path].get((passage.entity.kind, passage.entity.qualname,
                    passage.entity_span.start_line, passage.entity_span.end_line))
                passages[pid] = replace(passage,
                    implementation_start_line=(scope.implementation_start_line
                        if scope is not None and refresh_metadata else passage.implementation_start_line),
                    role=(classify_role(path, passage.entity.qualname, scope.annotations if scope else ())
                          if refresh_roles else passage.role))
        by_key = {(p.entity, p.span.start_line, p.span.end_line): p
                  for p in passages.values()}
        from collections import defaultdict
        regions = defaultdict(list)
        for passage in passages.values():
            regions[passage.entity].append(passage.span)
        for row in rows:
            if cases[row["id"]]["repo_id"] != repo:
                continue
            candidates = []
            for record in row["candidates"]:
                owned = [replace(by_key[(EntityKey(record["path"], **record["entity"]),
                    span["start_line"], span["end_line"])], signals=span["signals"])
                    for span in record["passages"]]
                candidates.append(Candidate(owned[0].entity, owned, record["signals"],
                                            merge_spans(regions[owned[0].entity])))
            result[row["id"]] = candidates
            if refresh_exact:
                exact = _exact(conn, passages, SearchRequest(cases[row["id"]]["query"]))
                if len(exact) == 1:
                    exact[0].signals["rrf"] = 1
                    exact[0].owned_regions = merge_spans(regions[exact[0].entity])
                    result[row["id"]] = exact
        conn.close()
    return result


def restore_matches(row: dict, pool: list[Candidate]) -> list[CodeMatch]:
    """Restore saved judgments without changing owner, score or evidence identity."""
    candidates = {candidate.entity: candidate for candidate in pool}
    matches = []
    for saved in row["matches"]:
        entity = EntityKey(saved["path"], **saved["entity"])
        candidate = candidates[entity]
        by_span = {(p.span.start_line, p.span.end_line): p for p in candidate.passages}
        evidence = [replace(by_span[(p["start_line"], p["end_line"])], signals=p["signals"])
                    for p in saved["evidence"]]
        matches.append(CodeMatch(entity, saved["score"], evidence, evidence[0].source_hash,
                                 saved["signals"], candidate.owned_regions))
    return matches
