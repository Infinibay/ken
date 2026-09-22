"""Measure a four-node shape posting list, without changing the source index.

This experiment covers direct binary comparisons used as branch conditions.
It intentionally excludes wrappers, chained comparisons and unresolved operands.
Absence here is NOT evidence that a source-level pattern is absent. The normal
matcher must still check bindings, coverage and control flow.

Usage::

    PYTHONPATH=src python examples/bench/structural_shapes.py INDEX.sqlite OUTPUT

OUTPUT must not exist. The source is opened read-only; the separate posting list
contains only integer references into that particular graph's term dictionary.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import time
from collections import Counter
from pathlib import Path

from ken.structural_store.graph_values import ValueReader


def term(db, graph, text):
    row = db.execute(
        "SELECT term_id FROM k2_graph_terms WHERE graph_id=? AND text=?",
        (graph, text),
    ).fetchone()
    return row[0] if row else None


def extract(db, graph):
    """Return exact shape keys and concrete node references, in source order."""
    values = ValueReader(db, graph)
    control, operator, operand, branch, compare = (
        term(db, graph, text)
        for text in ("CONTROL_CONDITION", "OPERATOR", "OPERAND", "BRANCH", "COMPARE")
    )
    roots = db.execute(
        """SELECT b.native_kind,o.native_kind,c.subject,c.object,b.owner
        FROM k2_graph_facts c INDEXED BY k2_graph_fact_relation
        CROSS JOIN k2_graph_operations b INDEXED BY k2_graph_operation_id
        CROSS JOIN k2_graph_operations o INDEXED BY k2_graph_operation_id
        WHERE c.graph_id=? AND c.relation=?
          AND b.graph_id=c.graph_id AND b.local_id=c.subject AND b.kind=?
          AND o.graph_id=c.graph_id AND o.local_id=c.object AND o.kind=?
        ORDER BY c.ordinal""",
        (graph, control, branch, compare),
    ).fetchall()
    rows = []
    for root_kind, condition_kind, root, condition, owner in roots:
        operators = db.execute(
            """SELECT object,attributes FROM k2_graph_facts
            INDEXED BY k2_graph_fact_forward
            WHERE graph_id=? AND relation=? AND subject=? ORDER BY ordinal""",
            (graph, operator, condition),
        ).fetchall()
        if len(operators) != 1 or values.get(operators[0][1]).get("position") != 0:
            continue
        operands = db.execute(
            """SELECT f.object,f.attributes,o.native_kind
            FROM k2_graph_facts f INDEXED BY k2_graph_fact_forward
            LEFT JOIN k2_graph_operations o INDEXED BY k2_graph_operation_id
              ON o.graph_id=f.graph_id AND o.local_id=f.object
            WHERE f.graph_id=? AND f.relation=? AND f.subject=? ORDER BY f.ordinal""",
            (graph, operand, condition),
        ).fetchall()
        if len(operands) != 2 or any(item[2] is None for item in operands):
            continue
        ordered = {values.get(attrs).get("position"): (node, kind)
                   for node, attrs, kind in operands}
        if set(ordered) != {0, 1}:
            continue
        left, left_kind = ordered[0]
        right, right_kind = ordered[1]
        rows.append((root_kind, condition_kind, operators[0][0], left_kind,
                     right_kind, root, condition, left, right, owner))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True)
    source.execute("PRAGMA cache_size=-65536")
    graph = source.execute(
        "SELECT graph_id FROM k2_graph_publications WHERE ready=1 ORDER BY graph_id DESC LIMIT 1"
    ).fetchone()[0]
    started = time.perf_counter()
    rows = extract(source, graph)
    extraction = time.perf_counter() - started
    path = args.output / "shapes.sqlite"
    posting = sqlite3.connect(path)
    started = time.perf_counter()
    posting.execute("""CREATE TABLE shapes(
        root_kind INTEGER, condition_kind INTEGER, operator INTEGER,
        left_kind INTEGER, right_kind INTEGER,
        root INTEGER, condition INTEGER, left_node INTEGER, right_node INTEGER,
        owner INTEGER)""")
    posting.executemany("INSERT INTO shapes VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    posting.execute("CREATE INDEX shape ON shapes(root_kind,condition_kind,operator,left_kind,right_kind)")
    posting.commit()
    writing = time.perf_counter() - started
    word = lambda ident: source.execute(
        "SELECT text FROM k2_graph_terms WHERE graph_id=? AND term_id=?", (graph, ident)
    ).fetchone()[0]
    counts = Counter(row[:5] for row in rows)
    # Pick the commonest identifier/literal example, rather than a rare outlier.
    literals = {"integer", "integer_literal", "float", "float_literal", "string",
                "string_literal", "true", "false", "boolean_literal", "none", "null"}
    candidates = [key for key, _ in counts.most_common()
                  if word(key[3]) == "identifier" and word(key[4]) in literals]
    if not candidates:
        raise ValueError("no direct identifier/literal branch comparison in this graph")
    key = candidates[0]
    sql = "SELECT * FROM shapes WHERE root_kind=? AND condition_kind=? AND operator=? AND left_kind=? AND right_kind=?"
    indexed = []
    for _ in range(5):
        started = time.perf_counter()
        hits = posting.execute(sql, key).fetchall()
        indexed.append(time.perf_counter() - started)
    direct = []
    for _ in range(3):
        started = time.perf_counter()
        expected = [row for row in extract(source, graph) if row[:5] == key]
        direct.append(time.perf_counter() - started)
        assert sorted(hits) == sorted(expected)
    # The full extraction is a baseline, not the best possible SQL plan for a
    # known shape. Do not present this ratio as end-to-end KQL2 acceleration.
    report = {
        "source": str(args.source.resolve()), "graph": graph,
        "coverage": "direct binary BRANCH/COMPARE only; fallback required elsewhere",
        "rows": len(rows), "distinct_shapes": len(counts),
        "extraction_seconds": extraction, "writing_seconds": writing,
        "bytes": path.stat().st_size, "selected_shape": [word(i) for i in key],
        "selected_matches": len(hits), "exact_node_references_equal": True,
        "lookup_seconds": indexed, "lookup_median_seconds": statistics.median(indexed),
        "full_reextraction_seconds": direct,
        "scope": "posting lookup versus reconstructing all eligible shapes; not a KQL2 or optimized SQL speedup",
        "top_shapes": [{"shape": [word(i) for i in key], "count": count}
                       for key, count in counts.most_common(10)],
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    posting.close()
    source.close()


if __name__ == "__main__":
    main()
