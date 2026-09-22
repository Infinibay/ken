"""Classify the misses of a ``validate_pattern_corpus`` run, so the next round is aimed.

Usage::

    .venv/bin/python examples/bench/audit_pattern_corpus.py --baseline /tmp/ken-baseline-v20
    .venv/bin/python examples/bench/audit_pattern_corpus.py --baseline /tmp/ken-baseline-v20 --pattern decorator

The runner already records, per case, the outcome of the query for the *labelled*
pattern: whether the evaluation was ``complete`` and which causes it could not decide.
A miss is therefore one of three very different things -- and only the first is a
missing primitive:

* ``incomplete``      the budget ran out: the query may be right and unusable.
* ``unknown:<cause>`` the graph cannot decide the fact (open dispatch, unlinked import,
                      an unsupported body). The cause names the primitive to add.
* ``complete-no-match`` the query ran to completion and the shape is simply not accepted:
                      either the query is too strict or the evidence is not published.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib


def load(baseline: pathlib.Path) -> list[dict]:
    cases = []
    for path in sorted(baseline.glob("*.json")):
        if path.name == "manifest.json":
            continue
        report = json.loads(path.read_text())
        repo = report.get("repo", {}).get("name", path.stem)
        for case in report.get("results", []):
            case["repo"] = repo
            cases.append(case)
    return cases


def classify(case: dict) -> tuple[str, int]:
    outcome = case.get("outcomes", {}).get(case["expected"])
    if outcome is None:
        return "not-evaluated", 0
    states = outcome.get("stats", {}).get("states", 0)
    if not outcome.get("complete", True):
        return "incomplete", states
    unknown = outcome.get("unknown") or []
    if unknown:
        return "unknown:" + ",".join(sorted({str(item).split(":")[0] for item in unknown})), states
    return "complete-no-match", states


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=pathlib.Path)
    parser.add_argument("--pattern", help="only this labelled pattern")
    parser.add_argument("--cases", action="store_true", help="list every miss, not just counts")
    arguments = parser.parse_args()

    cases = load(arguments.baseline)
    misses = [case for case in cases if not case["expected_found"]
              and (arguments.pattern is None or case["expected"] == arguments.pattern)]
    accepted = sum(1 for case in cases if case["expected_found"])
    print(f"accepted {accepted}/{len(cases)}  misses {len(misses)}")
    print(f"errors {sum(1 for case in cases if case.get('diagnostics'))}")

    tally: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for case in misses:
        kind, _ = classify(case)
        tally[case["expected"]][kind] += 1

    for pattern in sorted(tally, key=lambda name: -sum(tally[name].values())):
        counts = tally[pattern]
        detail = "  ".join(f"{kind} {count}" for kind, count in counts.most_common())
        print(f"  {pattern:26s} {sum(counts.values()):3d}  {detail}")

    if arguments.cases:
        print()
        for case in sorted(misses, key=lambda c: (c["expected"], c["repo"], c["scope"])):
            kind, states = classify(case)
            print(f"  {case['expected']:26s} {kind:34s} states={states:<7d} "
                  f"{case['repo']:18s} {case['scope']}")


if __name__ == "__main__":
    main()
