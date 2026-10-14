"""Repository-held-out calibration of cached neural evidence; no unjudged negatives."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import evaluate, request_for_case
from ken.bench.ranking_controls import JOINT_FEATURES, Preference, fit_ranker
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.presentation import present
from ken.bench.ranking_controls import calibrate

from replay import load_pools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("features", type=Path)
    parser.add_argument("pool", type=Path)
    parser.add_argument("ranked", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = Path(__file__).resolve().parent / "datasets"
    dataset = load_dataset(base / "development.jsonl")
    cases = {c["id"]: c for c in dataset}
    roots = {k: Path(v) for k, v in json.loads((base / "roots-development.json").read_text()).items()}
    feature_rows = [json.loads(line) for line in args.features.read_text().splitlines()]
    pairs = [Preference(row["repo_id"], row["positive"], negative["features"], query_id=row["id"])
             for row in feature_rows for negative in row["negatives"]]
    pools = load_pools(args.pool, cases, roots=roots, refresh_metadata=True, refresh_exact=True)
    rows = [json.loads(line) for line in args.ranked.read_text().splitlines()]
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("duplicate cached ranking")
    selected = [cases[r["id"]] for r in rows]
    for regularization in (.01, .1, 1.):
        output = args.output / str(regularization)
        output.mkdir()
        models = {repo: fit_ranker([p for p in pairs if p.group != repo], validation_groups={repo},
            regularization=regularization, features=JOINT_FEATURES) for repo in {c["repo_id"] for c in selected}}
        responses, saved_rows = [], []
        for row in rows:
            case = cases[row["id"]]
            request = SearchRequest(**request_for_case(case))
            by_entity = {c.entity: c for c in pools[case["id"]]}
            matches = []
            for saved in row["matches"]:
                entity = EntityKey(saved["path"], **saved["entity"])
                candidate = by_entity[entity]
                passages = {(p.span.start_line, p.span.end_line): p for p in candidate.passages}
                evidence = [replace(passages[(p["start_line"], p["end_line"])], signals=p["signals"])
                            for p in saved["evidence"]]
                matches.append(CodeMatch(entity, saved["score"], evidence, evidence[0].source_hash,
                                         saved["signals"], candidate.owned_regions))
            ranked = calibrate(request, matches, models[case["repo_id"]])
            response = present(ranked, roots[case["repo_id"]], request, profile_version="held-repository-calibration").to_dict()
            responses.append({"id": case["id"], **response})
            saved_rows.append({"id": case["id"], "matches": [{"path": m.entity.path, "entity": m.entity.to_dict(),
                "score": m.score, "signals": m.signals, "evidence": [{"start_line": p.span.start_line,
                "end_line": p.span.end_line, "signals": p.signals} for p in m.evidence]} for m in ranked]})
        report = evaluate(selected, responses, roots=roots)
        (output / "responses.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in responses)+"\n")
        (output / "ranked.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in saved_rows)+"\n")
        (output / "report.json").write_text(json.dumps(report, indent=2))
        (output / "models.json").write_text(json.dumps({k: m.to_dict() for k, m in models.items()}, indent=2))
        print(json.dumps({"lambda": regularization, "strict": report["strict_top1"],
                          "identity": report["identity_top1"], "weights": {repo: dict(zip(m.features,m.weights))
                          for repo,m in models.items()}}), flush=True)
    (args.output / "provenance.json").write_text(json.dumps({"dataset_sha256": dataset.sha256,
        "feature_sha256": hashlib.sha256(args.features.read_bytes()).hexdigest(),
        "ranking_sha256": hashlib.sha256(args.ranked.read_bytes()).hexdigest(), "pairs": len(pairs),
        "feature_schema": JOINT_FEATURES, "query_balanced": True}, indent=2))


if __name__ == "__main__":
    main()
