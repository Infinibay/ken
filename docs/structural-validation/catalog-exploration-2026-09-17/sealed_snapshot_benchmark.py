import json
import time
from pathlib import Path

from ken.kql2.exploration.catalog_index import CatalogIndex
from ken.structural.catalog import detect_patterns
from ken.structural.query import QueryBudget
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex

path = Path("/tmp/ken-codex-perf/native-full-v11/query-index.sqlite")
out = Path("/tmp/ken-catalog-port-full")
out.mkdir(exist_ok=True)
for backend in ["indexed", "exploration"]:
    print("Starting", backend, flush=True)
    started = time.monotonic()
    with Store(path, cache_mb=None) as store:
        base = GraphIndex(store, 1)
        index = (
            CatalogIndex(base, revision="sealed-codex-1")
            if backend == "exploration"
            else base
        )
        index.profile = True
        result = detect_patterns(index, None, QueryBudget(timeout_ms=5000))
        report = {
            "backend": backend,
            "source": "sealed pre-existing Codex semantic snapshot; not fresh acquisition",
            "index": str(path),
            "ir_version": base.ir.version,
            "entities": len(base.ir.entities),
            "facts": len(base.ir.facts),
            "seconds": time.monotonic() - started,
            "timeout_ms_per_pattern": 5000,
            **result,
        }
        if backend == "exploration":
            report["buckets"] = dict(index.cache.metrics)
            index.close()
        base.close()
    (out / f"{backend}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        backend,
        report["seconds"],
        "complete",
        result["complete"],
        "findings",
        len(result["findings"]),
        flush=True,
    )
