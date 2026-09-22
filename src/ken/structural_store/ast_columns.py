"""Schema 9: native canonical AST records and explicit syntax-body intervals.

Layouts are frozen migration data. Tuple fields live in ordered member rows;
string fields contain unit-local string IDs. No node payload needs JSON decoding.
"""

from .ast_schema import STATEMENTS as LEGACY
from .ast_schema import TABLES as LEGACY_TABLES

LAYOUTS = {
    "nodes": (
        "id kind category parent ordinal role native_role native_kind source_id start end line scope owner name text operator type_kind flags subtree_end argument_kind argument_name argument_position source_position",
        "kind category role native_role native_kind source_id owner name text operator type_kind argument_kind argument_name",
        "flags",
    ),
    "scopes": (
        "id parent node kind name namespace lookup_parent global_names nonlocal_names",
        "kind name namespace",
        "global_names nonlocal_names",
    ),
    "symbols": (
        "id name scope declaration kind source_id visible_from initialized_from type_kind native_type mutable flags position parameter_kind native_position",
        "name kind source_id type_kind native_type parameter_kind",
        "flags",
    ),
    "references": (
        "node name scope mode symbol status reason availability",
        "name mode status reason availability",
        "",
    ),
}
IDENTITIES = {
    "nodes": "node_id",
    "scopes": "scope_id",
    "symbols": "symbol_id",
    "references": "node_id",
}


def column(family, field):
    if field == "id":
        return IDENTITIES[family]
    return {"start": "start_byte", "end": "end_byte", "node": "node_id"}.get(
        field, field
    )


def columns(family):
    names, _, tuples = LAYOUTS[family]
    return tuple(
        column(family, name) for name in names.split() if name not in tuples.split()
    )


NATIVE = [
    "CREATE TABLE k2_ast_units(unit_id INTEGER PRIMARY KEY REFERENCES k2_units ON DELETE CASCADE, version TEXT NOT NULL)",
    LEGACY[1],
    LEGACY[2],
]
for family in LAYOUTS:
    fields = ",".join('"' + name + '" INTEGER' for name in columns(family))
    NATIVE.append(f"""CREATE TABLE k2_ast_{family}(unit_id INTEGER NOT NULL REFERENCES k2_ast_units ON DELETE CASCADE,
        {fields}, PRIMARY KEY(unit_id,{IDENTITIES[family]})) WITHOUT ROWID""")
NATIVE.extend(
    sql
    for sql in LEGACY
    if sql.startswith("CREATE INDEX k2_ast_") and "string" not in sql
)
NATIVE.extend(
    [
        LEGACY[-2],
        """CREATE TABLE k2_ast_members(unit_id INTEGER NOT NULL REFERENCES k2_ast_units ON DELETE CASCADE,
        family TEXT NOT NULL, record_id INTEGER NOT NULL, field TEXT NOT NULL, ordinal INTEGER NOT NULL,
        value INTEGER NOT NULL, PRIMARY KEY(unit_id,family,record_id,field,ordinal)) WITHOUT ROWID""",
        """CREATE TABLE k2_ast_diagnostics(unit_id INTEGER NOT NULL REFERENCES k2_ast_units ON DELETE CASCADE,
        ordinal INTEGER NOT NULL, message TEXT NOT NULL, PRIMARY KEY(unit_id,ordinal)) WITHOUT ROWID""",
        """CREATE TABLE k2_ast_bodies(unit_id INTEGER NOT NULL REFERENCES k2_ast_units ON DELETE CASCADE,
        owner INTEGER NOT NULL, relation TEXT NOT NULL, root INTEGER NOT NULL,
        subtree_end INTEGER NOT NULL, final_node INTEGER NOT NULL,
        PRIMARY KEY(unit_id,owner,relation,root)) WITHOUT ROWID""",
    ]
)
# Link indexes must follow their table.
NATIVE.remove(LEGACY[-1])
NATIVE.append(LEGACY[-1])
TABLES = ("k2_ast_bodies", "k2_ast_diagnostics", "k2_ast_members") + LEGACY_TABLES
STATEMENTS = (
    tuple("DROP TABLE " + table for table in LEGACY_TABLES)
    + tuple(NATIVE)
    + (
        "CREATE INDEX k2_graph_operation_region ON k2_graph_operations(graph_id,owner,start_byte,end_byte)",
    )
)
DOWN = (
    ("DROP INDEX k2_graph_operation_region",)
    + tuple("DROP TABLE " + table for table in TABLES)
    + LEGACY
)
