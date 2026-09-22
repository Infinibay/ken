"""Relational query snapshots: searchable columns, dictionary-coded endpoints.

The source-unit payloads in earlier migrations are acquisition caches. These
tables are the executable index: opening a graph never decodes those payloads.
"""

STATEMENTS = (
    """CREATE TABLE k2_graphs(
        graph_id INTEGER PRIMARY KEY,
        snapshot_id INTEGER NOT NULL REFERENCES k2_snapshots ON DELETE CASCADE,
        fingerprint TEXT NOT NULL UNIQUE, path TEXT NOT NULL, language TEXT NOT NULL,
        version TEXT NOT NULL, view TEXT NOT NULL, metadata INTEGER NOT NULL)""",
    """CREATE TABLE k2_graph_terms(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        term_id INTEGER NOT NULL, text TEXT NOT NULL,
        PRIMARY KEY(graph_id,term_id), UNIQUE(graph_id,text)) WITHOUT ROWID""",
    """CREATE TABLE k2_graph_values(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        value_id INTEGER NOT NULL, signature BLOB NOT NULL, tag TEXT NOT NULL,
        text_value TEXT, integer_value INTEGER, real_value REAL,
        PRIMARY KEY(graph_id,value_id), UNIQUE(graph_id,signature)) WITHOUT ROWID""",
    """CREATE TABLE k2_graph_members(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        parent INTEGER NOT NULL, ordinal INTEGER NOT NULL, key TEXT,
        child INTEGER NOT NULL, comparison TEXT NOT NULL,
        PRIMARY KEY(graph_id,parent,ordinal)) WITHOUT ROWID""",
    "CREATE INDEX k2_graph_member_key ON k2_graph_members(graph_id,parent,key)",
    "CREATE INDEX k2_graph_member_value ON k2_graph_members(graph_id,key,comparison,parent)",
    """CREATE TABLE k2_graph_entities(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        ordinal INTEGER NOT NULL, local_id INTEGER NOT NULL, kind TEXT NOT NULL,
        name TEXT NOT NULL, path TEXT NOT NULL, line INTEGER NOT NULL,
        end_line INTEGER NOT NULL, attributes INTEGER NOT NULL,
        owner INTEGER, start_byte INTEGER, end_byte INTEGER, source_owner INTEGER,
        PRIMARY KEY(graph_id,local_id), UNIQUE(graph_id,ordinal)) WITHOUT ROWID""",
    "CREATE INDEX k2_graph_entity_kind ON k2_graph_entities(graph_id,kind,name,ordinal)",
    "CREATE INDEX k2_graph_entity_owner ON k2_graph_entities(graph_id,owner,ordinal)",
    "CREATE INDEX k2_graph_entity_source_owner ON k2_graph_entities(graph_id,source_owner,ordinal)",
    "CREATE INDEX k2_graph_entity_call_span ON k2_graph_entities(graph_id,kind,owner,start_byte,end_byte)",
    """CREATE TABLE k2_graph_operations(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        ordinal INTEGER NOT NULL, local_id INTEGER NOT NULL, kind TEXT NOT NULL,
        native_kind TEXT NOT NULL, parent INTEGER, role TEXT NOT NULL,
        start_byte INTEGER NOT NULL, end_byte INTEGER NOT NULL, line INTEGER NOT NULL,
        owner INTEGER NOT NULL, attributes INTEGER NOT NULL,
        PRIMARY KEY(graph_id,ordinal)) WITHOUT ROWID""",
    "CREATE INDEX k2_graph_operation_id ON k2_graph_operations(graph_id,local_id,ordinal)",
    "CREATE INDEX k2_graph_operation_owner ON k2_graph_operations(graph_id,owner,ordinal)",
    "CREATE INDEX k2_graph_operation_kind ON k2_graph_operations(graph_id,kind,ordinal)",
    """CREATE TABLE k2_graph_facts(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        ordinal INTEGER NOT NULL, subject INTEGER NOT NULL, relation INTEGER NOT NULL,
        object INTEGER NOT NULL, attributes INTEGER NOT NULL, evidence INTEGER NOT NULL,
        PRIMARY KEY(graph_id,ordinal)) WITHOUT ROWID""",
    "CREATE INDEX k2_graph_fact_forward ON k2_graph_facts(graph_id,relation,subject,ordinal,object)",
    "CREATE INDEX k2_graph_fact_reverse ON k2_graph_facts(graph_id,relation,object,ordinal,subject)",
    "CREATE INDEX k2_graph_fact_attribute ON k2_graph_facts(graph_id,relation,attributes,ordinal)",
    "CREATE INDEX k2_graph_fact_relation ON k2_graph_facts(graph_id,relation,ordinal)",
    """CREATE TABLE k2_graph_relations(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        relation INTEGER NOT NULL, count INTEGER NOT NULL,
        PRIMARY KEY(graph_id,relation)) WITHOUT ROWID""",
    """CREATE TABLE k2_graph_capabilities(
        graph_id INTEGER NOT NULL REFERENCES k2_graphs ON DELETE CASCADE,
        capability TEXT NOT NULL, PRIMARY KEY(graph_id,capability)) WITHOUT ROWID""",
)

TABLES = (
    "k2_graph_capabilities",
    "k2_graph_relations",
    "k2_graph_facts",
    "k2_graph_operations",
    "k2_graph_entities",
    "k2_graph_members",
    "k2_graph_values",
    "k2_graph_terms",
    "k2_graphs",
)
