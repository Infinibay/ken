"""Reproduce search friction and compare source evidence with a runnable oracle.

Only the generated fixture is executed. Ken analyzes source without executing it.
No production project code is imported by the evaluation.
"""

from __future__ import annotations

import argparse
import ast
import json
import runpy
import subprocess
import tempfile
import time
from pathlib import Path

from ken.inspection.service import inspect
from ken.kql2.service import search

FIXTURE = """created = []
class Resource:
    def __init__(self): self.closed = False
    def close(self): self.closed = True

def _conn():
    resource = Resource()
    created.append(resource)
    return resource

def consume(resource):
    resource.close()

def leak():
    connection = _conn()

def direct_close():
    connection = _conn()
    connection.close()

def alias_close():
    connection = _conn()
    alias = connection
    connection = None
    alias.close()

def wrong_close():
    first = _conn()
    second = _conn()
    second.close()

def transferred():
    return _conn()

def delegated():
    consume(_conn())
"""
QUERY = """language "kql/2"; module investigation;
query missing_close {
  callable $target {name:"_conn";}
  callable $owner {
    call $site {target:$target;}
    not exists {call $cleanup {name:/^(close|closing)$/;}}
  }
  select $owner;
}"""


def evaluate(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ken-resource-investigation-") as directory:
        root = Path(directory)
        source = root / "resources.py"
        source.write_text(FIXTURE)
        module = runpy.run_path(str(source))
        oracle = {}
        for name in (
            "leak",
            "direct_close",
            "alias_close",
            "wrong_close",
            "transferred",
            "delegated",
        ):
            module["created"].clear()
            returned = module[name]()
            live = [r for r in module["created"] if not r.closed]
            oracle[name] = (
                "returned_identity"
                if live and all(r is returned for r in live)
                else "leak"
                if live
                else "released"
            )
        started = time.monotonic()
        text = subprocess.run(
            ["rg", "-n", r"\b_conn\(", str(source)],
            capture_output=True,
            text=True,
            check=True,
        )
        text_ms = (time.monotonic() - started) * 1000
        lines = {int(line.split(":", 1)[0]) for line in text.stdout.splitlines()}
        declarations = [
            node
            for node in ast.parse(FIXTURE).body
            if isinstance(node, ast.FunctionDef)
        ]
        text_candidates = [
            node.name
            for node in declarations
            if node.name != "_conn"
            and any(node.lineno <= line <= node.end_lineno for line in lines)
        ]
        measurements = []
        for label, query in (
            ("first", QUERY),
            ("repeat", QUERY),
            ("edited", QUERY.replace("close|closing", "close|closing|dispose")),
        ):
            start = time.monotonic()
            result = search(root, query, timeout_ms=5000)
            measurements.append(
                {
                    "case": label,
                    "wall_ms": (time.monotonic() - start) * 1000,
                    "complete": result["complete"],
                    "rows": len(result["rows"]),
                    "parsed_units": result["analysis"].get("parsed_units"),
                    "reused_units": result["analysis"].get("reused_units"),
                    "result_cache": result["analysis"].get("result_cache"),
                }
            )
        candidates = [
            row[0].rsplit("CALLABLE:", 1)[1].split("@")[0] for row in result["rows"]
        ]
        impact = inspect(root, "resources.py::_conn", depth=2, limit=30)
        flows = [
            {
                "caller": c["caller"]["name"],
                "call_line": c["call"]["line"],
                **c["result_flow"],
            }
            for c in impact["consumers"]
        ]
        # The deliberately coarse predicate is a hypothesis filter, not a leak detector.
        assert set(candidates) == {"leak", "transferred", "delegated"}
        assert oracle["wrong_close"] == "leak" and "wrong_close" not in candidates
        assert any(
            f["caller"] == "alias_close"
            and any(b["status"] == "cleanup_candidate" for b in f["boundaries"])
            for f in flows
        )
        wrong = [f for f in flows if f["caller"] == "wrong_close"]
        assert (
            len(wrong) == 2
            and sum(
                any(b["status"] == "cleanup_candidate" for b in f["boundaries"])
                for f in wrong
            )
            == 1
        )
        report = {
            "runtime_ground_truth": oracle,
            "rg": {"wall_ms": text_ms, "candidates": text_candidates},
            "kql_absence_candidates": candidates,
            "query_attempts": 1,
            "measurements": measurements,
            "result_flows": flows,
            "coverage": impact["coverage"],
            "limits": "Retrieval timings only, not human diagnosis time. Cleanup spelling is not a release contract; the absence query misses wrong_close and includes two safe wrappers.",
        }
        (output / "resources.py.txt").write_text(FIXTURE)
        (output / "missing-close.kql").write_text(QUERY)
        (output / "fixture-evaluation.json").write_text(json.dumps(report, indent=2))
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.output)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "runtime_ground_truth",
                    "rg",
                    "kql_absence_candidates",
                    "measurements",
                    "limits",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
