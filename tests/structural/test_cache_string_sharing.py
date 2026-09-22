"""Cache compaction shares text, never mutable data or cross-project state."""

import json

from ken.structural.serialization import _StringPool, decoded_json


def test_decoding_preserves_values_and_shares_repeated_ids_and_tokens():
    identifier = "sample/module.py::SomeClass/a_long_method_name"
    value = {
        identifier: {"owner": identifier, "tokens": [identifier, [identifier]]},
        "facts": [{"subject": identifier}, {"subject": identifier}],
    }
    result = decoded_json(json.dumps(value).encode())
    assert result == value
    key = next(iter(result))
    assert result[key]["owner"] is key
    assert result[key]["tokens"][1][0] is key
    assert result["facts"][0]["subject"] is key
    result["facts"][0]["subject"] = "changed"
    assert result["facts"][1]["subject"] == identifier


def test_pool_budget_limits_retention_without_changing_values():
    pool = _StringPool(max_entries=2, max_bytes=1000)
    for value in ("first", "second", "third"):
        assert pool.value(value) == value
    assert len(pool.strings) == 2
    tiny = _StringPool(max_bytes=1)
    assert tiny.value("too large") == "too large"
    assert not tiny.strings


def test_each_read_has_independent_containers_and_string_pool():
    payload = b'{"items": [{"name": "a long repeated identifier"}]}'
    first, second = decoded_json(payload), decoded_json(payload)
    first["items"][0]["name"] = "changed"
    assert second["items"][0]["name"] == "a long repeated identifier"
