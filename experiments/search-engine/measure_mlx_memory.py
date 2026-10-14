"""Isolate free-buffer caching on a deterministic, label-free source sample."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from ken.db import connect
from ken.retrieval.profile import RetrievalProfile, load_encoder
from ken.retrieval.representations import bounded_passage_text
from ken.retrieval.storage import load_passage_map


def main():
    import mlx.core as mx
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=1024)
    parser.add_argument("--free-cache-mib", type=int)
    args = parser.parse_args()
    if args.count <= 0 or (args.free_cache_mib is not None and args.free_cache_mib < 0):
        raise ValueError("invalid measurement budget")
    args.output.mkdir(parents=True, exist_ok=False)
    previous = mx.set_cache_limit((args.free_cache_mib or 0) * 1024**2)
    if args.free_cache_mib is None:
        mx.set_cache_limit(previous)
    profile = RetrievalProfile.from_dict(json.loads(args.profile.read_text()))
    with connect(args.index) as conn:
        passages = list(load_passage_map(conn).values())
    indices = np.linspace(0, len(passages)-1, min(args.count, len(passages)), dtype=int)
    selected = [passages[i] for i in indices]
    encoder = load_encoder(profile.behavior)
    texts = [bounded_passage_text(p, "behavior", profile, encoder) for p in selected]
    # Warm the same tokenizer/kernels; start both measurements with free cache empty.
    encoder.embed_passages(texts[:16])
    mx.clear_cache()
    mx.reset_peak_memory()
    started = time.perf_counter()
    vectors = np.stack(encoder.embed_passages(texts))
    elapsed = time.perf_counter() - started
    np.save(args.output / "vectors.npy", vectors)
    report = {"count": len(texts), "seconds": elapsed, "texts_per_second": len(texts)/elapsed,
        "active_bytes": mx.get_active_memory(), "cached_bytes": mx.get_cache_memory(),
        "peak_active_bytes": mx.get_peak_memory(), "free_cache_mib": args.free_cache_mib,
        "previous_free_cache_bytes": previous, "profile_sha256": profile.fingerprint,
        "texts_sha256": hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest(),
        "vectors_sha256": hashlib.sha256(vectors.tobytes()).hexdigest()}
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
