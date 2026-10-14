"""Conditional joint-relevance experiment on frozen development candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import evaluate, request_for_case
from ken.retrieval.joint_model import load_judge
from ken.retrieval.evidence import refine_evidence
from ken.retrieval.model import SearchRequest
from ken.retrieval.presentation import present
from ken.retrieval.profile import EncoderSpec
from ken.retrieval.ranking import rank_candidates

from replay import load_pools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rerank-limit", type=int, default=40)
    parser.add_argument("--backend", default="sentence-transformers", choices=("sentence-transformers", "mlx"))
    parser.add_argument("--rank-unit", default="entity", choices=("entity", "passage"))
    parser.add_argument("--sequence-length", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--refresh-exact", action="store_true")
    parser.add_argument("--variant", default="control")
    parser.add_argument("--model-size", default="0.6B", choices=("0.6B", "4B"))
    parser.add_argument("--refine-evidence", action="store_true")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent / "datasets"
    dataset = load_dataset(base / "development.jsonl")
    cases = {case["id"]: case for case in dataset}
    roots = {repo: Path(root) for repo, root in json.loads((base / "roots-development.json").read_text()).items()}
    pools = load_pools(args.pool, cases, roots=roots, refresh_metadata=args.refresh_metadata,
                       refresh_exact=args.refresh_exact)
    selected = [case for case in dataset if case["id"] in pools][:args.limit]
    revision = {"0.6B": "e61197ed45024b0ed8a2d74b80b4d909f1255473",
                "4B": "22e683669bc0f0bd69640a1354a6d0aebcfeede5"}[args.model_size]
    spec = EncoderSpec("Qwen/Qwen3-Reranker-" + args.model_size, revision,
                       args.backend, dtype="float16", sequence_length=args.sequence_length, batch_size=args.batch_size)
    judge = load_judge(spec)
    out = args.pool / (f"joint-{args.rerank_limit}"
        + ("-" + args.variant if args.variant != "control" else ""))
    out.mkdir(exist_ok=False)
    responses, times = [], []
    for case in selected:
        started = time.perf_counter()
        request = SearchRequest(**request_for_case(case))
        try:
            matches = rank_candidates(request, pools[case["id"]], judge=judge,
                rerank_limit=args.rerank_limit, rank_unit=args.rank_unit)
            if args.refine_evidence:
                matches = refine_evidence(matches, roots[case["repo_id"]], request, judge=judge)
            response = present(matches, roots[case["repo_id"]], request,
                               profile_version=spec.key).to_dict()
        except Exception as exc:
            response = {"results": [], "error": f"{type(exc).__name__}: {exc}"}
        responses.append({"id": case["id"], **response})
        if "error" not in response:
            with (out / "ranked.jsonl").open("a") as stream:
                stream.write(json.dumps({"id": case["id"], "matches": [
                    {"path": m.entity.path, "entity": m.entity.to_dict(), "score": m.score,
                     "signals": m.signals, "evidence": [{"start_line": p.span.start_line,
                     "end_line": p.span.end_line, "signals": p.signals} for p in m.evidence]}
                    for m in matches]}, ensure_ascii=False)+"\n")
        times.append((time.perf_counter()-started)*1000)
        (out / "responses.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in responses)+"\n")
        if len(responses) % 5 == 0:
            partial = evaluate(selected[:len(responses)], responses, roots=roots)
            print(json.dumps({"completed": len(responses), "of": len(selected), "strict": partial["strict_top1"],
                              "identity": partial["identity_top1"], "last_ms": times[-1]}), flush=True)
    report = evaluate(selected, responses, roots=roots)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    (out / "provenance.json").write_text(json.dumps({"dataset_sha256": dataset.sha256,
        "model": spec.__dict__, "pool_sha256": hashlib.sha256((args.pool / "candidates.jsonl").read_bytes()).hexdigest(),
        "rerank_limit": args.rerank_limit, "timings_ms": times, "runtime_device": judge.device,
        "rank_unit": args.rank_unit, "refresh_metadata": args.refresh_metadata,
        "refresh_exact": args.refresh_exact, "refine_evidence": args.refine_evidence}, indent=2))
    print(json.dumps({key: report[key] for key in ("strict_top1", "identity_top1", "strata")}), flush=True)


if __name__ == "__main__":
    main()
