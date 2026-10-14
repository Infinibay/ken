"""Repository-held-out control; only independently reviewed negatives fit weights."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import _identity, evaluate, request_for_case
from ken.bench.ranking_controls import Preference, candidate_features, fit_ranker
from ken.retrieval.model import SearchRequest
from ken.retrieval.presentation import present
from ken.bench.ranking_controls import rank_linear

from replay import load_pools


def matches(candidate, alternative):
    record = {"path": candidate.entity.path, "entity": candidate.entity.to_dict()}
    if not _identity(record, alternative):
        return False
    if alternative.get("entity") is not None:
        return True
    spans = [p.entity_span for p in candidate.passages]
    return any(all(span.start_line <= a["start_line"] <= a["end_line"] <= span.end_line
                   for a in alternative["anchors"]) for span in spans)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("--round2", action="store_true")
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--refresh-exact", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent / "datasets"
    dataset = load_dataset(base / "development.jsonl")
    cases = {case["id"]: case for case in dataset}
    roots = {repo: Path(root) for repo, root in json.loads((base / "roots-development.json").read_text()).items()}
    review_paths = [base / "pair-review.jsonl"]
    input_paths = [base / "pair-review-input.jsonl"]
    if args.round2:
        review_paths.append(base / "pair-review-round2.jsonl")
        input_paths.append(base / "pair-review-input-round2.jsonl")
    reviews = [row for path in review_paths for row in map(json.loads, path.read_text().splitlines())]
    inputs = {row["pair_id"]: row for path in input_paths for row in map(json.loads, path.read_text().splitlines())}
    pools = load_pools(args.pool, cases, roots=roots, refresh_metadata=args.refresh_metadata,
                       refresh_exact=args.refresh_exact)
    features = {rid: {c.entity: candidate_features(SearchRequest(**request_for_case(cases[rid])), c)
                      for c in pool} for rid, pool in pools.items()}
    pairs = []
    missing = []
    for review in reviews:
        rid = review["case_id"]
        if rid not in pools or review["label"] != "incorrect":
            continue
        pool = pools[rid]
        packet = inputs[review["pair_id"]]
        digest = hashlib.sha256(json.dumps(packet, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode()).hexdigest()
        if digest != review["pair_sha256"]:
            raise ValueError(f"review no longer matches candidate pair: {rid}")
        source = roots[cases[rid]["repo_id"]] / packet["alternative"]["path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != review["alternative_source_hash"]:
            raise ValueError(f"review no longer matches source: {rid}")
        positive = next((c for c in pool if any(matches(c, a) for a in cases[rid]["alternatives"])), None)
        alternative = packet["alternative"]
        negative = next((c for c in pool if c.entity.path == alternative["path"]
                         and c.entity.to_dict() == alternative["entity"]), None)
        if positive is None or negative is None:
            missing.append(rid)
            continue
        pairs.append(Preference(cases[rid]["repo_id"], features[rid][positive.entity], features[rid][negative.entity]))
    out = args.output or args.pool / "linear"
    out.mkdir(exist_ok=True)
    selected_cases = [cases[rid] for rid in pools]
    repos = sorted({case["repo_id"] for case in selected_cases})
    reports = {}
    for regularization in (.01, .1, 1.):
        responses = []
        for repo in repos:
            trained = [p for p in pairs if p.group != repo]
            model = fit_ranker(trained, validation_groups={repo}, regularization=regularization)
            for case in selected_cases:
                if case["repo_id"] != repo:
                    continue
                request = SearchRequest(**request_for_case(case))
                matches_ = rank_linear(request, pools[case["id"]], model)
                response = present(matches_, roots[repo], request, profile_version="development-cv").to_dict()
                responses.append({"id": case["id"], **response})
        report = evaluate(selected_cases, responses, roots=roots)
        reports[str(regularization)] = report
        (out / f"responses-{regularization}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in responses)+"\n")
        print(json.dumps({"lambda": regularization, "strict": report["strict_top1"], "identity": report["identity_top1"]}), flush=True)
    best = max(reports, key=lambda key: reports[key]["strict_top1"]["rate"])
    model = fit_ranker(pairs, validation_groups=set(), regularization=float(best))
    (out / "ranker.json").write_text(json.dumps(model.to_dict(), indent=2))
    (out / "report.json").write_text(json.dumps({"reports": reports, "selected_lambda": best,
        "reviewed_pairs_used": len(pairs), "training_missing_features": missing,
        "candidate_pool_sha256": hashlib.sha256((args.pool / "candidates.jsonl").read_bytes()).hexdigest(),
        "review_sha256": hashlib.sha256(b"".join(path.read_bytes() for path in review_paths)).hexdigest(),
        "refreshed_metadata": args.refresh_metadata, "refreshed_exact": args.refresh_exact}, indent=2))


if __name__ == "__main__":
    main()
