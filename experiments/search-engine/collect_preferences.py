"""Score independently reviewed development pairs for a bounded post-model ranker."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import request_for_case
from ken.retrieval.joint_model import load_judge
from ken.bench.ranking_controls import candidate_features
from ken.retrieval.model import Candidate, SearchRequest
from ken.retrieval.profile import EncoderSpec
from ken.retrieval.ranking import rank_candidates

from replay import load_pools
from train_ranker import matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = Path(__file__).resolve().parent / "datasets"
    dataset = load_dataset(base / "development.jsonl")
    cases = {c["id"]: c for c in dataset}
    roots = {k: Path(v) for k, v in json.loads((base / "roots-development.json").read_text()).items()}
    reviews, packets = [], {}
    for suffix in ("", "-round2"):
        reviews.extend(json.loads(line) for line in (base / f"pair-review{suffix}.jsonl").read_text().splitlines())
        packets.update((r["pair_id"], r) for r in map(json.loads,
            (base / ("pair-review-input.jsonl" if not suffix else "pair-review-input-round2.jsonl")).read_text().splitlines()))
    usable = {}
    for review in reviews:
        if review["label"] != "incorrect":
            continue
        packet = packets[review["pair_id"]]
        digest = hashlib.sha256(json.dumps(packet, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        if digest != review["pair_sha256"]:
            raise ValueError("independent review hash mismatch")
        source = roots[packet["repo_id"]] / packet["alternative"]["path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != review["alternative_source_hash"]:
            raise ValueError("reviewed source changed")
        usable.setdefault(packet["case_id"], []).append(packet)
    pools = load_pools(args.pool, cases, roots=roots, refresh_metadata=True)
    spec = EncoderSpec("Qwen/Qwen3-Reranker-0.6B", "e61197ed45024b0ed8a2d74b80b4d909f1255473",
                       "mlx", dtype="float16", sequence_length=768, batch_size=8)
    judge = load_judge(spec)
    missing, timings = [], []
    for index, case in enumerate(dataset):
        request = SearchRequest(**request_for_case(case))
        pool = pools[case["id"]]
        positive = next((c for c in pool if any(matches(c, a) for a in case["alternatives"])), None)
        selected, selected_pairs = {}, []
        if positive is not None:
            selected[positive.entity] = positive
            for packet in usable.get(case["id"], []):
                alternative = packet["alternative"]
                negative = next((c for c in pool if c.entity.path == alternative["path"]
                                 and c.entity.to_dict() == alternative["entity"]), None)
                if negative is not None:
                    selected[negative.entity] = negative
                    selected_pairs.append((packet, negative))
        if not selected_pairs:
            missing.append(case["id"])
            continue
        started = time.perf_counter()
        ranked = rank_candidates(request, list(selected.values()), judge=judge,
                                 rank_unit="passage", rerank_limit=len(selected))
        features = {m.entity: candidate_features(request, Candidate(m.entity, m.evidence, m.signals)) for m in ranked}
        record = {"id": case["id"], "repo_id": case["repo_id"], "positive": features[positive.entity],
                  "negatives": [{"pair_id": packet["pair_id"], "features": features[negative.entity]}
                                for packet, negative in selected_pairs]}
        with (args.output / "features.jsonl").open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False)+"\n")
        timings.append((time.perf_counter()-started)*1000)
        if (index+1) % 10 == 0:
            print(json.dumps({"completed": index+1, "of": len(cases), "last_ms": timings[-1]}), flush=True)
    (args.output / "provenance.json").write_text(json.dumps({"dataset_sha256": dataset.sha256,
        "model": spec.__dict__, "pool_sha256": hashlib.sha256((args.pool / "candidates.jsonl").read_bytes()).hexdigest(),
        "rank_unit": "passage", "missing_training_features": missing, "timings_ms": timings,
        "reviewed_pairs_sha256": hashlib.sha256(json.dumps(packets, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}, indent=2))


if __name__ == "__main__":
    main()
