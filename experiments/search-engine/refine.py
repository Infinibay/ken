"""Controlled evidence-only replay: preserve every saved owner and ranking score."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import evaluate, request_for_case
from ken.retrieval.evidence import refine_evidence
from ken.retrieval.joint_model import load_judge
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.presentation import present
from ken.retrieval.profile import EncoderSpec

from replay import load_pools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("ranked", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = Path(__file__).resolve().parent / "datasets"
    dataset = load_dataset(base / "development.jsonl")
    cases = {c["id"]: c for c in dataset}
    roots = {k: Path(v) for k, v in json.loads((base / "roots-development.json").read_text()).items()}
    pools = load_pools(args.pool, cases, roots=roots, refresh_metadata=True, refresh_exact=True)
    rows = [json.loads(line) for line in args.ranked.read_text().splitlines()]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate saved ranking")
    spec = EncoderSpec("Qwen/Qwen3-Reranker-0.6B", "e61197ed45024b0ed8a2d74b80b4d909f1255473",
                       "mlx", dtype="float16", sequence_length=768, batch_size=8)
    judge = load_judge(spec)
    responses, times = [], []
    for row in rows:
        started = time.perf_counter()
        case = cases[row["id"]]
        request = SearchRequest(**request_for_case(case))
        candidates = {c.entity: c for c in pools[case["id"]]}
        matches = []
        for saved in row["matches"]:
            entity = EntityKey(saved["path"], **saved["entity"])
            candidate = candidates[entity]
            by_span = {(p.span.start_line, p.span.end_line): p for p in candidate.passages}
            passages = [replace(by_span[(p["start_line"], p["end_line"])], signals=p["signals"])
                        for p in saved["evidence"]]
            matches.append(CodeMatch(entity, saved["score"], passages, passages[0].source_hash,
                                     saved["signals"], candidate.owned_regions))
        try:
            refined = refine_evidence(matches, roots[case["repo_id"]], request, judge=judge)
            response = present(refined, roots[case["repo_id"]], request, profile_version=spec.key).to_dict()
        except Exception as exc:
            response = {"results": [], "error": f"{type(exc).__name__}: {exc}"}
        responses.append({"id": case["id"], **response})
        times.append((time.perf_counter() - started) * 1000)
        (args.output / "responses.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in responses)+"\n")
        if len(responses) % 10 == 0:
            print(json.dumps({"completed": len(responses), "of": len(rows)}), flush=True)
    report = evaluate([cases[row["id"]] for row in rows], responses, roots=roots)
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    (args.output / "provenance.json").write_text(json.dumps({"dataset_sha256": dataset.sha256,
        "saved_ranking_sha256": hashlib.sha256(args.ranked.read_bytes()).hexdigest(),
        "model": spec.__dict__, "timings_ms": times, "runtime_device": judge.device}, indent=2))
    print(json.dumps({k: report[k] for k in ("strict_top1", "identity_top1", "strata")}), flush=True)


if __name__ == "__main__":
    main()
