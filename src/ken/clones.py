"""Near-duplicate / copy-paste detection via MinHash + LSH.

"Where else is this implemented? Is this function copy-pasted?" is a purely
*lexical* question — set-similarity over token shingles, no meaning needed.

For each indexed symbol we read its source live, normalise (strip comments and
whitespace), shingle into overlapping k-grams, and build a MinHash signature.
LSH banding gives near-linear candidate generation; each surviving candidate is
then scored with the **exact** Jaccard over the retained shingle sets — MinHash
is used for *retrieval*, never for the final number. Anti-boilerplate floor
(min distinct shingles) keeps tiny identical stubs from flooding the result.

Three properties this module is careful about:

* **Determinism.** Shingles are hashed with blake2b, not Python's ``hash()``,
  which is salted per process (PYTHONHASHSEED) and would hand back different
  signatures — and therefore different LSH buckets and different results — on
  every run.
* **Exact modular arithmetic.** The permutation family ``(a·x + b) mod p`` is
  evaluated over 31-bit values with the Mersenne prime ``2**31 - 1`` so every
  product stays inside int64. 61-bit constants silently wrap in numpy and stop
  being a permutation at all.
* **Threshold-aware banding.** Band/row counts are derived from the caller's
  ``min_similarity`` so recall stays ≥ 98% at that threshold. A fixed 16×4
  banding is tuned for ~0.75 and silently misses ~36% of true pairs at 0.5.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

_NUM_PERM = 64
_SHINGLE_K = 5
_MIN_SHINGLES = 15
# Mersenne prime. Shingle hashes and the permutation coefficients are all
# < 2**31, so a*x + b < 2**62 and int64 arithmetic is exact (never wraps).
_PRIME = (1 << 31) - 1
# Polynomial base for combining K token hashes into one shingle hash.
_POLY_BASE = 1_000_003
# LSH buckets larger than this are boilerplate families; expanding them would
# emit O(m^2) pairs. Skipped, and reported in the output when it happens.
_MAX_BUCKET = 100
# Recall we insist on at the caller's threshold when picking bands/rows.
_TARGET_RECALL = 0.98

_COMMENT = re.compile(r"#.*$|//.*$", re.MULTILINE)
_TOKEN = re.compile(r"[A-Za-z0-9_]+")

# Deterministic permutation coefficients (a*x + b) mod _PRIME.
_RNG = np.random.default_rng(0x5EED)
_A = _RNG.integers(1, _PRIME, size=_NUM_PERM, dtype=np.int64)
_B = _RNG.integers(0, _PRIME, size=_NUM_PERM, dtype=np.int64)

# token -> stable 31-bit hash. Tokens repeat heavily across a repo, so this
# cache turns the per-shingle hashing cost into a per-distinct-token one.
_TOKEN_HASH: dict[str, int] = {}


def _token_hash(token: str) -> int:
    """Stable 31-bit hash of one token (process-independent, unlike ``hash``)."""
    cached = _TOKEN_HASH.get(token)
    if cached is None:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        cached = int.from_bytes(digest, "big") % _PRIME
        _TOKEN_HASH[token] = cached
    return cached


def _read_lines(project_root: Path, rel: str, start: int, end: int) -> str:
    try:
        lines = (project_root.resolve() / rel).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return ""
    return "\n".join(lines[max(0, start - 1): max(start - 1, end)])


def _shingles(source: str) -> set[int]:
    """Hashes of the overlapping token k-grams of *source*.

    The k token hashes of a window are folded with a polynomial hash, reducing
    mod ``_PRIME`` at every step so the intermediates never leave int64.
    """
    text = _COMMENT.sub("", source)
    tokens = _TOKEN.findall(text.lower())
    n_windows = len(tokens) - _SHINGLE_K + 1
    if n_windows < 1:
        return set()
    toks = np.fromiter(
        (_token_hash(t) for t in tokens), dtype=np.int64, count=len(tokens)
    )
    acc = np.zeros(n_windows, dtype=np.int64)
    for j in range(_SHINGLE_K):
        acc = (acc * _POLY_BASE + toks[j: j + n_windows]) % _PRIME
    return set(acc.tolist())


def _signature(shingles: set[int]) -> np.ndarray:
    arr = np.fromiter(shingles, dtype=np.int64, count=len(shingles))
    # (a * x + b) mod p, min over shingles, per permutation. Exact in int64:
    # a < 2**31 and x < 2**31, so the product stays below 2**62.
    hashed = (np.outer(_A, arr) + _B[:, None]) % _PRIME
    return hashed.min(axis=1)


def _lsh_params(threshold: float, num_perm: int = _NUM_PERM) -> tuple[int, int]:
    """Pick ``(bands, rows)`` for an LSH banding tuned to *threshold*.

    A pair with true similarity ``s`` becomes a candidate with probability
    ``1 - (1 - s**rows)**bands``. We take the banding that keeps that ≥
    ``_TARGET_RECALL`` at the threshold while minimising the false-positive
    rate well below it (fewer wasted exact comparisons). Falls back to the
    highest-recall banding if no candidate meets the recall target.
    """
    s = min(0.999, max(0.01, float(threshold)))
    best: tuple[float, int, int] | None = None
    fallback: tuple[float, int, int] | None = None
    for rows in range(1, num_perm + 1):
        bands = num_perm // rows
        if bands < 1:
            break
        recall = 1.0 - (1.0 - s**rows) ** bands
        # False-positive pressure: how often a clearly-dissimilar pair (half
        # the requested similarity) still has to be verified exactly.
        false_pos = 1.0 - (1.0 - (0.5 * s) ** rows) ** bands
        if fallback is None or recall > fallback[0]:
            fallback = (recall, bands, rows)
        if recall < _TARGET_RECALL:
            continue
        if best is None or false_pos < best[0]:
            best = (false_pos, bands, rows)
    if best is not None:
        return best[1], best[2]
    assert fallback is not None
    return fallback[1], fallback[2]


def _exact_similarity(a: set[int], b: set[int]) -> tuple[float, float]:
    """``(jaccard, containment)`` over the true shingle sets.

    Containment is ``|A ∩ B| / min(|A|, |B|)`` — it stays high when a small
    function is pasted verbatim inside a much larger one, a case Jaccard
    penalises for the size gap alone.
    """
    if not a or not b:
        return 0.0, 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0, 0.0
    union = len(a) + len(b) - inter
    return inter / union, inter / min(len(a), len(b))


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

    Reported ``similarity`` is the exact Jaccard of the token-shingle sets,
    not the MinHash estimate; ``containment`` is the share of the smaller
    symbol's shingles found in the larger one.
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
    shingles: dict[int, set[int]] = {}
    meta: dict[int, dict] = {}
    for r in rows:
        src = _read_lines(project_root, r["path"], int(r["line_start"]), int(r["line_end"]))
        sh = _shingles(src)
        if len(sh) < _MIN_SHINGLES:
            continue
        sid = int(r["id"])
        sigs[sid] = _signature(sh)
        shingles[sid] = sh
        meta[sid] = {
            "qualname": r["qualname"] or r["name"],
            "file": r["path"],
            "line": int(r["line_start"]),
            "line_end": int(r["line_end"]),
            "size": int(r["line_end"]) - int(r["line_start"]) + 1,
        }
    if not sigs:
        return {"ok": True, "clones": [], "note": "no symbols large enough to compare"}

    bands, rows_per_band = _lsh_params(min_similarity)
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for sid, sig in sigs.items():
        for b in range(bands):
            band = tuple(sig[b * rows_per_band:(b + 1) * rows_per_band].tolist())
            buckets[(b, band)].append(sid)

    candidate_pairs: set[tuple[int, int]] = set()
    skipped_buckets = 0
    for members in buckets.values():
        if len(members) < 2:
            continue
        if len(members) > _MAX_BUCKET:
            skipped_buckets += 1
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = sorted((members[i], members[j]))
                candidate_pairs.add((a, b))

    note = None
    if skipped_buckets:
        note = (
            f"{skipped_buckets} LSH bucket(s) held more than {_MAX_BUCKET} "
            "near-identical symbols (boilerplate) and were not expanded"
        )

    # Targeted query mode.
    if path is not None:
        target = _normalize(path)
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
            hit = a if a in target_ids else (b if b in target_ids else None)
            other = b if hit == a else (a if hit == b else None)
            if hit is None or other is None:
                continue
            sim, contain = _exact_similarity(shingles[a], shingles[b])
            if sim >= min_similarity:
                # The smaller of the two bounds how much code they can share —
                # the same measure the project-wide mode ranks by.
                shared = min(meta[hit]["size"], meta[other]["size"])
                results.append((sim, contain, other, shared))
        # Rank by duplicated volume: similarity scaled by that shared bound.
        results.sort(key=lambda t: (-t[0] * t[3], meta[t[2]]["file"]))
        out = {
            "ok": True,
            "path": target,
            "qualname": qualname,
            "clones": [
                {**meta[o], "similarity": round(sim, 3), "containment": round(contain, 3)}
                for sim, contain, o, _shared in results[: max(1, int(limit))]
            ],
        }
        if note:
            out["note"] = note
        return out

    # Project-wide mode.
    pairs = []
    for a, b in candidate_pairs:
        sim, contain = _exact_similarity(shingles[a], shingles[b])
        if sim >= min_similarity:
            pairs.append((sim, contain, a, b))
    pairs.sort(key=lambda t: (
        -t[0] * min(meta[t[2]]["size"], meta[t[3]]["size"]),
        meta[t[2]]["file"], meta[t[3]]["file"],
    ))
    out = {
        "ok": True,
        "clones": [
            {
                "similarity": round(sim, 3),
                "containment": round(contain, 3),
                "a": {"qualname": meta[a]["qualname"], "file": meta[a]["file"], "line": meta[a]["line"]},
                "b": {"qualname": meta[b]["qualname"], "file": meta[b]["file"], "line": meta[b]["line"]},
            }
            for sim, contain, a, b in pairs[: max(1, int(limit))]
        ],
    }
    if note:
        out["note"] = note
    return out


def _normalize(path: str) -> str:
    """Project-root-relative form of *path* (``./x`` -> ``x``).

    Deliberately not ``lstrip("./")``, which strips *characters* and would turn
    ``.hidden/config.py`` into ``hidden/config.py``.
    """
    p = Path(path).as_posix()
    return p[2:] if p.startswith("./") else p
