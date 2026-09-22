import json
import math

from ken.structural.model import IR, Entity
from ken.structural_store import Store
from ken.structural_store.migrations import migrate, validate


def test_scalar_migration_preserves_types_and_needs_no_json_at_query_time(
    tmp_path, monkeypatch
):
    values = {
        "text": "01",
        "unicode": 'á\n"x',
        "integer": 1,
        "real": 1.5,
        "yes": True,
        "no": False,
        "null": None,
        "huge": 2**90,
        "zero": -0.0,
    }
    ir = IR(
        "a.py",
        "python",
        entities={"a": Entity("a", "CLASS", "A", "a.py", 1, 1, values)},
    )
    with Store(tmp_path / "s.sqlite") as store:
        unit = store.put_unit("a", ir, "hash", "frontend")
        snapshot = store.publish([unit], expected_parent=None)
        migrate(store.db, 7)
        encoded = dict(store.db.execute("SELECT key,value FROM k2_properties"))
        assert json.loads(encoded["yes"]) is True
        assert json.loads(encoded["text"]) == "01"
        migrate(store.db)
        from ken.structural_store.schema import VERSION
        assert validate(store.db) == VERSION
        node = next(store.scan(snapshot))
        monkeypatch.setattr(
            json,
            "loads",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("property decoded JSON")
            ),
        )
        actual = store.properties(node)
        assert {key: actual[key] for key in values} == values
        assert math.copysign(1, actual["zero"]) == -1
        types = dict(store.db.execute("SELECT key,typeof(value) FROM k2_properties"))
        assert (
            types["text"] == "text"
            and types["integer"] == "integer"
            and types["real"] == "real"
        )
