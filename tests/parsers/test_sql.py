"""SQL parser: CREATE DDL definitions (no imports)."""

from __future__ import annotations


def test_table_with_schema_and_doc(parse_sql):
    src = "-- Stores application users\nCREATE TABLE myschema.users (\n  id INTEGER PRIMARY KEY\n);\n"
    out = parse_sql(src)
    assert len(out.symbols) == 1
    sym = out.symbols[0]
    assert sym.kind == "table"
    assert sym.name == "users"
    assert sym.qualname == "myschema.users"
    assert sym.docstring == "Stores application users"
    assert out.imports == []


def test_function_and_index(parse_sql):
    src = (
        "CREATE FUNCTION add_nums(a int, b int) RETURNS int AS $$ BEGIN RETURN a+b; END; $$ LANGUAGE plpgsql;\n"
        "CREATE INDEX idx_users_name ON users(name);\n"
    )
    out = parse_sql(src)
    by_name = {s.name: s for s in out.symbols}
    assert by_name["add_nums"].kind == "function"
    assert by_name["idx_users_name"].kind == "index"


def test_alter_is_not_a_definition(parse_sql):
    src = "CREATE VIEW active AS SELECT 1;\nALTER TABLE users ADD COLUMN age int;\n"
    out = parse_sql(src)
    names = {s.name for s in out.symbols}
    assert "active" in names
    assert "users" not in names  # ALTER produces no symbol
