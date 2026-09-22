"""Body membership stays structural, indexed, branch-specific and JSON-free."""

import json

import pytest

from ken.common_ast import normalize
from ken.structural.frontend import lower_source
from ken.structural_store import Store
from ken.structural_store.common_ast import View, load
from ken.structural_store.graph_syntax import intervals
from ken.structural_store.migrations import migrate

SOURCE = """class A:
 def f(self,x):
  if x:
   while x:
    x-=1
  else:
   for y in x:
    pass
  def nested():
   return 2
  return x
"""


def test_native_ast_body_ranges_and_migration(tmp_path, monkeypatch):
    ir = lower_source(SOURCE, "python", "a.py")
    expected = normalize(ir)
    with Store(tmp_path / "s.db") as store:
        unit = store.put_unit("key", ir, "hash", "frontend")
        migrate(store.db, 8)
        migrate(store.db)
        # Schema 9 only invalidates the derived AST, retaining the source unit.
        assert store.load_unit(unit).to_dict() == ir.to_dict()
        view = View(store, unit)
        monkeypatch.setattr(
            json, "loads", lambda *a, **k: pytest.fail("AST parsed JSON")
        )
        assert load(store, unit) == expected
        branch = next(view.nodes(kind="if"))
        (yes,) = view.bodies(branch.id)
        (no,) = view.bodies(branch.id, "else")
        assert yes.subtree_end <= no.root
        assert list(view.body_nodes(branch.id)) == list(
            expected.nodes[yes.root : yes.subtree_end]
        )
        assert list(view.body_nodes(branch.id, "else")) == list(
            expected.nodes[no.root : no.subtree_end]
        )
        for kind in ("module", "type_declaration", "callable", "while", "for", "block"):
            for owner in view.nodes(kind=kind):
                ranges = view.bodies(owner.id)
                assert ranges
                members = list(view.body_nodes(owner.id))
                assert len({n.id for n in members}) == len(members)
                for body in ranges:
                    stored = store.db.execute(
                        "SELECT final_node FROM k2_ast_bodies WHERE unit_id=? AND owner=? AND relation=? AND root=?",
                        (unit, owner.id, body.relation, body.root),
                    ).fetchone()[0]
                    assert stored == body.final_node == body.subtree_end - 1
        plan = store.db.execute(
            "EXPLAIN QUERY PLAN SELECT node_id FROM k2_ast_nodes WHERE unit_id=? AND node_id>=? AND node_id<?",
            (unit, yes.root, yes.subtree_end),
        ).fetchall()
        assert any("PRIMARY KEY" in row[3] and "node_id>" in row[3] for row in plan)


def test_preorder_intervals_support_out_of_order_nodes_and_multiple_roots():
    rows = [(30, 10), (10, None), (40, 30), (20, None), (50, 10)]
    bounds = {
        identity: (start, end, last) for identity, start, end, last in intervals(rows)
    }
    assert bounds == {
        10: (0, 4, 50),
        30: (1, 3, 40),
        40: (2, 3, 40),
        50: (3, 4, 50),
        20: (4, 5, 20),
    }
    with pytest.raises(ValueError, match="cyclic"):
        list(intervals([(1, 2), (2, 1)]))
    with pytest.raises(ValueError, match="duplicate"):
        list(intervals([(1, None), (1, None)]))
