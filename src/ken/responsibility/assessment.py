"""Combine reasoner contributions into hypotheses and preserve their conditions."""

from dataclasses import asdict
from typing import Any, Sequence

from .model import Inquiry, Reasoner, Symbol
from .reasoners import confidence


def assess_symbol(
    symbol: Symbol,
    formulations: list[str],
    query_terms: list[frozenset[str]],
    similarities: Sequence[float],
    reasoners: tuple[Reasoner, ...],
) -> dict[str, Any]:
    alternatives = []
    for j, wording in enumerate(formulations):
        inquiry = Inquiry(wording, query_terms[j], float(similarities[j]))
        evidence = tuple(
            e for reasoner in reasoners for e in reasoner.assess(inquiry, symbol)
        )
        alternatives.append((confidence(evidence), wording, evidence))
    # Alternative formulations are assumptions, not independent votes.
    rating, wording, evidence = max(alternatives, key=lambda a: a[0]["score"])
    # A weaker paraphrase must not hide a denial or a condition found by
    # another formulation of the same proposed responsibility.
    cautions = tuple(
        dict.fromkeys(
            e
            for _, _, items in alternatives
            for e in items
            if e.direction == "against"
            or e.reasoner in {"documentation_guard", "delegation"}
        )
    )
    evidence = tuple(dict.fromkeys((*evidence, *cautions)))
    rating = confidence(evidence)
    assumptions = list(dict.fromkeys(e.assumption for e in evidence if e.assumption))
    if wording != formulations[0]:
        assumptions.insert(
            0,
            "This supplied formulation preserves the question's meaning: " + wording,
        )
    denied = any(e.direction == "against" for e in evidence)
    inspect: dict[str, Any] = {
        "tool": "ken_read",
        "path": symbol.path,
        "include": ["source"],
    }
    if symbol.kind == "module":
        inspect.update(start_line=symbol.line, end_line=symbol.end_line)
    else:
        inspect["qualname"] = symbol.qualname
    return {
        "symbol": symbol.qualname,
        "path": symbol.path,
        "line": symbol.line,
        "kind": symbol.kind,
        "status": "counterevidence" if denied else "hypothesis",
        "confidence": rating,
        "matched_formulation": wording,
        "documentation": symbol.documentation[:900],
        "evidence": [asdict(e) for e in evidence],
        "assumptions": assumptions,
        "source": {
            "sha256": symbol.sha256,
            "index_changed": symbol.refreshed,
            "documentation_scope": symbol.doc_scope,
            "documentation_kind": f"{symbol.kind}_docstring",
            "behavior_verified": False,
        },
        "inspect": inspect,
    }


def present(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    scope: str,
    indexed_count: int,
    inspected_count: int,
    include_tests: bool,
    issues: list[dict[str, str]],
    hypotheses: list[str],
) -> dict[str, Any]:
    candidates.sort(key=lambda c: (-c["confidence"]["score"], c["path"], c["line"]))
    plausible = [
        c
        for c in candidates
        if c["confidence"]["score"] >= 0.4 and c["status"] == "hypothesis"
    ]
    selected = plausible[:limit]
    close = (
        len(plausible) > 1
        and plausible[0]["confidence"]["score"] - plausible[1]["confidence"]["score"]
        < 0.08
    )
    return {
        "ok": True,
        "question": question.strip(),
        "hypotheses": hypotheses,
        "status": "ambiguous" if close else "candidates" if selected else "unknown",
        "candidates": selected,
        "counterevidence": [c for c in candidates if c["status"] == "counterevidence"][
            :limit
        ],
        "assessment": {
            "kind": "heuristic",
            "calibrated": False,
            "probability": None,
            "note": "Scores rank hypotheses; they are not probabilities of correctness. Documentation and call sites do not prove behavior.",
        },
        "coverage": {
            "scope": scope,
            "indexed_symbols": indexed_count,
            "inspected_symbols": inspected_count,
            "candidate_limit": 40,
            "exhaustive": False,
            "include_tests": include_tests,
            "sources": [
                "module_docstrings",
                "class_docstrings",
                "method_docstrings",
                "function_docstrings",
            ],
            "findings_used": False,
            "issues": issues,
            "note": "Index retrieval can miss new symbols or concepts absent from the indexed docstring excerpt. Cross-language quality depends on the configured embedder.",
        },
    }
