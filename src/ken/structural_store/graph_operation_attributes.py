"""Lossless operation-fact attributes backed by existing operation columns.

Negative attribute IDs address overlays; positive IDs keep the general value
codec. Only attributes proven equal to native columns are elided. The fact's
ordinal, endpoints, evidence and additional attributes remain unchanged.
"""

CORE = frozenset({"kind", "native_kind", "owner", "role", "start_byte", "end_byte"})
TABLES = ("k2_graph_operation_attributes",)
STATEMENTS = (
    """CREATE TABLE k2_graph_operation_attributes(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        fact_ordinal INTEGER NOT NULL, operation_ordinal INTEGER NOT NULL,
        kind INTEGER NOT NULL, residual INTEGER NOT NULL,
        PRIMARY KEY(graph_id,fact_ordinal)) WITHOUT ROWID""",
    "CREATE INDEX k2_graph_operation_attributes_operation ON k2_graph_operation_attributes(graph_id,operation_ordinal,fact_ordinal)",
    "CREATE INDEX k2_graph_operation_attributes_kind ON k2_graph_operation_attributes(graph_id,kind,fact_ordinal)",
    "CREATE INDEX k2_graph_operation_attributes_residual ON k2_graph_operation_attributes(graph_id,residual,fact_ordinal)",
    "CREATE INDEX k2_graph_operation_native_kind ON k2_graph_operations(graph_id,native_kind,ordinal)",
    "CREATE INDEX k2_graph_operation_role ON k2_graph_operations(graph_id,role,ordinal)",
    "CREATE INDEX k2_graph_operation_start ON k2_graph_operations(graph_id,start_byte,ordinal)",
    "CREATE INDEX k2_graph_operation_end ON k2_graph_operations(graph_id,end_byte,ordinal)",
)
# Earlier readers cannot decode overlays. Discard only affected derived graphs;
# source units and ordinary graphs survive and can be projected again.
DOWN = (
    "DELETE FROM k2_graphs WHERE graph_id IN (SELECT graph_id FROM k2_graph_operation_attributes)",
    "DROP TABLE k2_graph_operation_attributes",
    "DROP INDEX k2_graph_operation_native_kind",
    "DROP INDEX k2_graph_operation_role",
    "DROP INDEX k2_graph_operation_start",
    "DROP INDEX k2_graph_operation_end",
)


class OperationAttributes:
    def __init__(self, db, graph, values, terms):
        self.db, self.graph, self.values, self.terms = db, graph, values, terms
        self.pending = iter(())
        self.next_ordinal = 0
        self.current = None

    def operation(self, identity):
        # Producer facts normally follow operation order. Fetch bounded pages,
        # closing each cursor before a commit so readers cannot pin the WAL.
        if self.current is None or self.current[1] != identity:
            self.current = next(self.pending, None)
            if self.current is None:
                rows = self.db.execute(
                    """SELECT ordinal,local_id,native_kind,owner,role,start_byte,end_byte
                       FROM k2_graph_operations WHERE graph_id=? AND ordinal>=?
                       ORDER BY ordinal LIMIT 4096""",
                    (self.graph, self.next_ordinal),
                ).fetchall()
                if rows:
                    self.next_ordinal = rows[-1][0] + 1
                self.pending = iter(rows)
                self.current = next(self.pending, None)
        if self.current is not None and self.current[1] == identity:
            return self.current
        return self.db.execute(
            """SELECT ordinal,local_id,native_kind,owner,role,start_byte,end_byte
               FROM k2_graph_operations WHERE graph_id=? AND local_id=? ORDER BY ordinal LIMIT 1""",
            (self.graph, identity),
        ).fetchone()

    def put(self, ordinal, fact):
        attrs = fact.attrs
        if fact.relation != "OPERATION" or not CORE <= attrs.keys():
            return self.values.put(attrs)
        if any(
            type(attrs[k]) is not str for k in ("kind", "native_kind", "owner", "role")
        ) or any(type(attrs[k]) is not int for k in ("start_byte", "end_byte")):
            return self.values.put(attrs)
        row = self.operation(self.terms.put(fact.subject))
        native = (
            self.terms.put(attrs["native_kind"]),
            self.terms.put(attrs["owner"]),
            self.terms.put(attrs["role"]),
            attrs["start_byte"],
            attrs["end_byte"],
        )
        if row is None or row[2:] != native:
            return self.values.put(attrs)
        residual = self.values.put({k: v for k, v in attrs.items() if k not in CORE})
        self.db.execute(
            "INSERT INTO k2_graph_operation_attributes VALUES (?,?,?,?,?)",
            (self.graph, ordinal, row[0], self.terms.put(attrs["kind"]), residual),
        )
        return -ordinal - 1


def encoded(reader, value):
    row = reader.db.execute(
        """SELECT a.kind,o.native_kind,o.owner,o.role,o.start_byte,o.end_byte,a.residual
           FROM k2_graph_operation_attributes a JOIN k2_graph_operations o
           ON o.graph_id=a.graph_id AND o.ordinal=a.operation_ordinal
           WHERE a.graph_id=? AND a.fact_ordinal=?""",
        (reader.graph, -value - 1),
    ).fetchone()
    if row is None:
        raise ValueError("missing operation attribute overlay")
    return (
        "operation_attributes",
        tuple(reader.words.get(code) for code in row[:4]) + row[4:],
    )


def decode(reader, row):
    kind, native, owner, role, start, end, residual = row[1]
    return {
        **reader.get(residual),
        "kind": kind,
        "native_kind": native,
        "owner": owner,
        "role": role,
        "start_byte": start,
        "end_byte": end,
    }


def member(reader, row, key):
    """Read a native column or one residual member without expanding the rest."""
    columns = ("kind", "native_kind", "owner", "role", "start_byte", "end_byte")
    if key in CORE:
        return row[1][columns.index(key)]
    return reader.member(row[1][-1], key)


def candidates(index, key, comparisons, *, operations=True, correlated=False):
    """Attribute IDs from ordinary values and native overlays, using exact keys.

    A bound subject already selects its facts through the forward index. In that
    case correlate membership with ``f.attributes`` instead of materializing the
    matching attributes of the entire project for every subject in a join.
    """
    key_code = index.term(key)
    codes = [code for text in comparisons if (code := index.term(text)) is not None]
    ordinary = (
        "SELECT parent FROM k2_graph_members WHERE graph_id=? AND key=? AND comparison IN ("
        + ",".join("?" for _ in codes)
        + ")"
    )
    params = [index.graph, key_code, *codes]
    selected = ordinary + (" AND parent=f.attributes" if correlated else "")
    if not operations:
        return selected, tuple(params)
    base = "SELECT -a.fact_ordinal-1 FROM k2_graph_operation_attributes a"
    occurrence = " AND a.fact_ordinal=-f.attributes-1" if correlated else ""
    if key not in CORE:
        residual = (
            "EXISTS (" + ordinary + " AND parent=a.residual)"
            if correlated
            else "a.residual IN (" + ordinary + ")"
        )
        return (
            selected
            + " UNION ALL "
            + base
            + " WHERE a.graph_id=?"
            + occurrence
            + " AND "
            + residual,
            (*params, index.graph, *params),
        )
    columns = {
        "kind": "a.kind",
        "native_kind": "o.native_kind",
        "owner": "o.owner",
        "role": "o.role",
        "start_byte": "o.start_byte",
        "end_byte": "o.end_byte",
    }
    values = codes
    if key in ("start_byte", "end_byte"):
        values = []
        for text in comparisons:
            try:
                value = int(text)
            except ValueError:
                continue
            if str(value) == text and -(2**63) <= value < 2**63:
                values.append(value)
    if not values:
        return selected, tuple(params)
    if key != "kind":
        base += " JOIN k2_graph_operations o ON o.graph_id=a.graph_id AND o.ordinal=a.operation_ordinal"
    sql = (
        selected
        + " UNION ALL "
        + base
        + " WHERE a.graph_id=? AND "
        + columns[key]
        + " IN ("
        + ",".join("?" for _ in values)
        + ")"
        + occurrence
    )
    return sql, (*params, index.graph, *values)
