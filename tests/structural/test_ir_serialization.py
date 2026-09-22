"""Bounded IR serialization stays compatible with existing cache records."""

import json
import zlib

import pytest

from ken.structural.cache import IRCache
from ken.structural.frontend import lower_source
from ken.structural.model import IR, Entity
from ken.structural.semantic import link_project
from ken.structural.serialization import compressed_ir
from ken.structural.service import build_project


@pytest.mark.parametrize("count", [0, 1, 512, 513, 1100])
def test_streamed_json_matches_public_ir_serialization(count):
    ir = IR("árbol.py", "python", capabilities={"z", "a"}, diagnostics=["unknown"])
    for i in range(count):
        identity = str(i)
        ir.entities[identity] = Entity(
            identity,
            "CLASS",
            "árbol",
            ir.path,
            1,
            1,
            {"nested": {"list": [True, None, '"']}},
        )
        ir.add(identity, "ENTITY", "CLASS", "source")
    assert json.loads(zlib.decompress(compressed_ir(ir))) == ir.to_dict()


def test_source_operations_and_cached_ir_roundtrip(tmp_path):
    ir = lower_source("def f(x):\n return x + 1\n", "python", "sample.py")
    cache = IRCache(tmp_path / "ir.sqlite", 1)
    try:
        cache.put_ir("ir", ir)
        assert IR.from_dict(cache.get("ir")).to_dict() == ir.to_dict()
    finally:
        cache.close()


@pytest.mark.parametrize("cache_mb", [0, 1])
def test_build_does_not_clone_ir_for_cache_writes(tmp_path, monkeypatch, cache_mb):
    (tmp_path / "sample.py").write_text("def work():\n return 1\n")

    def forbidden(self):
        pytest.fail("cache serialization must not clone IR with to_dict")

    monkeypatch.setattr(IR, "to_dict", forbidden)
    graph, analysis = build_project(tmp_path, cache_mb=cache_mb)
    assert graph.entities and analysis["files"] == ["sample.py"]


def test_linking_can_transfer_private_entities_without_changing_the_graph():
    source = "class A:\n def create(self): return A()\n"
    unit = lower_source(source, "python", "sample.py")
    expected = link_project([unit])
    before = unit.to_dict()
    transferred = link_project([unit], copy_entities=False)
    assert transferred.to_dict() == expected.to_dict()
    assert all(
        transferred.entities[key] is entity for key, entity in unit.entities.items()
    )
    # The default linker still isolates changes to the source unit's metadata.
    isolated = lower_source(source, "python", "sample.py")
    link_project([isolated])
    assert isolated.to_dict() == before
