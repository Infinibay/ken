"""Column overlays preserve operation fact values, filters and fallback rows."""

from dataclasses import asdict

import pytest

from ken.structural.model import IR, Fact, FactIndex, Operation
from ken.structural.query import Clause
from ken.structural_store import Store
from ken.structural_store.migrations import migrate, validate
from tests.kql2.test_graph_columns import stored


def fixture():
    ir = IR("a", "python", view="query")
    for i in range(3):
        attrs = {
            "kind": "call",
            "native_kind": "call_expression",
            "owner": "f",
            "role": "body",
            "start_byte": 100 + i,
            "end_byte": 101 + i,
        }
        ir.operations.append(
            Operation(
                str(i),
                "CALL",
                "call_expression",
                None,
                "body",
                100 + i,
                101 + i,
                1,
                "f",
            )
        )
        ir.facts.append(Fact(str(i), "OPERATION", "CALL", attrs, ["proof", str(i)]))
    return ir


def test_native_operation_attribute_keys_need_no_member_rows():
    ir = fixture()
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        assert index.term("native_kind") is None
        assert index.term("101") is None
        assert (
            store.db.execute(
                "SELECT count(*) FROM k2_graph_operation_attributes"
            ).fetchone()[0]
            == 3
        )
        reference = FactIndex(ir)
        for key, values in {
            "kind": ["call", "CALL", "absent"],
            "native_kind": ["call_expression", "missing"],
            "owner": ["f", "missing"],
            "role": ["body", ""],
            "start_byte": ["100", "101", "0101", "false", str(2**100)],
            "end_byte": ["101", "102", "103"],
            "missing": ["anything"],
        }.items():
            for value in values:
                assert [
                    asdict(f) for f in index.attr_rows("OPERATION", key, value)
                ] == [asdict(f) for f in reference.attr_rows("OPERATION", key, value)]
        assert [asdict(f) for f in index.ir.facts] == [asdict(f) for f in ir.facts]


def test_custom_values_duplicate_and_out_of_order_facts_are_preserved():
    ir = fixture()
    ir.facts = [ir.facts[2], ir.facts[0], ir.facts[2], ir.facts[1]]
    ir.facts[0].attrs["extra"] = {"nested": [False, 1]}
    ir.facts.append(
        Fact("0", "OPERATION", "CUSTOM", {**ir.facts[1].attrs, "role": "custom"})
    )
    ir.facts.append(Fact("missing", "OPERATION", "CALL", ir.facts[1].attrs.copy()))
    ir.facts.append(
        Fact("0", "OPERATION", "CALL", {**ir.facts[1].attrs, "start_byte": False})
    )
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        reference = FactIndex(ir)
        assert [asdict(f) for f in index.ir.facts] == [asdict(f) for f in ir.facts]
        for key, value in [
            ("role", "custom"),
            ("start_byte", "false"),
            ("extra", "{'nested': [False, 1]}"),
        ]:
            assert [asdict(f) for f in index.attr_rows("OPERATION", key, value)] == [
                asdict(f) for f in reference.attr_rows("OPERATION", key, value)
            ]
        first, _, third, *_ = index.ir.facts
        first.attrs["extra"]["nested"].append("changed")
        assert third.attrs["extra"]["nested"] == [False, 1]


def test_projected_overlay_members_preserve_native_and_residual_values(monkeypatch):
    ir = fixture()
    ir.facts[0].attrs.update(modality="may", unrelated={"large": [1, 2, 3]})
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        fact = index.rows("OPERATION", "0")[0]
        assert fact._attributes < 0
        residual = index.values.encoded(fact._attributes)[1][-1]
        members = dict(index.values.encoded(residual)[1])
        original = index.values.get
        def get(value):
            assert value not in {fact._attributes, residual, members["unrelated"]}
            return original(value)
        monkeypatch.setattr(index.values, "get", get)
        for key, expected in ir.facts[0].attrs.items():
            if key != "unrelated":
                assert fact.attribute(key) == expected
        assert fact.attribute("missing") is None


def test_downgrade_discards_only_graphs_requiring_new_attribute_codec():
    with Store(cache_mb=0) as store:
        unit = store.put_unit("source", IR("a", "python"), "hash", "frontend")
        stored(store, fixture(), "overlay")
        ordinary = stored(
            store,
            IR("b", "python", view="query", facts=[Fact("x", "R", "y")]),
            "ordinary",
        )
        migrate(store.db, 11)
        assert store.db.execute("SELECT graph_id FROM k2_graphs").fetchall() == [
            (ordinary.graph,)
        ]
        assert store.load_unit(unit).path == "a"
        migrate(store.db)
        assert len(ordinary.rows("R")) == 1


def test_index_trim_roundtrip_keeps_data_and_selective_access_paths():
    with Store(cache_mb=0) as store:
        index = stored(store, fixture())
        expected = [asdict(f) for f in index.ir.facts]
        for target in (12, 13, 14, 13, 12, 14):
            migrate(store.db, target)
            assert validate(store.db) == target
            names = {
                row[1]
                for row in store.db.execute("PRAGMA index_list(k2_graph_operations)")
            }
            for suffix in ("role", "start", "end"):
                assert ("k2_graph_operation_" + suffix in names) == (target == 12)
            assert ("k2_graph_operation_region" in names) == (target < 14)
            member_indexes = {
                row[1]
                for row in store.db.execute("PRAGMA index_list(k2_graph_members)")
            }
            assert ("k2_graph_member_key" in member_indexes) == (target < 14)
            for column in ("owner", "native_kind"):
                plan = store.db.execute(
                    "EXPLAIN QUERY PLAN SELECT ordinal FROM k2_graph_operations "
                    f"WHERE graph_id=? AND {column}=?",
                    (
                        index.graph,
                        index.term("f" if column == "owner" else "call_expression"),
                    ),
                ).fetchall()
                assert any(
                    "SEARCH" in row[3] and f"k2_graph_operation_{column}" in row[3]
                    for row in plan
                )
            assert [asdict(f) for f in index.ir.facts] == expected
            assert len(index.attr_rows("OPERATION", "start_byte", "101")) == 1


@pytest.mark.parametrize(
    "key", ["kind", "native_kind", "owner", "role", "start_byte", "extra"]
)
def test_bound_overlay_filters_do_not_scan_global_attribute_buckets(key):
    ir = IR("a", "python", view="query")
    attrs = {
        "kind": "call",
        "native_kind": "call_expression",
        "owner": "f",
        "role": "body",
        "start_byte": 0,
        "end_byte": 1,
        "extra": "shared",
    }
    for i in range(1000):
        identity = str(i)
        ir.operations.append(
            Operation(identity, "CALL", "call_expression", None, "body", 0, 1, 1, "f")
        )
        ir.facts.append(Fact(identity, "OPERATION", "CALL", {**attrs, "unique": i}))
    # An ordinary value is still a candidate even when overlays use the same key.
    ir.facts.append(Fact("fallback", "OPERATION", "CUSTOM", {key: attrs[key]}))
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        for subject in ("42", "fallback", "absent"):
            clause = Clause(
                "require", "$op", "OPERATION", "_", [(key, "literal", str(attrs[key]))]
            )
            instructions = 0

            def count():
                nonlocal instructions
                instructions += 1
                return 0

            store.db.set_progress_handler(count, 1)
            try:
                rows = index.candidates(clause, subject=subject)
                assert bool(rows) == (subject != "absent")
                found = list(rows)
            finally:
                store.db.set_progress_handler(None, 0)
            assert [fact.subject for fact in found] == (
                [] if subject == "absent" else [subject]
            )
            assert instructions < 1500


def test_selective_object_uses_reverse_lookup_before_attributes():
    ir = IR("a", "python", view="query")
    for i in range(1000):
        ir.facts.append(Fact(str(i), "R", str(i), {"shared": True, "unique": i}))
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        clause = Clause("require", "$x", "R", "$y", [("shared", "literal", "true")])
        steps = []
        store.db.set_progress_handler(lambda: steps.append(1) or 0, 1)
        try:
            rows = index.candidates(clause, object="42")
            assert [fact.subject for fact in rows] == ["42"]
            assert len(rows) == 1
        finally:
            store.db.set_progress_handler(None, 0)
        assert len(steps) < 500
        assert rows.access == "reverse"
