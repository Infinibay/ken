//! Adapt explicit SQLite facts to the authoritative, upgrade-safe ModelPolicy.
use crate::{Result, RetrievalError};
use ken_models::model_policy::{ModelPolicy, ProjectModelFacts, ProjectModelResolution};
use rusqlite::{Connection, OptionalExtension, params};
fn table(conn: &Connection, name: &str) -> Result<bool> {
    Ok(conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?)",
        [name],
        |r| r.get(0),
    )?)
}
fn facts(conn: &Connection) -> Result<ProjectModelFacts> {
    let recorded_model = if table(conn, "meta")? {
        conn.query_row("SELECT value FROM meta WHERE key='embed_model'", [], |r| {
            r.get::<_, Option<String>>(0)
        })
        .optional()?
        .flatten()
    } else {
        None
    };
    let file_vectors_present = if table(conn, "ci_files")? {
        let mut statement = conn.prepare("PRAGMA table_info(ci_files)")?;
        let columns = statement
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let present = columns
            .iter()
            .filter(|name| matches!(name.as_str(), "embedding" | "vec_slot"))
            .map(|name| format!("{name} IS NOT NULL"))
            .collect::<Vec<_>>();
        if present.is_empty() {
            false
        } else {
            conn.query_row(
                &format!(
                    "SELECT EXISTS(SELECT 1 FROM ci_files WHERE {})",
                    present.join(" OR ")
                ),
                [],
                |r| r.get(0),
            )?
        }
    } else {
        false
    };
    Ok(ProjectModelFacts {
        recorded_model,
        file_vectors_present,
    })
}
pub fn resolve_project(
    conn: &Connection,
    policy: &ModelPolicy,
    environment_model: Option<&str>,
) -> Result<ProjectModelResolution> {
    Ok(policy.resolve_project(&facts(conn)?, environment_model))
}
/// Pin only a proven fresh project, in the same SQLite snapshot as its facts.
/// A missing/read-only/corrupt input cannot be mistaken for empty vector storage.
pub fn configure_project(
    conn: &Connection,
    policy: &ModelPolicy,
    environment_model: Option<&str>,
) -> Result<ProjectModelResolution> {
    static SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let savepoint = format!(
        "project_embedding_{}",
        SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    );
    conn.execute_batch(&format!("SAVEPOINT {savepoint}"))?;
    let result: Result<ProjectModelResolution> = (|| {
        let selected = resolve_project(conn, policy, environment_model)?;
        if let Some(pin) = &selected.initial_pin {
            conn.execute_batch("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)")?;
            for (key, value) in [
                ("embed_model", pin.model.clone()),
                ("embed_doc_space", pin.document_space.to_string()),
            ] {
                conn.execute("INSERT INTO meta(key,value)VALUES(?,?)ON CONFLICT(key)DO UPDATE SET value=excluded.value",params![key,value])?;
            }
        }
        Ok(selected)
    })();
    match result {
        Ok(selected) => {
            conn.execute_batch(&format!("RELEASE {savepoint}"))?;
            Ok(selected)
        }
        Err(error) => {
            conn.execute_batch(&format!("ROLLBACK TO {savepoint};RELEASE {savepoint}"))
                .map_err(|rollback| {
                    RetrievalError::Invalid(format!("{error}; embedding pin rollback: {rollback}"))
                })?;
            Err(error)
        }
    }
}
