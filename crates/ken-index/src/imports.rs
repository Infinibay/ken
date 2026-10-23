//! Persist resolutions from the accepted import catalog; no language rules live here.
use crate::{IndexError, Result};
use ken_core::imports::{ImportCatalog, ImportRequest, Resolution};
use rusqlite::{Connection, params};
use std::{collections::HashMap, path::Path};
pub fn resolve_missing_edges(conn: &Connection, root: Option<&Path>) -> Result<()> {
    let mut query=conn.prepare("SELECT i.id,i.to_module,f.path,f.language FROM ci_imports i JOIN ci_files f ON f.id=i.from_file_id WHERE i.to_file_id IS NULL")?;
    let pending = query
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                ImportRequest {
                    module: r.get(1)?,
                    source_path: r.get(2)?,
                    language: r.get(3)?,
                },
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if pending.is_empty() {
        return Ok(());
    }
    let mut query = conn.prepare("SELECT id,path FROM ci_files")?;
    let files = query
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let by_path: HashMap<_, _> = files
        .iter()
        .map(|(id, path)| (path.as_str(), *id))
        .collect();
    let catalog =
        ImportCatalog::from_project(root, files.iter().map(|(_, p)| p.clone()).collect())?;
    let mut targets = Vec::new();
    let mut resolutions = Vec::new();
    for (id, request) in pending {
        let resolved = catalog.resolve(&request)?;
        if let Some(target) = resolved.target {
            targets.push((
                *by_path.get(target.as_str()).ok_or_else(|| {
                    IndexError::Invalid("resolved import target is not indexed".into())
                })?,
                id,
            ));
        }
        let value = match resolved.resolution {
            Resolution::Internal => "internal",
            Resolution::Unresolved => "unresolved",
            Resolution::External => "external",
        };
        resolutions.push((value, id));
    }
    conn.execute_batch("SAVEPOINT index_import_resolution")?;
    let write = || -> Result<()> {
        let mut update = conn.prepare("UPDATE ci_imports SET to_file_id=?1 WHERE id=?2")?;
        for (target, id) in targets {
            update.execute(params![target, id])?;
        }
        let mut update = conn.prepare("UPDATE ci_imports SET resolution=?1 WHERE id=?2")?;
        for (resolution, id) in resolutions {
            update.execute(params![resolution, id])?;
        }
        Ok(())
    };
    match write() {
        Ok(()) => {
            conn.execute_batch("RELEASE SAVEPOINT index_import_resolution")?;
            Ok(())
        }
        Err(e) => {
            conn.execute_batch("ROLLBACK TO SAVEPOINT index_import_resolution;RELEASE SAVEPOINT index_import_resolution")?;
            Err(e)
        }
    }
}
