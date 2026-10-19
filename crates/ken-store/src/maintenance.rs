use crate::{
    ProjectDatabase, ProjectStore, StoreError, StoreResult, VectorSpace, VectorStore,
    WriteTransaction, allocate, database::set_meta, error::sql_error, high_water, recovery,
};
use serde::Serialize;
use std::{collections::BTreeMap, path::Path};

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum MaintenanceEvent {
    Migrated {
        space: VectorSpace,
        count: u64,
    },
    Compacted {
        space: VectorSpace,
        before: i64,
        after: i64,
    },
    StagingReady,
    JournalPublished,
    BackupRenamed,
    NewPublished,
    DatabaseCommitted,
    Cleaned,
}
#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
pub struct CompactionCount {
    pub before: i64,
    pub after: i64,
}

pub fn migrate_inline(
    project: &mut ProjectStore,
    dim: usize,
    model: Option<&str>,
    batch: usize,
    mut progress: impl FnMut(MaintenanceEvent),
) -> StoreResult<BTreeMap<VectorSpace, u64>> {
    let batch = i64::try_from(batch)
        .ok()
        .filter(|n| *n > 0)
        .ok_or(StoreError::InvalidSlot(
            "batch must be positive and fit SQLite",
        ))?;
    let bytes = dim
        .checked_mul(4)
        .and_then(|n| i64::try_from(n).ok())
        .ok_or(StoreError::Dimension("inline byte length exceeds SQLite"))?;
    let mut moved = BTreeMap::new();
    for space in VectorSpace::ALL {
        let store = project.vectors(space, dim, model)?;
        let mut count = 0u64;
        loop {
            let mut tx = project.database_mut().immediate()?;
            let rows: Vec<(i64, Vec<u8>)> = {
                let conn = tx.connection();
                let mut stmt=conn.prepare(&format!("SELECT id,embedding FROM {space} WHERE embedding IS NOT NULL AND vec_slot IS NULL AND length(embedding)=?1 ORDER BY id LIMIT ?2")).map_err(|e|sql_error(conn,e))?;
                stmt.query_map([bytes, batch], |row| Ok((row.get(0)?, row.get(1)?)))
                    .map_err(|e| sql_error(conn, e))?
                    .collect::<Result<_, _>>()
                    .map_err(|e| sql_error(conn, e))?
            };
            if rows.is_empty() {
                break;
            }
            let vectors: Vec<Vec<f32>> = rows
                .iter()
                .map(|(_, raw)| {
                    raw.chunks_exact(4)
                        .map(|v| f32::from_le_bytes([v[0], v[1], v[2], v[3]]))
                        .collect()
                })
                .collect();
            let slots = allocate(&mut tx, space, rows.len())?;
            store.write(&slots, &vectors, false)?;
            let conn = tx.connection();
            for ((id, _), slot) in rows.iter().zip(slots) {
                conn.execute(
                    &format!("UPDATE {space} SET vec_slot=?1,embedding=NULL WHERE id=?2"),
                    rusqlite::params![slot, id],
                )
                .map_err(|e| sql_error(conn, e))?;
            }
            tx.commit()?;
            count = count
                .checked_add(rows.len() as u64)
                .ok_or(StoreError::InvalidSlot("migration count overflows"))?;
            progress(MaintenanceEvent::Migrated { space, count });
        }
        store.flush()?;
        moved.insert(space, count);
    }
    Ok(moved)
}

pub fn reclaim_database(db: &mut ProjectDatabase) -> StoreResult<(u64, u64)> {
    if db.connection().path().is_none_or(str::is_empty) {
        return Ok((0, 0));
    }
    let before = std::fs::metadata(db.path())
        .map_err(|e| StoreError::io(db.path(), e))?
        .len();
    let conn = db.connection();
    conn.execute_batch("VACUUM")
        .map_err(|e| sql_error(conn, e))?;
    let busy: i64 = conn
        .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |row| row.get(0))
        .map_err(|e| sql_error(conn, e))?;
    if busy != 0 {
        return Err(StoreError::Recovery {
            path: db.path().into(),
            reason: "database checkpoint is busy; migration remains committed".into(),
        });
    }
    let after = std::fs::metadata(db.path())
        .map_err(|e| StoreError::io(db.path(), e))?
        .len();
    Ok((before, after))
}

pub fn compact(
    project: &mut ProjectStore,
    dim: usize,
    mut progress: impl FnMut(MaintenanceEvent),
) -> StoreResult<BTreeMap<VectorSpace, CompactionCount>> {
    let live = project.vector_directory();
    recovery::recover(project.database_mut(), &live)?;
    let result = compact_operation(project, &live, dim, &mut progress);
    if result.is_err() {
        recovery::recover(project.database_mut(), &live)?;
    }
    result
}
fn compact_operation(
    project: &mut ProjectStore,
    live: &Path,
    dim: usize,
    progress: &mut impl FnMut(MaintenanceEvent),
) -> StoreResult<BTreeMap<VectorSpace, CompactionCount>> {
    let parent = live
        .parent()
        .ok_or(StoreError::InvalidSlot("vector directory has no parent"))?;
    let staging = tempfile::Builder::new()
        .prefix(".vectors-stage-")
        .tempdir_in(parent)
        .map_err(|e| StoreError::io(parent, e))?;
    let tx = project.database_mut().immediate()?;
    copy_unmanaged(live, staging.path())?;
    let mut counts = BTreeMap::new();
    for space in VectorSpace::ALL {
        let src = VectorStore::open(live, space, dim, None)?;
        let manifest = live.join(format!("{space}.json"));
        std::fs::copy(&manifest, staging.path().join(format!("{space}.json")))
            .map_err(|e| StoreError::io(&manifest, e))?;
        let dst = VectorStore::open(staging.path(), space, dim, None)?;
        let before = high_water(tx.connection(), space)?;
        let rows: Vec<(i64, i64)> = {
            let conn = tx.connection();
            let mut stmt = conn
                .prepare(&format!(
                    "SELECT id,vec_slot FROM {space} WHERE vec_slot IS NOT NULL ORDER BY vec_slot"
                ))
                .map_err(|e| sql_error(conn, e))?;
            stmt.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
                .map_err(|e| sql_error(conn, e))?
                .collect::<Result<_, _>>()
                .map_err(|e| sql_error(conn, e))?
        };
        for (index, chunk) in rows.chunks(4096).enumerate() {
            let old: Vec<_> = chunk.iter().map(|p| p.1).collect();
            let new: Vec<_> = (index * 4096..index * 4096 + chunk.len())
                .map(|n| n as i64)
                .collect();
            dst.write(&new, &src.read(&old)?, false)?;
        }
        dst.flush()?;
        remap(&tx, space, &rows)?;
        let after = i64::try_from(rows.len())
            .map_err(|_| StoreError::InvalidSlot("compaction count exceeds SQLite"))?;
        counts.insert(space, CompactionCount { before, after });
        progress(MaintenanceEvent::Compacted {
            space,
            before,
            after,
        });
    }
    progress(MaintenanceEvent::StagingReady);
    let mut publication = recovery::Publication::prepare(live, staging, dim)?;
    publication.publish(progress)?;
    set_meta(tx.connection(), recovery::MARKER, publication.id())
        .map_err(|e| sql_error(tx.connection(), e))?;
    tx.commit()?;
    progress(MaintenanceEvent::DatabaseCommitted);
    recovery::recover(project.database_mut(), live)?;
    progress(MaintenanceEvent::Cleaned);
    Ok(counts)
}
fn remap(tx: &WriteTransaction<'_>, space: VectorSpace, rows: &[(i64, i64)]) -> StoreResult<()> {
    let conn = tx.connection();
    // Null first: row identity remains stable and unique slot indexes never collide.
    conn.execute(
        &format!("UPDATE {space} SET vec_slot=NULL WHERE vec_slot IS NOT NULL"),
        [],
    )
    .map_err(|e| sql_error(conn, e))?;
    for (slot, (id, _)) in rows.iter().enumerate() {
        conn.execute(
            &format!("UPDATE {space} SET vec_slot=?1 WHERE id=?2"),
            rusqlite::params![slot as i64, id],
        )
        .map_err(|e| sql_error(conn, e))?;
    }
    conn.execute("DELETE FROM ci_vec_free WHERE space=?1", [space.as_str()])
        .map_err(|e| sql_error(conn, e))?;
    conn.execute("INSERT INTO ci_vec_alloc(space,next_slot) VALUES(?1,?2) ON CONFLICT(space) DO UPDATE SET next_slot=excluded.next_slot",rusqlite::params![space.as_str(),rows.len() as i64]).map_err(|e|sql_error(conn,e))?;
    Ok(())
}

fn copy_unmanaged(source: &Path, dest: &Path) -> StoreResult<()> {
    let entries = match std::fs::read_dir(source) {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(StoreError::io(source, e)),
    };
    for entry in entries {
        let entry = entry.map_err(|e| StoreError::io(source, e))?;
        let name = entry.file_name();
        let text = name.to_string_lossy();
        let managed = VectorSpace::ALL.into_iter().any(|space| {
            text == format!("{space}.json")
                || text
                    .strip_prefix(&format!("{space}."))
                    .and_then(|s| s.strip_suffix(".vec"))
                    .and_then(|s| s.parse::<u64>().ok())
                    .is_some_and(|index| text == format!("{space}.{index:04}.vec"))
        });
        if managed {
            continue;
        }
        copy_entry(&entry.path(), &dest.join(name))?;
    }
    Ok(())
}
fn copy_entry(source: &Path, dest: &Path) -> StoreResult<()> {
    let kind = std::fs::symlink_metadata(source).map_err(|e| StoreError::io(source, e))?;
    if kind.is_symlink() {
        let target = std::fs::read_link(source).map_err(|e| StoreError::io(source, e))?;
        std::os::unix::fs::symlink(target, dest).map_err(|e| StoreError::io(dest, e))?;
    } else if kind.is_dir() {
        std::fs::create_dir(dest).map_err(|e| StoreError::io(dest, e))?;
        for entry in std::fs::read_dir(source).map_err(|e| StoreError::io(source, e))? {
            let entry = entry.map_err(|e| StoreError::io(source, e))?;
            copy_entry(&entry.path(), &dest.join(entry.file_name()))?;
        }
        std::fs::set_permissions(dest, kind.permissions()).map_err(|e| StoreError::io(dest, e))?;
    } else if kind.is_file() {
        std::fs::copy(source, dest).map_err(|e| StoreError::io(source, e))?;
    } else {
        return Err(StoreError::Recovery {
            path: source.into(),
            reason: "unmanaged special file cannot be copied safely".into(),
        });
    }
    Ok(())
}
