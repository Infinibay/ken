"""Reproducible development diagnostics; never accepts hidden reference hints."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import evaluate, request_for_case
from ken.bench.runner import run_live
from ken.db import connect
from ken.retrieval.candidates import retrieve
from ken.retrieval.model import SearchRequest
from ken.retrieval.profile import EncoderSpec, RetrievalProfile, default_profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="static", choices=("static", "e5", "qwen"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--dtype", default="float32", choices=("float32", "float16"))
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    dataset = load_dataset(base / "datasets/development.jsonl")
    cases = list(dataset)[:args.limit]
    roots = {key: Path(value) for key, value in json.loads(
        (base / "datasets/roots-development.json").read_text()).items()}
    profile = default_profile()
    if args.model != "static":
        model, revision = {
            "e5": ("intfloat/multilingual-e5-small", "614241f622f53c4eeff9890bdc4f31cfecc418b3"),
            "qwen": ("Qwen/Qwen3-Embedding-0.6B", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"),
        }[args.model]
        spec = EncoderSpec(model, revision, "sentence-transformers", dtype=args.dtype)
        profile = RetrievalProfile(spec, spec)
    label = args.model + ("-" + args.dtype if args.dtype != "float32" else "")
    out = Path("output/development") / (label + (f"-{args.limit}" if args.limit else ""))
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile.json").write_text(json.dumps(profile.to_dict(), indent=2))
    responses, diagnostic = [], []
    provenance = {"dataset_sha256": dataset.sha256, "profile_sha256": profile.fingerprint,
                  "model": args.model, "case_ids": [c["id"] for c in cases], "repos": {}}
    for repo in sorted({case["repo_id"] for case in cases}):
        selected = [case for case in cases if case["repo_id"] == repo]
        started = time.perf_counter()
        print(json.dumps({"starting": repo, "model": args.model, "dtype": args.dtype}), flush=True)
        run = run_live(selected, roots, out / "indices", profile=profile, rebuild=not args.reuse)
        responses.extend(run.pop("responses"))
        provenance["repos"][repo] = run
        conn = connect(out / "indices" / (repo + ".db"))
        for case in selected:
            candidates = retrieve(conn, roots[repo], SearchRequest(**request_for_case(case)), profile)
            diagnostic.append({"id": case["id"], "candidates": [
                {"path": c.entity.path, "entity": c.entity.to_dict(), "signals": c.signals,
                 "passages": [{"start_line": p.span.start_line, "end_line": p.span.end_line,
                               "signals": p.signals} for p in c.passages]} for c in candidates]})
        conn.close()
        (out / "responses.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in responses)+"\n")
        (out / "candidates.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in diagnostic)+"\n")
        (out / "provenance.json").write_text(json.dumps(provenance, indent=2))
        score = evaluate(selected, [r for r in responses if r["id"] in {c["id"] for c in selected}], roots=roots)
        print(json.dumps({"repo": repo, "strict": score["strict_top1"],
                          "identity": score["identity_top1"], "seconds": round(time.perf_counter()-started, 2)}), flush=True)
    report = evaluate(cases, responses, roots=roots)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("strict_top1", "identity_top1", "macro_repo_top1", "strata")}), flush=True)


if __name__ == "__main__":
    main()
