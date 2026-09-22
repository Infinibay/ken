"""A necessary domain must not cost more probes than the incumbent scan."""

import pytest

from ken.structural.model import FactIndex, IR
from ken.structural.query import Clause
from ken.structural.relational import Executor, Row
from ken.structural.relational_planning import estimate_rows


@pytest.mark.parametrize("noise", [0, 10, 1000])
@pytest.mark.parametrize("reverse", [False, True])
def test_point_join_work_is_independent_of_unrelated_domain_members(noise, reverse):
    ir = IR("sample", "python")
    for value in ("chosen", "rejected"):
        ir.add("anchor" if reverse else value, "R", value if reverse else "anchor")
    index = FactIndex(ir)
    calls = []
    original = index.rows

    def rows(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    index.rows = rows
    allowed = {"chosen", *(f"unrelated{i}" for i in range(noise))}

    class Domain:
        def domain(self, bindings, role):
            return allowed if role == "$value" else None

        def allows(self, bindings):
            return "$value" not in bindings or bindings["$value"] in allowed

    clause = Clause("require", "$anchor" if reverse else "$value", "R",
                    "$value" if reverse else "$anchor")
    engine = Executor(index, {})
    bindings = {"$anchor": "anchor"}
    assert estimate_rows(engine, clause, bindings, Domain()) == 1
    actual = engine.facts(clause, Row(bindings), Domain())
    assert [row.bindings["$value"] for row in actual] == ["chosen"]
    assert len(calls) <= 6
