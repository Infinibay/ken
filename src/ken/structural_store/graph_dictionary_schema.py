"""Schema 11: dictionary codes for repeated labels, paths and comparisons."""

from .graph_schema import STATEMENTS as GRAPH

FAMILIES = {
    "entities": {"kind", "path"},
    "operations": {"kind", "native_kind", "role"},
    "values": {"tag"},
    "members": {"key", "comparison"},
}
FIELDS = {
    "entities": [
        "graph_id",
        "ordinal",
        "local_id",
        "kind",
        "name",
        "path",
        "line",
        "end_line",
        "attributes",
        "owner",
        "start_byte",
        "end_byte",
        "source_owner",
    ],
    "operations": [
        "graph_id",
        "ordinal",
        "local_id",
        "kind",
        "native_kind",
        "parent",
        "role",
        "start_byte",
        "end_byte",
        "line",
        "owner",
        "attributes",
    ],
    "values": [
        "graph_id",
        "value_id",
        "signature",
        "tag",
        "text_value",
        "integer_value",
        "real_value",
    ],
    "members": ["graph_id", "parent", "ordinal", "key", "child", "comparison"],
}
REGION = "CREATE INDEX k2_graph_operation_region ON k2_graph_operations(graph_id,owner,start_byte,end_byte)"


def rebuild(encoded):
    statements = []
    for family, coded in FAMILIES.items():
        table = "k2_graph_" + family
        definition = next(
            sql for sql in GRAPH if sql.startswith("CREATE TABLE " + table + "(")
        )
        if encoded:
            for field in sorted(coded):
                definition = definition.replace(field + " TEXT", field + " INTEGER")
        statements.extend((f"ALTER TABLE {table} RENAME TO {table}_old", definition))
        joins, values = [], []
        for field in FIELDS[family]:
            if field not in coded:
                values.append("o." + field)
                continue
            alias = "d_" + field
            output, lookup = ("term_id", "text") if encoded else ("text", "term_id")
            values.append(alias + "." + output)
            joins.append(
                f"LEFT JOIN k2_graph_terms {alias} ON {alias}.graph_id=o.graph_id AND {alias}.{lookup}=o.{field}"
            )
        statements.extend(
            (
                f"INSERT INTO {table} SELECT "
                + ",".join(values)
                + f" FROM {table}_old o "
                + " ".join(joins),
                f"DROP TABLE {table}_old",
            )
        )
        statements.extend(
            sql
            for sql in GRAPH
            if sql.startswith("CREATE INDEX ") and f" ON {table}(" in sql
        )
        if family == "operations":
            statements.append(REGION)
    return tuple(statements)


words = " UNION ".join(
    f'SELECT graph_id,"{field}" AS word FROM k2_graph_{family} WHERE "{field}" IS NOT NULL'
    for family, coded in FAMILIES.items()
    for field in sorted(coded)
)
STATEMENTS = (
    # Freeze ID high-water marks before inserting; graph-local IDs remain stable.
    """CREATE TABLE k2_graph_dictionary_stage AS SELECT g.graph_id,coalesce(max(t.term_id),0) AS base
       FROM k2_graphs g LEFT JOIN k2_graph_terms t USING(graph_id) GROUP BY g.graph_id""",
    f"""WITH words AS ({words})
        INSERT INTO k2_graph_terms SELECT w.graph_id,
        s.base + row_number() OVER (PARTITION BY w.graph_id ORDER BY w.word),w.word
        FROM words w JOIN k2_graph_dictionary_stage s USING(graph_id)
        LEFT JOIN k2_graph_terms t ON t.graph_id=w.graph_id AND t.text=w.word WHERE t.term_id IS NULL""",
    "DROP TABLE k2_graph_dictionary_stage",
) + rebuild(True)
DOWN = rebuild(False)
