"""Reproducible development diagnostics; never accepts hidden reference hints."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import evaluate, request_for_case
from ken.bench.runner import run_live, source_manifest
from ken.bench.source_receipts import verify_frozen_source
from ken.db import connect
from ken.retrieval.candidates import retrieve
from ken.retrieval.model import SearchRequest
from ken.retrieval.profile import EncoderSpec, RetrievalProfile, default_profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="static", choices=("static", "e5", "qwen", "potion"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--dtype", default="float32", choices=("float32", "float16"))
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prepared-sources", action="store_true")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--control-model-path", type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    dataset = load_dataset(base / "datasets/development.jsonl")
    cases = list(dataset)[:args.limit]
    roots = {key: Path(value) for key, value in json.loads(
        (base / "datasets/roots-development.json").read_text()).items()}
    profile = default_profile()
    encoders = None
    if args.model == "potion":
        if args.control_model_path is None or args.profile is not None:
            raise ValueError("Potion control requires --control-model-path and its registered provided profile")
        from experimental_encoders import PotionControl
        encoder = PotionControl(args.control_model_path)
        encoders = {"identity": encoder, "behavior": encoder}
        profile = RetrievalProfile(encoder.spec, encoder.spec)
    elif args.model != "static":
        model, revision = {
            "e5": ("intfloat/multilingual-e5-small", "614241f622f53c4eeff9890bdc4f31cfecc418b3"),
            "qwen": ("Qwen/Qwen3-Embedding-0.6B", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"),
        }[args.model]
        spec = EncoderSpec(model, revision, "sentence-transformers", dtype=args.dtype)
        profile = RetrievalProfile(spec, spec)
    if args.profile:
        profile = RetrievalProfile.from_dict(json.loads(args.profile.read_text()))
    if args.budget is not None:
        profile = replace(profile, max_tokens=args.budget)
    label = ("profile-" + profile.fingerprint[:12] if args.profile else
             args.model + ("-" + args.dtype if args.dtype != "float32" else ""))
    out = args.output or Path("output/development") / (label + (f"-{args.limit}" if args.limit else ""))
    if args.prepared_sources:
        prepared = json.loads((out / "source-preparation.json").read_text())
        if prepared["profile_sha256"] != profile.fingerprint or (out / "provenance.json").exists():
            raise ValueError("prepared sources require the matching profile and no previous measurement")
    if out.exists() and not (args.resume or args.reuse or args.prepared_sources):
        raise FileExistsError("use a fresh output directory, or --resume with matching frozen inputs")
    out.mkdir(parents=True, exist_ok=True)
    responses, diagnostic = [], []
    provenance = {"dataset_sha256": dataset.sha256, "profile_sha256": profile.fingerprint,
                  "encoder_models": {view: getattr(profile, view).model_id for view in ("identity", "behavior")},
                  "case_ids": [c["id"] for c in cases], "repos": {}}
    import ken
    if Path(ken.__file__).resolve().parents[2] != base.parents[1]:
        raise ValueError("measurement script and imported engine must use the same frozen source")
    source_receipt = base.parents[1] / "SOURCE-MANIFEST.json"
    provenance["source_receipt_sha256"] = verify_frozen_source(base.parents[1]) if source_receipt.is_file() else None
    runtime = {}
    for package in ("numpy", "mlx", "mlx-lm", "transformers", "huggingface-hub", "torch", "sentence-transformers", "tokenizers", "safetensors", "model2vec"):
        try:
            runtime[package] = version(package)
        except PackageNotFoundError:
            runtime[package] = None
    provenance["runtime_versions"] = runtime
    if args.resume:
        if not source_receipt.is_file():
            raise ValueError("resume requires an immutable frozen source receipt")
        saved = json.loads((out / "provenance.json").read_text())
        if any(saved.get(key) != provenance[key] for key in ("dataset_sha256", "profile_sha256", "case_ids", "source_receipt_sha256", "runtime_versions")):
            raise ValueError("resume requires the same dataset, complete case list and profile")
        provenance = saved
        responses = [json.loads(line) for line in (out / "responses.jsonl").read_text().splitlines()]
        diagnostic = [json.loads(line) for line in (out / "candidates.jsonl").read_text().splitlines()]
        for rows in (responses, diagnostic):
            if len({r["id"] for r in rows}) != len(rows) or any(r["id"] not in provenance["case_ids"] for r in rows):
                raise ValueError("invalid checkpoint case identifiers")
    (out / "profile.json").write_text(json.dumps(profile.to_dict(), indent=2))
    for repo in sorted({case["repo_id"] for case in cases}):
        selected = [case for case in cases if case["repo_id"] == repo]
        selected_ids = {c["id"] for c in selected}
        if (args.resume and repo in provenance["repos"] and
                selected_ids <= {r["id"] for r in responses} & {r["id"] for r in diagnostic}):
            from ken.gitignore_filter import iter_files
            current = source_manifest(roots[repo], iter_files(roots[repo]))
            recorded = provenance["repos"][repo]["index_stats"][repo]
            if current["source_tree_sha256"] != recorded["source_tree_sha256"]:
                raise ValueError("source corpus changed since checkpoint")
            print(json.dumps({"resumed": repo, "cases": len(selected)}), flush=True)
            continue
        started = time.perf_counter()
        print(json.dumps({"starting": repo, "encoder_models": provenance["encoder_models"],
                          "behavior_dtype": profile.behavior.dtype, "profile_sha256": profile.fingerprint}), flush=True)
        run = run_live(selected, roots, out / "indices", profile=profile, rebuild=not args.reuse,
                       encoders=encoders)
        responses.extend(run.pop("responses"))
        provenance["repos"][repo] = run
        conn = connect(out / "indices" / (repo + ".db"))
        for case in selected:
            candidates = retrieve(conn, roots[repo], SearchRequest(**request_for_case(case)), profile,
                                  encoders=encoders)
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
