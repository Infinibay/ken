"""Distinctive-term responsibility briefs (file & directory).

Answers "what is this file/package *for*, and what distinguishes it from its
siblings?" with extractive statistics — every word is a real token from the
index, so the agent can verify it. No summarisation, no LLM.

Method: Monroe et al. (2008) **weighted log-odds-ratio with an informative
Dirichlet prior**. More trustworthy than TF-IDF or topic models on the small
corpora ken indexes: the prior shrinks rare-term noise and the z-score makes
"distinctive" comparable across documents of different sizes.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

# Identifier-aware tokenisation: split snake_case, camelCase, dotted names.
_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "self", "return",
    "none", "true", "false", "init", "str", "int", "list", "dict", "test",
    "get", "set", "py", "ts", "js",
}


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for chunk in _SPLIT.split(text or ""):
        for piece in _CAMEL.split(chunk):
            tok = piece.lower()
            if len(tok) >= 3 and tok not in _STOP and not tok.isdigit():
                out.append(tok)
    return out


def _doc_terms(conn, file_ids: list[int]) -> Counter:
    counts: Counter = Counter()
    if not file_ids:
        return counts
    qs = ",".join("?" for _ in file_ids)
    for r in conn.execute(
        f"SELECT name, qualname, docstring FROM ci_symbols WHERE file_id IN ({qs})",
        tuple(file_ids),
    ):
        counts.update(_tokens(f"{r['name']} {r['qualname'] or ''} {r['docstring'] or ''}"))
    for r in conn.execute(
        f"SELECT text FROM ci_intent_sources WHERE file_id IN ({qs})", tuple(file_ids)
    ):
        counts.update(_tokens(r["text"]))
    return counts


def profile(conn, path: str, *, granularity: str = "file", top_terms: int = 12) -> dict:
    """Return the distinguishing vocabulary of a file or directory."""
    target = Path(path).as_posix().lstrip("./") if path else ""
    rows = [(int(r["id"]), r["path"]) for r in conn.execute("SELECT id, path FROM ci_files")]
    by_path = {p: i for i, p in rows}

    if granularity == "dir":
        target_ids = [i for i, p in rows if p == target or p.startswith(target.rstrip("/") + "/")]
        label = target.rstrip("/") or "(root)"
    else:
        if target not in by_path:
            return {"ok": False, "error": "file not indexed", "path": target}
        target_ids = [by_path[target]]
        label = target
    if not target_ids:
        return {"ok": False, "error": "no indexed files under path", "path": target}

    target_set = set(target_ids)
    rest_ids = [i for i, _ in rows if i not in target_set]

    counts_t = _doc_terms(conn, target_ids)
    counts_r = _doc_terms(conn, rest_ids)
    n_t = sum(counts_t.values())
    n_r = sum(counts_r.values())
    if n_t == 0:
        return {"ok": True, "label": label, "granularity": granularity,
                "distinguishing_terms": [], "evidence_strength": "none",
                "note": "no indexable terms (no symbols/docstrings)"}

    # Informative Dirichlet prior from the global corpus frequencies.
    global_counts = counts_t + counts_r
    n_all = n_t + n_r
    alpha0 = 1000.0  # prior strength
    vocab = set(counts_t) | set(counts_r)

    scored: list[tuple[float, str, int]] = []
    for w in vocab:
        a_w = alpha0 * (global_counts[w] / n_all) if n_all else 0.0
        y_t = counts_t.get(w, 0)
        y_r = counts_r.get(w, 0)
        # log-odds in target vs rest, each smoothed by the prior
        num_t = y_t + a_w
        den_t = n_t + alpha0 - y_t - a_w
        num_r = y_r + a_w
        den_r = n_r + alpha0 - y_r - a_w
        if den_t <= 0 or den_r <= 0 or num_t <= 0 or num_r <= 0:
            continue
        delta = math.log(num_t / den_t) - math.log(num_r / den_r)
        var = 1.0 / num_t + 1.0 / num_r
        z = delta / math.sqrt(var) if var > 0 else 0.0
        if z > 0:
            scored.append((z, w, y_t))

    scored.sort(key=lambda t: -t[0])
    terms = [{"term": w, "z": round(z, 2), "count": c} for z, w, c in scored[: max(1, int(top_terms))]]

    strength = "strong" if n_t >= 200 else "moderate" if n_t >= 40 else "thin"
    return {
        "ok": True,
        "label": label,
        "granularity": granularity,
        "files": len(target_ids),
        "term_count": n_t,
        "evidence_strength": strength,
        "distinguishing_terms": terms,
    }
