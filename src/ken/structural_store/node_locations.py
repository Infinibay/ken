"""Resolve selected source identities within one pinned snapshot."""

from collections import defaultdict


def locations(store, snapshot: int, identities: set[str]) -> dict[str, dict]:
    """Return canonical source locations without scanning every source node.

    Graph terms also contain literals and operation IDs. Only exact identities
    present in the snapshot's source-node table acquire a location.
    """
    grouped: dict[str, set[str]] = defaultdict(set)
    for identity in identities:
        if isinstance(identity, str) and "::" in identity:
            grouped[identity.partition("::")[0]].add(identity)
    result = {}
    for path, values in grouped.items():
        unit = store.db.execute(
            "SELECT unit_id FROM k2_snapshot_units WHERE snapshot_id=? AND path=?",
            (snapshot, path),
        ).fetchone()
        if unit is None:
            continue
        ordered = sorted(values)
        for offset in range(0, len(ordered), 400):
            chunk = ordered[offset : offset + 400]
            marks = ",".join("?" for _ in chunk)
            for identity, kind, name, line in store.db.execute(
                "SELECT local_id,kind,name,line FROM k2_nodes "
                f"WHERE unit_id=? AND local_id IN ({marks})",
                (unit[0], *chunk),
            ):
                result[identity] = {
                    "local_id": identity,
                    "kind": kind,
                    "name": name,
                    "path": path,
                    "line": line,
                }
    return result
