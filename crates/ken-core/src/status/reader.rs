use super::{rules::*, *};
use crate::project::{DiscoveryContext, is_file, locate_project, resolve_start};
use rusqlite::{Connection, OpenFlags};
use std::{fs, path::Path, time::Duration};

pub fn read_status(
    start: &Path,
    context: &DiscoveryContext,
    health: &dyn HealthProbe,
) -> Result<StatusReport, StatusError> {
    let Some(paths) = locate_project(start, context)? else {
        return Ok(StatusReport::MissingProject {
            error: format!(
                "no ken project found at or above {}",
                resolve_start(start, context)?.display()
            ),
        });
    };
    let raw = fs::read_to_string(paths.meta()).map_err(|source| StatusError::File {
        path: paths.meta(),
        source,
    })?;
    let meta: Value = serde_json::from_str(&raw).map_err(|source| StatusError::Json {
        path: paths.meta(),
        source,
    })?;
    let metadata = meta.as_object().ok_or_else(|| StatusError::Metadata {
        path: paths.meta(),
        reason: "expected an object",
    })?;
    let project_id = metadata
        .get("project_id")
        .ok_or_else(|| StatusError::Metadata {
            path: paths.meta(),
            reason: "missing project_id",
        })?
        .clone();
    let exists = is_file(&paths.db())?;
    let size = if exists {
        Some(
            fs::metadata(paths.db())
                .map_err(|source| StatusError::File {
                    path: paths.db(),
                    source,
                })?
                .len(),
        )
    } else {
        None
    };
    let project = ProjectStatus {
        project_root: paths.root().into(),
        project_id,
        db: DatabaseStatus {
            path: paths.db(),
            exists,
            size: format_size(size),
        },
    };
    if !exists {
        return Ok(StatusReport::MetadataOnly(project));
    }
    let (counts, indexed) = read_database(&paths.db()).map_err(|source| StatusError::Database {
        path: paths.db(),
        source,
    })?;
    let mut stale = Vec::new();
    for relative in indexed {
        let path = paths.root().join(&relative);
        if !path
            .try_exists()
            .map_err(|source| StatusError::File { path, source })?
        {
            stale.push(relative);
        }
    }
    let index_health = IndexHealth {
        stale_files: stale.len() as u64,
        sample: stale.into_iter().take(5).collect(),
    };
    let mut daemon = Map::from_iter([("running".into(), Value::Bool(false))]);
    if let Some(body) = health.probe(&paths, metadata)?.filter(|m| !m.is_empty()) {
        daemon.insert("running".into(), Value::Bool(true));
        daemon.extend(body);
    }
    Ok(StatusReport::Installed(Box::new(InstalledStatus {
        project,
        rank_signals: rank_signals(&counts),
        embedding_coverage: embedding_coverage(&counts),
        recommendations: recommendations(&counts, &index_health),
        counts,
        index_health,
        daemon,
    })))
}

fn read_database(path: &Path) -> rusqlite::Result<(StatusCounts, Vec<String>)> {
    let mut conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    conn.busy_timeout(Duration::from_millis(5000))?;
    let tx = conn.transaction()?;
    let count = |table: &str, condition: &str| {
        tx.query_row(
            &format!("SELECT COUNT(*) FROM {table}{condition}"),
            [],
            |row| {
                let value: i64 = row.get(0)?;
                u64::try_from(value).map_err(|_| rusqlite::Error::IntegralValueOutOfRange(0, value))
            },
        )
    };
    let counts = StatusCounts {
        files: count("ci_files", "")?,
        files_embedded: count(
            "ci_files",
            " WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL",
        )?,
        symbols: count("ci_symbols", "")?,
        symbols_embedded: count(
            "ci_symbols",
            " WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL",
        )?,
        sessions: count("cr_sessions", "")?,
        active_sessions: count("cr_sessions", " WHERE ended_at IS NULL")?,
        contexts: count("cr_contexts", "")?,
        prompt_contexts: count("cr_contexts", " WHERE kind = 'user_prompt'")?,
        prompt_contexts_embedded: count(
            "cr_contexts",
            " WHERE kind = 'user_prompt' AND embedding IS NOT NULL",
        )?,
        interactions: count("cr_interactions", "")?,
        session_scores: count("cr_session_scores", "")?,
        findings: count("cr_findings", "")?,
        findings_embedded: count("cr_findings", " WHERE embedding IS NOT NULL")?,
        intent_sources: count("ci_intent_sources", "")?,
        intent_sources_embedded: count(
            "ci_intent_sources",
            " WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL",
        )?,
    };
    let indexed = tx
        .prepare("SELECT path FROM ci_files ORDER BY path")?
        .query_map([], |r| r.get(0))?
        .collect::<rusqlite::Result<Vec<String>>>()?;
    tx.commit()?;
    Ok((counts, indexed))
}
