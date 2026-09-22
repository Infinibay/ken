"""Planner coverage and BODY's special yield coverage share one policy."""

from types import SimpleNamespace

import pytest

from ken.kql2.source_coverage import supports_general_walk, supports_pattern
from ken.structural.model import Fact


@pytest.mark.parametrize(
    "reasons, general, yielding",
    [
        (["await"], True, True),
        (["await_expression"], True, True),
        (["raise_statement"], True, True),
        (["throw_statement"], True, True),
        (["yield_statement"], False, True),
        (["yield", "await"], False, True),
        (["await", "throw_statement"], False, False),
        (["unknown_syntax"], False, False),
        ([], False, False),
    ],
)
def test_partial_reasons_preserve_the_matcher_coverage_contract(
    reasons, general, yielding
):
    statuses = [Fact("owner", "CFG_STATUS", "partial", {"reasons": reasons})]
    assert supports_general_walk(statuses) is general
    assert (
        supports_pattern(
            statuses, SimpleNamespace(clauses=[SimpleNamespace(kind="yield")])
        )
        is yielding
    )
    assert (
        supports_pattern(
            statuses, SimpleNamespace(clauses=[SimpleNamespace(kind="call")])
        )
        is general
    )


def test_missing_and_conflicting_coverage_stay_unknown():
    assert not supports_general_walk([])
    structured = Fact("owner", "CFG_STATUS", "structured")
    assert supports_general_walk([structured])
    assert not supports_general_walk(
        [structured, Fact("owner", "CFG_STATUS", "unmapped")]
    )
    assert not supports_general_walk(
        [
            Fact("owner", "CFG_STATUS", "partial", {"reasons": ["await"]}),
            Fact("owner", "CFG_STATUS", "partial", {"reasons": ["throw_statement"]}),
        ]
    )
