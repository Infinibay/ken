"""Lossless dictionary storage for repeated semantic fact identities."""

TABLES = ('k2_semantic_rows', 'k2_semantic_terms')
TABLE_STATEMENTS = (
    '''CREATE TABLE k2_semantic_terms(snapshot_id INTEGER NOT NULL REFERENCES k2_analysis ON DELETE CASCADE,
       term_id INTEGER NOT NULL, text TEXT NOT NULL,
       PRIMARY KEY(snapshot_id,term_id), UNIQUE(snapshot_id,text)) WITHOUT ROWID''',
    '''CREATE TABLE k2_semantic_rows(snapshot_id INTEGER NOT NULL REFERENCES k2_analysis ON DELETE CASCADE,
       ordinal INTEGER NOT NULL, subject INTEGER NOT NULL, relation INTEGER NOT NULL, object INTEGER NOT NULL,
       context TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(snapshot_id,ordinal))''',
)
INDEX_STATEMENTS = (
    'CREATE INDEX k2_semantic_row_forward ON k2_semantic_rows(snapshot_id,relation,subject,object)',
    'CREATE INDEX k2_semantic_row_reverse ON k2_semantic_rows(snapshot_id,relation,object,subject)',
)
VIEW = '''CREATE VIEW k2_semantic_facts AS
    SELECT f.snapshot_id,f.ordinal,s.text AS subject,r.text AS relation,o.text AS object,f.context,f.evidence
    FROM k2_semantic_rows f
    JOIN k2_semantic_terms s ON s.snapshot_id=f.snapshot_id AND s.term_id=f.subject
    JOIN k2_semantic_terms r ON r.snapshot_id=f.snapshot_id AND r.term_id=f.relation
    JOIN k2_semantic_terms o ON o.snapshot_id=f.snapshot_id AND o.term_id=f.object'''

STATEMENTS = (
    'ALTER TABLE k2_semantic_facts RENAME TO k2_semantic_facts_old',
) + TABLE_STATEMENTS + (
    '''WITH words AS (
       SELECT snapshot_id,subject AS text FROM k2_semantic_facts_old UNION
       SELECT snapshot_id,relation FROM k2_semantic_facts_old UNION
       SELECT snapshot_id,object FROM k2_semantic_facts_old)
       INSERT INTO k2_semantic_terms
       SELECT snapshot_id,row_number() OVER (PARTITION BY snapshot_id ORDER BY text),text FROM words''',
    '''INSERT INTO k2_semantic_rows
       SELECT f.snapshot_id,f.ordinal,s.term_id,r.term_id,o.term_id,f.context,f.evidence
       FROM k2_semantic_facts_old f
       JOIN k2_semantic_terms s ON s.snapshot_id=f.snapshot_id AND s.text=f.subject
       JOIN k2_semantic_terms r ON r.snapshot_id=f.snapshot_id AND r.text=f.relation
       JOIN k2_semantic_terms o ON o.snapshot_id=f.snapshot_id AND o.text=f.object''',
    'DROP TABLE k2_semantic_facts_old',
) + INDEX_STATEMENTS + (VIEW,)

RESTORE_ROWS = '''INSERT INTO k2_semantic_facts
    SELECT f.snapshot_id,f.ordinal,s.text,r.text,o.text,f.context,f.evidence
    FROM k2_semantic_rows f
    JOIN k2_semantic_terms s ON s.snapshot_id=f.snapshot_id AND s.term_id=f.subject
    JOIN k2_semantic_terms r ON r.snapshot_id=f.snapshot_id AND r.term_id=f.relation
    JOIN k2_semantic_terms o ON o.snapshot_id=f.snapshot_id AND o.term_id=f.object'''
