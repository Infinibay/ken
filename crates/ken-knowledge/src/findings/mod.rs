//! Finding persistence, code bridges, anchors and evidence-carrying graph traversal.
mod anchors;
mod graph;
mod numerical;
mod store;
use crate::Result;
pub use anchors::{anchors_for, by_anchor, set_anchors};
pub use graph::{ensure_graph, extract_refs, for_file, rebuild, recompute_edges, related};
pub use numerical::{ScalarMath, VectorMath};
use rusqlite::{Connection, OptionalExtension, params};
pub use store::{
    classify_tags, ensure_schema, forget, format_recall_hits, list, recall, remember,
    remember_with_embedding,
};
pub(super) fn meta(db: &Connection, key: &str) -> Result<Option<String>> {
    Ok(db
        .query_row("SELECT value FROM meta WHERE key=?", [key], |r| r.get(0))
        .optional()?)
}
pub(super) fn set_meta(db: &Connection, key: &str, value: &str) -> Result<()> {
    db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",params![key,value])?;
    Ok(())
}
pub(super) fn enabled(db: &Connection) -> bool {
    meta(db, "findings_graph_enabled").ok().flatten().as_deref() != Some("0")
}
pub(super) fn graph_tables(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS cr_finding_refs(finding_id INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,ref_kind TEXT NOT NULL,ref_key TEXT NOT NULL,file_id INTEGER REFERENCES ci_files(id) ON DELETE SET NULL,symbol_id INTEGER REFERENCES ci_symbols(id) ON DELETE SET NULL,method TEXT NOT NULL,resolved INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL,PRIMARY KEY(finding_id,ref_kind,ref_key));CREATE INDEX IF NOT EXISTS idx_cr_finding_refs_key ON cr_finding_refs(ref_kind,ref_key);CREATE INDEX IF NOT EXISTS idx_cr_finding_refs_file ON cr_finding_refs(file_id) WHERE file_id IS NOT NULL;CREATE TABLE IF NOT EXISTS cr_finding_edges(src INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,dst INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,edge_type TEXT NOT NULL,directed INTEGER NOT NULL DEFAULT 0,weight REAL NOT NULL,evidence TEXT NOT NULL DEFAULT '{}',updated_at INTEGER NOT NULL,PRIMARY KEY(src,dst,edge_type),CHECK(src<>dst AND weight>=0 AND weight<=1 AND (directed=1 OR src<dst)));CREATE INDEX IF NOT EXISTS idx_cr_finding_edges_dst ON cr_finding_edges(dst);")?;
    Ok(())
}
pub(super) fn guarded(db: &Connection, body: impl FnOnce() -> Result<()>) {
    if db.execute_batch("SAVEPOINT fg").is_err() {
        return;
    }
    match body() {
        Ok(()) => {
            let _ = db.execute_batch("RELEASE fg");
        }
        Err(_) => {
            let _ = db.execute_batch("ROLLBACK TO fg;RELEASE fg");
            let _ = set_meta(db, "findings_graph_version", "dirty");
        }
    }
}
