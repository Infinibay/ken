"""One-time preorder projection; syntax membership is an indexed integer range."""

from array import array
from itertools import islice

TABLES = ("k2_graph_syntax", "k2_graph_syntax_ready")
STATEMENTS = (
    """CREATE TABLE k2_graph_syntax_ready(graph_id INTEGER PRIMARY KEY REFERENCES k2_graphs ON DELETE CASCADE)""",
    """CREATE TABLE k2_graph_syntax(graph_id INTEGER NOT NULL REFERENCES k2_graph_syntax_ready ON DELETE CASCADE,
        local_id INTEGER NOT NULL, position INTEGER NOT NULL, subtree_end INTEGER NOT NULL,
        final_node INTEGER NOT NULL, PRIMARY KEY(graph_id,local_id), UNIQUE(graph_id,position)) WITHOUT ROWID""",
)


def intervals(rows):
    """Linear forest traversal, including out-of-order nodes and nested callables.

    Compact sibling arrays avoid allocating one Python list per AST node. Parent
    identity, not overlapping byte spans, defines membership. Missing parents
    form roots; cycles and duplicate identities reject publication.
    """
    ids, parents = array("q"), array("q")
    positions = {}
    for identity, parent in rows:
        if identity in positions:
            raise ValueError("duplicate syntax identity")
        positions[identity] = len(ids)
        ids.append(identity)
        parents.append(parent if parent is not None else -1)
    size = len(ids)
    first, sibling = array("q", [-1]) * (size + 1), array("q", [-1]) * size
    for i in range(size - 1, -1, -1):
        parent = positions.get(parents[i], size)
        sibling[i], first[parent] = first[parent], i
    del positions, parents
    counter, last = 0, -1
    stack = [(first[size], -1)]
    while stack:
        node, start = stack.pop()
        if node == -1:
            continue
        if start >= 0:
            yield ids[node], start, counter, last
            continue
        start = counter
        counter += 1
        last = ids[node]
        stack.extend(((sibling[node], -1), (node, start), (first[node], -1)))
    if counter != size:
        raise ValueError("cyclic syntax parentage")


def ensure(store, graph):
    if store.db.execute(
        "SELECT 1 FROM k2_graph_syntax_ready WHERE graph_id=?", (graph,)
    ).fetchone():
        return
    from .leases import renew

    with store.transaction():
        # Recheck after acquiring the writer lock.
        if store.db.execute(
            "SELECT 1 FROM k2_graph_syntax_ready WHERE graph_id=?", (graph,)
        ).fetchone():
            return
        store.db.execute("INSERT INTO k2_graph_syntax_ready VALUES (?)", (graph,))
        rows = store.db.execute(
            "SELECT local_id,parent FROM k2_graph_operations WHERE graph_id=? ORDER BY ordinal",
            (graph,),
        )
        pending = iter(intervals(rows))
        while batch := list(islice(pending, 4096)):
            renew(store)
            store.db.executemany(
                "INSERT INTO k2_graph_syntax VALUES (?,?,?,?,?)",
                ((graph, *row) for row in batch),
            )
