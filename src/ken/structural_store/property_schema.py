"""Migrate legacy scalar property JSON to native SQLite scalar values."""

CREATE = """CREATE TABLE k2_properties(node_id INTEGER NOT NULL REFERENCES k2_nodes ON DELETE CASCADE,
       key TEXT NOT NULL, tag TEXT NOT NULL, value, PRIMARY KEY(node_id,key))"""
INDEX = "CREATE INDEX k2_properties_value ON k2_properties(key,tag,value,node_id)"
STATEMENTS = (
    "DROP INDEX k2_properties_value",
    "ALTER TABLE k2_properties RENAME TO k2_properties_json",
    CREATE,
    """INSERT INTO k2_properties SELECT node_id,key,tag,
       CASE WHEN tag='Int' AND typeof(json_extract(value,'$'))='real' THEN value
            WHEN tag='Float' AND json_extract(value,'$')=0 AND substr(value,1,1)='-' THEN '-0.0'
            ELSE json_extract(value,'$') END FROM k2_properties_json""",
    "DROP TABLE k2_properties_json",
    INDEX,
)
DOWN = (
    "DROP INDEX k2_properties_value",
    "ALTER TABLE k2_properties RENAME TO k2_properties_native",
    """CREATE TABLE k2_properties(node_id INTEGER NOT NULL REFERENCES k2_nodes ON DELETE CASCADE,
       key TEXT NOT NULL, tag TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(node_id,key))""",
    """INSERT INTO k2_properties SELECT node_id,key,tag,
       CASE WHEN tag='Bool' THEN CASE WHEN value THEN 'true' ELSE 'false' END
            WHEN tag IN ('Int','Float') THEN CAST(value AS TEXT)
            ELSE json_quote(value) END FROM k2_properties_native""",
    "DROP TABLE k2_properties_native",
    INDEX,
)
