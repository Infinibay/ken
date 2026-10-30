//! One journal binds directory generations to SQLite's transactional commit marker.
use crate::{
    MaintenanceEvent, ProjectDatabase, StoreError, StoreResult, VectorSpace, VectorStore,
    error::sql_error, segments::publish_new, verify,
};
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File},
    io::Write,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

pub(crate) const MARKER: &str = "__ken_vector_compaction";
const OWNER: &str = ".ken-storage-owner.json";
const JOURNAL: &str = "vectors-maintenance.json";

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Identity {
    device: u64,
    inode: u64,
}
fn identity(path: &Path) -> StoreResult<Option<Identity>> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(StoreError::io(path, e)),
    };
    if !metadata.is_dir() || metadata.is_symlink() {
        return Err(invalid(path, "generation must be a real directory"));
    }
    Ok(Some(Identity {
        device: metadata.dev(),
        inode: metadata.ino(),
    }))
}
fn invalid(path: &Path, reason: impl Into<String>) -> StoreError {
    StoreError::Recovery {
        path: path.into(),
        reason: reason.into(),
    }
}
fn valid_id(id: &str) -> bool {
    (6..=64).contains(&id.len()) && id.bytes().all(|c| c.is_ascii_alphanumeric())
}
fn read_marker(conn: &rusqlite::Connection, path: &Path) -> StoreResult<Option<String>> {
    let row: Option<Option<String>> = conn
        .query_row("SELECT value FROM meta WHERE key=?1", [MARKER], |row| {
            row.get(0)
        })
        .optional()
        .map_err(|e| sql_error(conn, e))?;
    match row {
        None => Ok(None),
        Some(Some(id)) if valid_id(&id) => Ok(Some(id)),
        _ => Err(invalid(path, "commit marker is NULL, empty or malformed")),
    }
}
fn sync_parent(path: &Path) -> StoreResult<()> {
    File::open(path)
        .and_then(|f| f.sync_all())
        .map_err(|e| StoreError::io(path, e))
}

#[derive(Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Layout {
    #[default]
    Dense,
    Preserved,
}
impl Layout {
    fn dense(&self) -> bool {
        *self == Self::Dense
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Journal {
    format: u32,
    phase: String,
    id: String,
    staging: String,
    backup: String,
    old: Option<Identity>,
    new: Identity,
    dim: usize,
    #[serde(default, skip_serializing_if = "Layout::dense")]
    layout: Layout,
}
impl Journal {
    fn validate(&self, path: &Path) -> StoreResult<()> {
        if self.format != 1
            || !matches!(self.phase.as_str(), "prepared" | "discarding_new")
            || !valid_id(&self.id)
            || self.staging != format!(".vectors-stage-{}", self.id)
            || self.backup != format!(".vectors-backup-{}", self.id)
            || self.dim == 0
        {
            return Err(invalid(
                path,
                "invalid version, phase, operation identity or confined generation names",
            ));
        }
        Ok(())
    }

    fn discard_new(&mut self, path: &Path) -> StoreResult<()> {
        if self.phase == "discarding_new" {
            return Ok(());
        }
        // Persist cleanup authority outside the directory before deleting its
        // internal owner receipt. The recorded inode must still match on retry.
        self.phase = "discarding_new".into();
        let raw = serde_json::to_vec_pretty(self).map_err(|e| invalid(path, e.to_string()))?;
        let parent = path
            .parent()
            .ok_or_else(|| invalid(path, "no journal parent"))?;
        let mut replacement =
            tempfile::NamedTempFile::new_in(parent).map_err(|e| StoreError::io(parent, e))?;
        replacement
            .write_all(&raw)
            .map_err(|e| StoreError::io(path, e))?;
        replacement
            .as_file()
            .sync_all()
            .map_err(|e| StoreError::io(path, e))?;
        replacement
            .persist(path)
            .map_err(|e| StoreError::io(path, e.error))?;
        sync_parent(parent)
    }
}
fn owner(path: &Path, id: &str) -> StoreResult<()> {
    let path = path.join(OWNER);
    let raw = fs::read(&path).map_err(|e| StoreError::io(&path, e))?;
    let actual: String = serde_json::from_slice(&raw).map_err(|e| invalid(&path, e.to_string()))?;
    if actual != id {
        return Err(invalid(&path, "generation belongs to another operation"));
    }
    Ok(())
}
fn remove_owned(path: &Path, expected: Identity, id: Option<&str>) -> StoreResult<()> {
    if identity(path)? != Some(expected) {
        return Err(invalid(path, "generation identity changed before cleanup"));
    }
    if let Some(id) = id {
        owner(path, id)?;
    }
    match fs::remove_dir_all(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
            // Unmanaged directories retain their original permissions in both
            // generations. Only this validated, discarded tree may be made
            // writable; never change the published tree or follow its symlinks.
            if identity(path)? != Some(expected) {
                return Err(invalid(path, "generation identity changed before cleanup"));
            }
            writable_directories(path)?;
            fs::remove_dir_all(path).map_err(|e| StoreError::io(path, e))
        }
        Err(e) => Err(StoreError::io(path, e)),
    }
}

fn writable_directories(path: &Path) -> StoreResult<()> {
    let directory = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW)
        .open(path)
        .map_err(|e| StoreError::io(path, e))?;
    let permissions = directory
        .metadata()
        .map_err(|e| StoreError::io(path, e))?
        .permissions();
    directory
        .set_permissions(fs::Permissions::from_mode(permissions.mode() | 0o700))
        .map_err(|e| StoreError::io(path, e))?;
    for entry in fs::read_dir(path).map_err(|e| StoreError::io(path, e))? {
        let entry = entry.map_err(|e| StoreError::io(path, e))?;
        if entry
            .file_type()
            .map_err(|e| StoreError::io(&entry.path(), e))?
            .is_dir()
        {
            writable_directories(&entry.path())?;
        }
    }
    Ok(())
}

pub(crate) struct Publication {
    live: PathBuf,
    parent: PathBuf,
    journal: Journal,
    staging: Option<tempfile::TempDir>,
}
impl Publication {
    pub fn prepare(live: &Path, staging: tempfile::TempDir, dim: usize) -> StoreResult<Self> {
        Self::prepare_layout(live, staging, dim, Layout::Dense)
    }
    pub fn prepare_rebuild(
        live: &Path,
        staging: tempfile::TempDir,
        dim: usize,
    ) -> StoreResult<Self> {
        Self::prepare_layout(live, staging, dim, Layout::Preserved)
    }
    fn prepare_layout(
        live: &Path,
        staging: tempfile::TempDir,
        dim: usize,
        layout: Layout,
    ) -> StoreResult<Self> {
        let parent = live
            .parent()
            .ok_or_else(|| invalid(live, "no generation parent"))?
            .to_path_buf();
        let name = staging
            .path()
            .file_name()
            .and_then(|s| s.to_str())
            .ok_or_else(|| invalid(staging.path(), "invalid staging name"))?;
        let id = name
            .strip_prefix(".vectors-stage-")
            .ok_or_else(|| invalid(staging.path(), "invalid staging prefix"))?
            .to_owned();
        let journal = Journal {
            format: 1,
            phase: "prepared".into(),
            id: id.clone(),
            staging: name.to_owned(),
            backup: format!(".vectors-backup-{id}"),
            old: identity(live)?,
            new: identity(staging.path())?
                .ok_or_else(|| invalid(staging.path(), "missing staging directory"))?,
            dim,
            layout,
        };
        journal.validate(&parent.join(JOURNAL))?;
        if identity(&parent.join(&journal.backup))?.is_some() {
            return Err(invalid(&parent, "backup name already exists"));
        }
        let raw = serde_json::to_vec(&id).map_err(|e| invalid(staging.path(), e.to_string()))?;
        if !publish_new(&staging.path().join(OWNER), |f| f.write_all(&raw))? {
            return Err(invalid(
                staging.path(),
                "staging ownership marker already exists",
            ));
        }
        // A private preparation directory must not make the published store
        // unreadable to collaborators who could read the original directory.
        if journal.old.is_some() {
            let permissions = fs::metadata(live)
                .map_err(|e| StoreError::io(live, e))?
                .permissions();
            fs::set_permissions(staging.path(), permissions)
                .map_err(|e| StoreError::io(staging.path(), e))?;
        }
        sync_parent(staging.path())?;
        Ok(Self {
            live: live.into(),
            parent,
            journal,
            staging: Some(staging),
        })
    }
    pub fn id(&self) -> &str {
        &self.journal.id
    }
    pub fn publish(&mut self, progress: &mut impl FnMut(MaintenanceEvent)) -> StoreResult<()> {
        let path = self.parent.join(JOURNAL);
        let raw =
            serde_json::to_vec_pretty(&self.journal).map_err(|e| invalid(&path, e.to_string()))?;
        if !publish_new(&path, |file| file.write_all(&raw))? {
            return Err(invalid(&path, "another publication journal exists"));
        }
        // From this point only journal recovery owns cleanup, including on errors.
        if let Some(staging) = self.staging.take() {
            let _ = staging.keep();
        }
        progress(MaintenanceEvent::JournalPublished);
        if self.journal.old.is_some() {
            fs::rename(&self.live, self.parent.join(&self.journal.backup))
                .map_err(|e| StoreError::io(&self.live, e))?;
            sync_parent(&self.parent)?;
        }
        progress(MaintenanceEvent::BackupRenamed);
        fs::rename(self.parent.join(&self.journal.staging), &self.live)
            .map_err(|e| StoreError::io(&self.live, e))?;
        sync_parent(&self.parent)?;
        progress(MaintenanceEvent::NewPublished);
        Ok(())
    }
}

pub(crate) fn recover(db: &mut ProjectDatabase, live: &Path) -> StoreResult<()> {
    let parent = live
        .parent()
        .ok_or_else(|| invalid(live, "no vector parent"))?;
    let path = parent.join(JOURNAL);
    let tx = db.immediate()?;
    let conn = tx.connection();
    let raw = match fs::read(&path) {
        Ok(raw) => raw,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            let has_meta: bool = conn
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM sqlite_schema WHERE type='table' AND name='meta')",
                    [],
                    |row| row.get(0),
                )
                .map_err(|e| sql_error(conn, e))?;
            if has_meta && let Some(marker) = read_marker(conn, &path)? {
                if !valid_id(&marker) {
                    return Err(invalid(&path, "invalid orphan commit marker"));
                }
                if live
                    .join(OWNER)
                    .try_exists()
                    .map_err(|e| StoreError::io(live, e))?
                {
                    owner(live, &marker)?;
                    fs::remove_file(live.join(OWNER)).map_err(|e| StoreError::io(live, e))?;
                }
                conn.execute("DELETE FROM meta WHERE key=?1", [MARKER])
                    .map_err(|e| sql_error(conn, e))?;
            }
            return tx.commit();
        }
        Err(e) => return Err(StoreError::io(&path, e)),
    };
    let mut journal: Journal =
        serde_json::from_slice(&raw).map_err(|e| invalid(&path, e.to_string()))?;
    journal.validate(&path)?;
    let staging = parent.join(&journal.staging);
    let backup = parent.join(&journal.backup);
    let marker = read_marker(conn, &path)?;
    if marker.as_ref().is_some_and(|s| s != &journal.id) {
        return Err(invalid(&path, "SQLite marker belongs to another operation"));
    }
    if marker.is_some() && journal.phase == "discarding_new" {
        return Err(invalid(&path, "committed generation cannot be discarded"));
    }
    let live_id = identity(live)?;
    let stage_id = identity(&staging)?;
    let backup_id = identity(&backup)?;
    // Validate every generation before mutating anything named by the journal.
    if let Some(actual) = live_id {
        if actual == journal.new {
            if journal.phase == "prepared" {
                owner(live, &journal.id)?;
            }
        } else if Some(actual) != journal.old {
            return Err(invalid(
                live,
                "live generation identity does not match journal",
            ));
        }
    }
    if let Some(actual) = stage_id {
        if actual != journal.new {
            return Err(invalid(
                &staging,
                "staging generation identity does not match journal",
            ));
        }
        if journal.phase == "prepared" {
            owner(&staging, &journal.id)?;
        }
    }
    if let Some(actual) = backup_id
        && Some(actual) != journal.old
    {
        return Err(invalid(
            &backup,
            "backup generation identity does not match journal",
        ));
    }
    if marker.is_some() {
        if live_id != Some(journal.new) {
            return Err(invalid(live, "committed vector generation is missing"));
        }
        committed_payload(conn, live, journal.dim, journal.layout)?;
        if let Some(old) = backup_id {
            remove_owned(&backup, old, None)?;
        }
        if stage_id.is_some() {
            remove_owned(&staging, journal.new, Some(&journal.id))?;
        }
    } else {
        if let Some(old) = journal.old {
            if backup_id == Some(old) {
                if live_id.is_some() {
                    journal.discard_new(&path)?;
                    remove_owned(live, journal.new, None)?;
                }
                fs::rename(&backup, live).map_err(|e| StoreError::io(live, e))?;
            } else if live_id != Some(old) {
                return Err(invalid(live, "uncommitted original generation is missing"));
            }
        } else if live_id.is_some() {
            journal.discard_new(&path)?;
            remove_owned(live, journal.new, None)?;
        }
        if stage_id.is_some() {
            journal.discard_new(&path)?;
            remove_owned(&staging, journal.new, None)?;
        }
    }
    fs::remove_file(&path).map_err(|e| StoreError::io(&path, e))?;
    sync_parent(parent)?;
    if marker.is_some() {
        fs::remove_file(live.join(OWNER)).map_err(|e| StoreError::io(live, e))?;
        conn.execute("DELETE FROM meta WHERE key=?1", [MARKER])
            .map_err(|e| sql_error(conn, e))?;
    }
    tx.commit()
}

fn committed_payload(
    conn: &rusqlite::Connection,
    live: &Path,
    dim: usize,
    layout: Layout,
) -> StoreResult<()> {
    for space in VectorSpace::ALL {
        let manifest = live.join(format!("{space}.json"));
        if !manifest.is_file() {
            return Err(invalid(&manifest, "committed manifest is missing"));
        }
        let store = VectorStore::open(live, space, dim, None)?;
        let report = verify(conn, &store)?;
        if layout == Layout::Preserved {
            if report.out_of_range != 0 || report.double_booked != 0 {
                return Err(invalid(live, "committed rebuilt mapping is inconsistent"));
            }
            store.validate_referenced_segments(conn)?;
            continue;
        }
        let expected = (report.high_water as u64).div_ceil(store.manifest().segment_rows as u64);
        if report.segments as u64 != expected
            || report.referenced as u64 != report.high_water as u64
            || report.free != 0
            || report.leaked != 0
            || report.out_of_range != 0
            || report.double_booked != 0
        {
            return Err(invalid(live, "committed compacted mapping is incomplete"));
        }
    }
    Ok(())
}
