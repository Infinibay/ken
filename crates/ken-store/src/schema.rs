use crate::VectorSpace;
use rusqlite::{Connection, TransactionBehavior};

// One authoritative SQL resource, embedded at build time; no checkout is needed.
const SQL: &str = include_str!("../../../src/ken/schema.sql");
const COLUMNS: [(&str, &str, &str); 5] = [
    ("ci_imports", "resolution", "TEXT"),
    ("ci_files", "vec_slot", "INTEGER"),
    ("ci_symbols", "vec_slot", "INTEGER"),
    ("ci_intent_sources", "vec_slot", "INTEGER"),
    ("ci_passages", "implementation_start_line", "INTEGER"),
];

pub(crate) fn initialize(conn: &mut Connection) -> rusqlite::Result<()> {
    // PRAGMA foreign_keys inside a transaction cannot turn the setting on.
    conn.pragma_update(None, "foreign_keys", true)?;
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(SQL)?;
    for (table, column, decl) in COLUMNS {
        let exists: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM pragma_table_info(?1) WHERE name=?2 COLLATE NOCASE)",
            [table, column],
            |r| r.get(0),
        )?;
        if !exists {
            tx.execute_batch(&format!("ALTER TABLE {table} ADD COLUMN {column} {decl}"))?;
        }
    }
    tx.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_ci_imports_resolution ON ci_imports(resolution)",
    )?;
    for space in VectorSpace::ALL {
        let table = space.as_str();
        tx.execute_batch(&format!("CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_vec_slot ON {table}(vec_slot) WHERE vec_slot IS NOT NULL"))?;
        let name = match space {
            VectorSpace::Files => "trg_ci_files_free_slot",
            VectorSpace::Symbols => "trg_ci_symbols_free_slot",
            VectorSpace::IntentSources => "trg_ci_intent_free_slot",
        };
        tx.execute_batch(&format!("CREATE TRIGGER IF NOT EXISTS {name} AFTER DELETE ON {table} WHEN old.vec_slot IS NOT NULL BEGIN INSERT OR IGNORE INTO ci_vec_free(space,slot) VALUES('{table}',old.vec_slot); END"))?;
    }
    tx.commit()
}
