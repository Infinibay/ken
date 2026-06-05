"""Near-duplicate / copy-paste detection via MinHash + LSH.

"Where else is this implemented? Is this function copy-pasted?" is a purely
*lexical* question — set-similarity over token shingles, no meaning needed.

For each indexed symbol we read its source live, normalise (strip comments and
whitespace), shingle into overlapping k-grams, and build a MinHash signature.
LSH banding gives near-linear candidate generation; we confirm each candidate
with the estimated Jaccard. Anti-boilerplate floor (min distinct shingles)
keeps tiny identical stubs from flooding the result.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import numpy as np

_NUM_PERM = 64
_BANDS = 16  # rows per band = NUM_PERM / BANDS = 4
_SHINGLE_K = 5
_MIN_SHINGLES = 15
_MAX_HASH = (1 << 61) - 1
_COMMENT = re.compile(r"#.*$|//.*$", re.MULTILINE)
_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[A-Za-z0-9_]+")

# Deterministic permutation coefficients (a*x + b) mod prime.
_RNG = np.random.default_rng(0x5EED)
_A = _RNG.integers(1, _MAX_HASH, size=_NUM_PERM, dtype=np.int64)
_B = _RNG.integers(0, _MAX_HASH, size=_NUM_PERM, dtype=np.int64)


def _read_lines(project_root: Path, rel: str, start: int, end: int) -> str:
    try:
        lines = (project_root.resolve() / rel).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return ""
    return "\n".join(lines[max(0, start - 1): max(start - 1, end)])


def _shingles(source: str) -> set[int]:
    text = _COMMENT.sub("", source)
    tokens = _TOKEN.findall(text.lower())
    if len(tokens) < _SHINGLE_K:
        return set()
    out: set[int] = set()
    for i in range(len(tokens) - _SHINGLE_K + 1):
        gram = " ".join(tokens[i: i + _SHINGLE_K])
        out.add(hash(gram) & _MAX_HASH)
    return out


def _signature(shingles: set[int]) -> np.ndarray:
    arr = np.fromiter(shingles, dtype=np.int64, count=len(shingles))
    # (a * x + b) mod prime, min over shingles, per permutation.
    hashed = (np.outer(_A, arr) + _B[:, None]) % _MAX_HASH
    return hashed.min(axis=1)


def _jaccard(s1: np.ndarray, s2: np.ndarray) -> float:
    return float(np.mean(s1 == s2))


def clones(
    conn,
    path: str | None = None,
    *,
    qualname: str | None = None,
    min_similarity: float = 0.75,
    limit: int = 10,
    project_root: Path | None = None,
) -> dict:
    """Find near-duplicate symbols across the project.

    With *path* (and optionally *qualname*), return clones of that symbol.
    Without a path, return the strongest duplicate pairs project-wide.
    """
    if project_root is None:
        return {"ok": False, "error": "project_root required"}

    rows = conn.execute(
        """
        SELECT s.id, s.qualname, s.name, s.kind, s.line_start, s.line_end, f.path
        FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id
        WHERE s.kind IN ('function', 'method', 'class')
        """
    ).fetchall()

    sigs: dict[int, np.ndarray] = {}
    meta: dict[int, dict] = {}
    for r in rows:
        src = _read_lines(project_root, r["path"], int(r["line_start"]), int(r["line_end"]))
        sh = _shingles(src)
        if len(sh) < _MIN_SHINGLES:
            continue
        sid = int(r["id"])
        sigs[sid] = _signature(sh)
        meta[sid] = {
            "qualname": r["qualname"] or r["name"],
            "file": r["path"],
            "line": int(r["line_start"]),
            "line_end": int(r["line_end"]),
            "size": int(r["line_end"]) - int(r["line_start"]) + 1,
        }
    if not sigs:
        return {"ok": True, "clones": [], "note": "no symbols large enough to compare"}

    rows_per_band = _NUM_PERM // _BANDS
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for sid, sig in sigs.items():
        for b in range(_BANDS):
            band = tuple(sig[b * rows_per_band:(b + 1) * rows_per_band].tolist())
            buckets[(b, band)].append(sid)

    candidate_pairs: set[tuple[int, int]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = sorted((members[i], members[j]))
                candidate_pairs.add((a, b))

    # Targeted query mode.
    if path is not None:
        target = Path(path).as_posix().lstrip("./")
        target_ids = {
            sid for sid, m in meta.items()
            if m["file"] == target and (qualname is None or m["qualname"] == qualname
                                        or m["qualname"].endswith("." + qualname))
        }
        if not target_ids:
            return {"ok": False, "error": "symbol not found / too small to compare",
                    "path": target, "qualname": qualname}
        results = []
        for a, b in candidate_pairs:
            other = b if a in target_ids else (a if b in target_ids else None)
            if other is None:
                continue
            sim = _jaccard(sigs[a], sigs[b])
            if sim >= min_similarity:
                results.append((sim, other))
        results.sort(key=lambda t: -t[0] * meta[t[1]]["size"])
        return {
            "ok": True,
            "path": target,
            "qualname": qualname,
            "clones": [
                {**meta[o], "similarity": round(sim, 3)}
                for sim, o in results[: max(1, int(limit))]
            ],
        }

    # Project-wide mode.
    pairs = []
    for a, b in candidate_pairs:
        sim = _jaccard(sigs[a], sigs[b])
        if sim >= min_similarity:
            pairs.append((sim, a, b))
    pairs.sort(key=lambda t: -t[0] * (meta[t[1]]["size"] + meta[t[2]]["size"]))
    return {
        "ok": True,
        "clones": [
            {
                "similarity": round(sim, 3),
                "a": {"qualname": meta[a]["qualname"], "file": meta[a]["file"], "line": meta[a]["line"]},
                "b": {"qualname": meta[b]["qualname"], "file": meta[b]["file"], "line": meta[b]["line"]},
            }
            for sim, a, b in pairs[: max(1, int(limit))]
        ],
    }
