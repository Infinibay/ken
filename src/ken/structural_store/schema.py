"""Epoch 2 bootstrap schema. Only the dedicated structural store owns these tables."""
from hashlib import sha256

APPLICATION_ID = 0x4B514C32
VERSION = 14
BASE_STATEMENTS = (
    'CREATE TABLE k2_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    'CREATE TABLE k2_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)',
    '''CREATE TABLE k2_units(unit_id INTEGER PRIMARY KEY, unit_key TEXT NOT NULL UNIQUE,
       path TEXT NOT NULL, language TEXT NOT NULL, source_hash TEXT NOT NULL,
       frontend_hash TEXT NOT NULL, payload BLOB NOT NULL, coverage INTEGER NOT NULL CHECK(coverage IN (0,1)))''',
    '''CREATE TABLE k2_nodes(node_id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL REFERENCES k2_units ON DELETE CASCADE,
       local_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT, owner TEXT,
       line INTEGER NOT NULL, end_line INTEGER NOT NULL, UNIQUE(unit_id, local_id))''',
    'CREATE INDEX k2_nodes_kind_name ON k2_nodes(kind,name,unit_id,node_id)',
    'CREATE INDEX k2_nodes_owner ON k2_nodes(unit_id,owner,kind,node_id)',
    '''CREATE TABLE k2_properties(node_id INTEGER NOT NULL REFERENCES k2_nodes ON DELETE CASCADE,
       key TEXT NOT NULL, tag TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(node_id,key))''',
    'CREATE INDEX k2_properties_value ON k2_properties(key,tag,value,node_id)',
    '''CREATE TABLE k2_facts(unit_id INTEGER NOT NULL REFERENCES k2_units ON DELETE CASCADE,
       ordinal INTEGER NOT NULL, subject TEXT NOT NULL, relation TEXT NOT NULL, object TEXT NOT NULL,
       context TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(unit_id,ordinal))''',
    'CREATE INDEX k2_facts_forward ON k2_facts(unit_id,relation,subject,object)',
    'CREATE INDEX k2_facts_reverse ON k2_facts(unit_id,relation,object,subject)',
    '''CREATE TABLE k2_snapshots(snapshot_id INTEGER PRIMARY KEY, manifest TEXT NOT NULL UNIQUE,
       profile TEXT NOT NULL, coverage INTEGER NOT NULL CHECK(coverage IN (0,1)))''',
    '''CREATE TABLE k2_snapshot_units(snapshot_id INTEGER NOT NULL REFERENCES k2_snapshots ON DELETE CASCADE,
       unit_id INTEGER NOT NULL REFERENCES k2_units, path TEXT NOT NULL,
       PRIMARY KEY(snapshot_id,path), UNIQUE(snapshot_id,unit_id))''',
    'CREATE INDEX k2_membership_reverse ON k2_snapshot_units(unit_id,snapshot_id)',
)
ARTIFACT_STATEMENTS = (
    '''CREATE TABLE k2_artifacts(artifact_key TEXT PRIMARY KEY, kind TEXT NOT NULL,
       codec TEXT NOT NULL, checksum TEXT NOT NULL, payload BLOB NOT NULL,
       snapshot_id INTEGER REFERENCES k2_snapshots ON DELETE CASCADE,
       touched INTEGER NOT NULL, bytes INTEGER NOT NULL)''',
    'CREATE INDEX k2_artifacts_lru ON k2_artifacts(touched,artifact_key)',
)
LEASE_STATEMENTS = (
    '''CREATE TABLE k2_leases(lease_id TEXT PRIMARY KEY,
       snapshot_id INTEGER REFERENCES k2_snapshots ON DELETE CASCADE,
       expires_ns INTEGER NOT NULL)''',
    'CREATE INDEX k2_leases_snapshot ON k2_leases(snapshot_id,expires_ns)',
)
SEMANTIC_STATEMENTS = (
    '''CREATE TABLE k2_analysis(snapshot_id INTEGER PRIMARY KEY REFERENCES k2_snapshots ON DELETE CASCADE,
       capabilities TEXT NOT NULL, diagnostics TEXT NOT NULL)''',
    '''CREATE TABLE k2_semantic_facts(snapshot_id INTEGER NOT NULL REFERENCES k2_analysis ON DELETE CASCADE,
       ordinal INTEGER NOT NULL, subject TEXT NOT NULL, relation TEXT NOT NULL, object TEXT NOT NULL,
       context TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(snapshot_id,ordinal))''',
    'CREATE INDEX k2_semantic_forward ON k2_semantic_facts(snapshot_id,relation,subject,object)',
    'CREATE INDEX k2_semantic_reverse ON k2_semantic_facts(snapshot_id,relation,object,subject)',
)
CONTEXT_STATEMENTS = (
    '''CREATE TABLE k2_operation_units(unit_id INTEGER PRIMARY KEY REFERENCES k2_units ON DELETE CASCADE)''',
    '''CREATE TABLE k2_operations(unit_id INTEGER NOT NULL REFERENCES k2_operation_units ON DELETE CASCADE,
       local_id TEXT NOT NULL, owner TEXT NOT NULL, parent TEXT, kind TEXT NOT NULL,
       native_kind TEXT NOT NULL, role TEXT NOT NULL, start_byte INTEGER NOT NULL,
       end_byte INTEGER NOT NULL, line INTEGER NOT NULL, attributes TEXT NOT NULL,
       entity_id TEXT, PRIMARY KEY(unit_id,local_id))''',
    'CREATE INDEX k2_operations_owner ON k2_operations(unit_id,owner,start_byte,end_byte)',
    'CREATE INDEX k2_operations_parent ON k2_operations(unit_id,parent,start_byte)',
)
from .ast_schema import STATEMENTS as AST_STATEMENTS, TABLES as AST_TABLES
from .graph_schema import STATEMENTS as GRAPH_STATEMENTS, TABLES as GRAPH_TABLES
from .property_schema import STATEMENTS as PROPERTY_STATEMENTS, DOWN as PROPERTY_DOWN
from .ast_columns import STATEMENTS as AST_COLUMN_STATEMENTS, TABLES as AST_COLUMN_TABLES, DOWN as AST_COLUMN_DOWN
from .graph_syntax import STATEMENTS as SYNTAX_STATEMENTS, TABLES as SYNTAX_TABLES

from .graph_publication import STATEMENTS as PUBLICATION_STATEMENTS, TABLES as PUBLICATION_TABLES

from .graph_dictionary_schema import STATEMENTS as DICTIONARY_STATEMENTS, DOWN as DICTIONARY_DOWN

from .graph_operation_attributes import STATEMENTS as OPERATION_ATTRIBUTE_STATEMENTS, TABLES as OPERATION_ATTRIBUTE_TABLES, DOWN as OPERATION_ATTRIBUTE_DOWN

# BODY navigation uses owner/range indexes. Global role and byte-offset indexes
# penalize every operation insertion without helping those access paths.
OPERATION_INDEX_TRIM = (
    'DROP INDEX k2_graph_operation_role',
    'DROP INDEX k2_graph_operation_start',
    'DROP INDEX k2_graph_operation_end',
)
OPERATION_INDEX_RESTORE = (
    'CREATE INDEX k2_graph_operation_role ON k2_graph_operations(graph_id,role,ordinal)',
    'CREATE INDEX k2_graph_operation_start ON k2_graph_operations(graph_id,start_byte,ordinal)',
    'CREATE INDEX k2_graph_operation_end ON k2_graph_operations(graph_id,end_byte,ordinal)',
)
REDUNDANT_INDEX_TRIM = (
    'DROP INDEX k2_graph_member_key',
    'DROP INDEX k2_graph_operation_region',
)
REDUNDANT_INDEX_RESTORE = (
    'CREATE INDEX k2_graph_member_key ON k2_graph_members(graph_id,parent,key)',
    'CREATE INDEX k2_graph_operation_region ON k2_graph_operations(graph_id,owner,start_byte,end_byte)',
)

MIGRATIONS = {
    1: BASE_STATEMENTS,
    2: ARTIFACT_STATEMENTS,
    3: LEASE_STATEMENTS,
    4: SEMANTIC_STATEMENTS,
    5: CONTEXT_STATEMENTS,
    6: AST_STATEMENTS,
    7: GRAPH_STATEMENTS,
    8: PROPERTY_STATEMENTS,
    9: AST_COLUMN_STATEMENTS + SYNTAX_STATEMENTS,
    10: PUBLICATION_STATEMENTS,
    11: DICTIONARY_STATEMENTS,
    12: OPERATION_ATTRIBUTE_STATEMENTS,
    13: OPERATION_INDEX_TRIM,
    14: REDUNDANT_INDEX_TRIM,
}
CHECKSUMS = {v: sha256('\n'.join(sql).encode()).hexdigest() for v, sql in MIGRATIONS.items()}
STATEMENTS = tuple(sql for statements in MIGRATIONS.values() for sql in statements)
CHECKSUM = CHECKSUMS[VERSION]
BASE_TABLES = ('k2_snapshot_units', 'k2_snapshots', 'k2_facts', 'k2_properties', 'k2_nodes', 'k2_units', 'k2_migrations', 'k2_meta')

TABLES_BY_VERSION: dict[int, tuple[str, ...]] = {1: BASE_TABLES}
for version, added in (
    (2, ('k2_artifacts',)),
    (3, ('k2_leases',)),
    (4, ('k2_semantic_facts', 'k2_analysis')),
    (5, ('k2_operations', 'k2_operation_units')),
    (6, AST_TABLES),
    (7, GRAPH_TABLES),
    (8, ()),
):
    TABLES_BY_VERSION[version] = added + TABLES_BY_VERSION[version - 1]
TABLES_BY_VERSION[9] = SYNTAX_TABLES + AST_COLUMN_TABLES + GRAPH_TABLES + TABLES_BY_VERSION[5]
TABLES_BY_VERSION[10] = PUBLICATION_TABLES + TABLES_BY_VERSION[9]
TABLES_BY_VERSION[11] = TABLES_BY_VERSION[10]
TABLES_BY_VERSION[12] = OPERATION_ATTRIBUTE_TABLES + TABLES_BY_VERSION[11]
TABLES_BY_VERSION[13] = TABLES_BY_VERSION[12]
TABLES_BY_VERSION[14] = TABLES_BY_VERSION[13]
TABLES = TABLES_BY_VERSION[VERSION]
DOWN = {
    1: tuple(f'DROP TABLE {name}' for name in BASE_TABLES),
    2: ('DROP TABLE k2_artifacts',),
    3: ('DROP TABLE k2_leases',),
    4: ('DROP TABLE k2_semantic_facts', 'DROP TABLE k2_analysis'),
    5: ('DROP TABLE k2_operations', 'DROP TABLE k2_operation_units'),
    6: tuple('DROP TABLE ' + name for name in AST_TABLES),
    7: tuple('DROP TABLE ' + name for name in GRAPH_TABLES),
    8: PROPERTY_DOWN,
    9: tuple('DROP TABLE ' + name for name in SYNTAX_TABLES) + AST_COLUMN_DOWN,
    10: ('DROP TABLE k2_graph_publications',),
    11: DICTIONARY_DOWN,
    12: OPERATION_ATTRIBUTE_DOWN,
    13: OPERATION_INDEX_RESTORE,
    14: REDUNDANT_INDEX_RESTORE,
}
