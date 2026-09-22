"""Physical selection must preserve source rows while avoiding broad scans."""

import random

import pytest

from ken.kql2.exploration.records import Records, encode
from ken.structural.model import IR, Operation
from ken.structural_store import Store
from tests.kql2.test_graph_columns import stored


@pytest.mark.parametrize("seed", range(12))
def test_vector_selection_matches_ordered_scan_with_duplicates_and_alternatives(seed):
    rng = random.Random(seed)
    words = [None, "", "a", "b", "a|b", "ñ"]
    rows = [(rng.choice(words), rng.choice(words), rng.randrange(-4, 5))
            for _ in range(200)]
    rows += rows[::5]
    records = Records(encode(rows, 3, {0, 1}, lambda: None), 3, {0, 1})
    for _ in range(100):
        constraints = {}
        for column in rng.sample(range(3), rng.randrange(4)):
            values = words + ["missing"] if column < 2 else list(range(-5, 6))
            constraints[column] = (rng.choice(values) if rng.randrange(2) else
                                   tuple(rng.choices(values, k=rng.randrange(5))))
        expected = [row for row in rows if all(
            row[column] in (value if isinstance(value, tuple) else (value,))
            for column, value in constraints.items()
        )]
        for filters in (constraints, dict(reversed(list(constraints.items())))):
            assert [records.row(i) for i in records.select(filters)] == expected
    assert not records.cells.flags.writeable


def test_empty_record_vector_supports_unrestricted_and_constrained_selection():
    records = Records(encode([], 2, {0}, lambda: None), 2, {0})
    for constraints in ({}, {0: "missing"}, {1: 0}, {1: ()}):
        assert list(records.select(constraints)) == []


@pytest.mark.parametrize("lookup", ["local_id", "owner", "kind", "ordinal"])
def test_native_operation_point_access_does_not_scan_unrelated_operations(lookup):
    operations = [Operation(f"op{i}", "CALL", "call", None, "body", i, i + 1,
                            i + 1, "many", {}) for i in range(3000)]
    needle = Operation("needle", "RETURN", "return", None, "body", 3000, 3001,
                       3001, "one", {})
    operations.append(needle)
    ir = IR("sample", "python", view="query", operations=operations)
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        steps = 0

        def progress():
            nonlocal steps
            steps += 1
            return 0

        filters = {"local_id": "needle", "owner": "one", "kind": "RETURN", "ordinal": 3000}
        store.db.set_progress_handler(progress, 100)
        try:
            assert list(index.operations(**{lookup: filters[lookup]})) == [needle]
        finally:
            store.db.set_progress_handler(None, 0)
        # A point lookup takes hundreds of VM instructions; scanning 3,000
        # unrelated rows takes tens of thousands, independent of machine speed.
        assert steps < 20


def test_operation_filters_keep_conjunction_and_source_order():
    operations = [
        Operation("first", "CALL", "call", None, "body", 0, 1, 1, "owner", {}),
        Operation("second", "RETURN", "return", None, "body", 1, 2, 2, "owner", {}),
        Operation("third", "CALL", "call", None, "body", 2, 3, 3, "other", {}),
    ]
    with Store(cache_mb=0) as store:
        index = stored(store, IR("sample", "python", view="query", operations=operations))
        assert list(index.operations(owner="owner")) == operations[:2]
        assert list(index.operations(kind="CALL")) == operations[::2]
        assert list(index.operations(owner="owner", kind="CALL")) == operations[:1]
        assert not list(index.operations(local_id="third", owner="owner"))
        assert not list(index.operations(local_id="missing"))
