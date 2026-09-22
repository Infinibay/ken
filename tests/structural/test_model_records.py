"""Compact records preserve mutation, copy and diagnostic snapshot contracts."""

import copy
import pickle
from dataclasses import asdict, fields, make_dataclass, replace
from unittest.mock import patch

import pytest

from ken.structural import model
from ken.structural.model import Entity, Fact, Operation


@pytest.mark.parametrize(
    "record",
    [
        Entity("id", "CALL", "work", "sample.py", 1, 2, {"owner": "method"}),
        Fact("a", "CALLS", "b", {"execution": "possible"}, ["sample.py:1"]),
        Operation(
            "op", "CALL", "call", None, "body", 0, 10, 1, "owner", {"tokens": ["work"]}
        ),
    ],
)
def test_records_keep_copy_replace_and_pickle_behavior(record):
    expected = asdict(record)
    assert asdict(pickle.loads(pickle.dumps(record))) == expected
    cloned = copy.deepcopy(record)
    cloned.attrs["new"] = "value"
    assert "new" not in record.attrs
    assert replace(record, attrs={}).attrs == {}
    record.attrs["mutable"] = True
    assert record.attrs["mutable"] is True


@pytest.mark.parametrize(
    "kind, values",
    [
        (Entity, ("id", "CALL", "work", "sample.py", 1, 2, {})),
        (Fact, ("a", "CALLS", "b", {}, [])),
        (Operation, ("op", "CALL", "call", None, "body", 0, 10, 1, "owner", {})),
    ],
)
def test_pre_slots_diagnostic_snapshots_remain_readable(kind, values):
    legacy = make_dataclass(
        kind.__name__, [(field.name, field.type) for field in fields(kind)]
    )
    legacy.__module__ = model.__name__
    with patch.object(model, kind.__name__, legacy):
        payload = pickle.dumps(legacy(*values))
    restored = pickle.loads(payload)
    assert isinstance(restored, kind)
    assert asdict(restored) == asdict(kind(*values))
