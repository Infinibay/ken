"""Native coverage preserves the reference's mixed/partial/absent inventories."""

import pytest

from ken.kql2.source_candidates import SourceCandidatePlanner
from ken.structural.model import IR, Entity, Fact, FactIndex
from ken.structural_store import Store
from tests.kql2.test_graph_columns import stored


@pytest.mark.parametrize("entered", [False, True])
@pytest.mark.parametrize(
    "statuses",
    [
        [],
        [("structured", {})],
        [("partial", {})],
        [("partial", {"reasons": ["await"]})],
        [("partial", {"reasons": ["yield"]})],
        [("structured", {}), ("partial", {"reasons": ["await"]})],
        [
            ("partial", {"reasons": ["await"]}),
            ("partial", {"reasons": ["raise_statement"]}),
        ],
    ],
)
def test_coverage_matches_reference(statuses, entered):
    ir = IR(
        "x",
        "python",
        view="query",
        entities={"a": Entity("a", "CALLABLE", "a", "x", 1, 2)},
    )
    ir.facts = [Fact("a", "ENTITY", "CALLABLE"), Fact("missing", "ENTITY", "CALLABLE")]
    ir.facts.extend(
        Fact("a", "CFG_STATUS", status, attrs) for status, attrs in statuses
    )
    if entered:
        ir.facts.append(Fact("a", "CFG_ENTRY", "entry"))
    reference = SourceCandidatePlanner(FactIndex(ir), lambda: None)
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        candidate = SourceCandidatePlanner(index, lambda: None)
        assert candidate.coverage == reference.coverage
        assert candidate.call_coverage == reference.call_coverage
        assert index.source_coverage() is candidate.coverage
