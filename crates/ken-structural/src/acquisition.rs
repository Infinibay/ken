//! Acquire one immutable, executable project index independently of result caches.
use crate::{BuildError, ProjectBuilder, Result, ScanLimits};
use ken_program::{query_view::normalize_query_graph, value::GraphValue};
use ken_store::{
    artifact_cache::ArtifactCache,
    structural::{
        StructuralError, StructuralStore,
        graph::{GraphIndex, publish_graph_owned},
    },
};
use rusqlite::OptionalExtension;
use serde_json::{Value, json};
use std::{
    cell::RefCell,
    fs::{File, OpenOptions},
    os::fd::AsRawFd,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

/// Owns the pinned store. Call `index` to borrow a reader for this revision.
pub struct AcquiredProject {
    store: StructuralStore,
    pub graph: i64,
    pub analysis: Value,
}
impl AcquiredProject {
    pub fn index(&mut self) -> Result<GraphIndex<'_>> {
        Ok(GraphIndex::open(&mut self.store, self.graph)?)
    }
    pub fn retained_index(&self) -> Result<GraphIndex<'_>> {
        Ok(GraphIndex::open_retained(&self.store, self.graph)?)
    }
    /// Reconstruct the legacy source view from these captured units, never from
    /// a second worktree read. The normalized query graph has different facts.
    pub fn source_graph(
        &self,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<ken_program::StructuralIr> {
        let snapshot = self.store.connection().query_row(
            "SELECT snapshot_id FROM k2_graphs WHERE graph_id=?",
            [self.graph],
            |row| row.get(0),
        )?;
        self.store.check_pinned_snapshot(snapshot)?;
        let mut ids = Vec::new();
        self.store.snapshot_units_checked(snapshot, |id| {
            ids.push(id);
            Ok(())
        })?;
        let mut units = Vec::with_capacity(ids.len());
        for id in ids {
            check()?;
            units.push(self.store.load_unit(id)?);
        }
        let mut failure = None;
        let graph = ken_program::project::link_project_owned_with_check(units, || match check() {
            Ok(()) => Ok(()),
            Err(error) => {
                failure = Some(error);
                Err(ken_program::ProgramError::Invalid(
                    "source graph reconstruction interrupted",
                ))
            }
        });
        if let Some(error) = failure {
            return Err(error);
        }
        let graph = graph?;
        self.store.check_pinned_snapshot(snapshot)?;
        Ok(graph)
    }
    pub fn source_store(&self) -> &StructuralStore {
        &self.store
    }
    pub fn source_store_mut(&mut self) -> &mut StructuralStore {
        &mut self.store
    }
    pub fn close(self) -> Result<()> {
        Ok(self.store.close()?)
    }
    pub fn persistent(&self) -> bool {
        self.store.path().is_some()
    }
    pub fn allocated_bytes(&self) -> Result<u64> {
        Ok(self.store.allocated_bytes()?)
    }
}
pub struct ProjectAcquisition<'a, 'b> {
    builder: &'a mut ProjectBuilder<'b>,
    database: PathBuf,
    persistent: bool,
}
impl<'a, 'b> ProjectAcquisition<'a, 'b> {
    pub fn new(builder: &'a mut ProjectBuilder<'b>, database: &Path, persistent: bool) -> Self {
        Self {
            builder,
            database: database.into(),
            persistent,
        }
    }
    pub fn acquire(
        &mut self,
        path: &Path,
        limits: ScanLimits,
        check: impl FnMut() -> Result<()>,
    ) -> Result<AcquiredProject> {
        self.acquire_sources(path, None, limits, check)
    }
    pub fn acquire_sources(
        &mut self,
        path: &Path,
        source_paths: Option<&[String]>,
        limits: ScanLimits,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<AcquiredProject> {
        let start = Instant::now();
        let manifest = self
            .builder
            .manifest_sources(path, source_paths, limits, &mut check)?;
        let count = manifest.entries().len();
        use sha2::{Digest, Sha256};
        let source_manifest = manifest
            .entries()
            .iter()
            .map(|source| {
                json!([
                    source.path(),
                    format!("{:x}", Sha256::digest(source.content()))
                ])
            })
            .collect::<Vec<_>>();
        let skipped = serde_json::to_value(manifest.skipped())?;
        let key = ArtifactCache::key([
            b"native-query-index/4".as_slice(),
            manifest.graph_key().as_bytes(),
            crate::IMPLEMENTATION_FINGERPRINT.as_bytes(),
        ]);
        let _lock = AcquisitionLock::acquire(&self.database, self.persistent, &mut check)?;
        check()?;
        let mut store =
            StructuralStore::open(self.persistent.then_some(self.database.as_path()), None)?;
        let found:Option<(i64,i64)>=store.connection().query_row("SELECT graph_id,snapshot_id FROM k2_graphs JOIN k2_graph_publications USING(graph_id) WHERE fingerprint=?1 AND ready=1",[&key],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
        let (graph, mut analysis) = if let Some((graph, snapshot)) = found {
            store.pin_snapshot(snapshot)?;
            let index = GraphIndex::open(&mut store, graph)?;
            let GraphValue::Dict(metadata) = &index.metadata else {
                return Err(BuildError::Invalid("invalid stored graph metadata"));
            };
            let mut analysis: Value = serde_json::from_str(
                metadata
                    .iter()
                    .find(|(k, _)| k.to_utf8().as_deref() == Some("analysis"))
                    .ok_or(BuildError::Invalid("missing graph analysis"))?
                    .1
                    .to_raw()?
                    .get(),
            )?;
            analysis["skipped"] = skipped;
            analysis["coverage_complete"] = json!(
                analysis["skipped"].as_array().is_some_and(Vec::is_empty)
                    && metadata
                        .iter()
                        .find(|(k, _)| k.to_utf8().as_deref() == Some("diagnostics"))
                        .is_some_and(|(_, v)| matches!(v,GraphValue::List(v)if v.is_empty()))
            );
            analysis["cache"] =
                json!({"hits":1,"misses":0,"evictions":0,"enabled":self.persistent,"error":null});
            drop(index);
            (graph, analysis)
        } else {
            // Keep a building lease renewed by linker checks while immutable raw
            // units are projected. This protects them from concurrent collection.
            drop(store);
            let building = RefCell::new(StructuralStore::open(
                self.persistent.then_some(self.database.as_path()),
                None,
            )?);
            let mut source_units = vec![];
            let frontend = self.builder.frontend_revision().to_owned();
            let report = self.builder.build_manifest_with_units(
                manifest,
                || {
                    check()?;
                    building.borrow().renew(false)?;
                    Ok(())
                },
                |source, ir| {
                    let source_hash = format!("{:x}", Sha256::digest(source.content()));
                    let id = building.borrow_mut().put_unit(
                        source.key(),
                        ir,
                        &source_hash,
                        &frontend,
                        true,
                    )?;
                    source_units.push((id, source.key().to_owned(), source_hash));
                    Ok(())
                },
            )?;
            check()?;
            let complete = report.analysis.coverage_complete;
            let failed = report.analysis.files.len() != count;
            let graph = normalize_query_graph(&report.graph)?;
            drop(report.graph);
            let analysis = serde_json::to_value(&report.analysis)?;
            let raw = serde_json::value::to_raw_value(&analysis)?;
            let encoded = GraphValue::parse(&raw)?;
            store = building.into_inner();
            if failed && self.persistent {
                // Partial frontend failures never publish a reusable graph. Raw
                // cached units may survive, but the returned reader is ephemeral.
                let mut ephemeral = StructuralStore::open(None, None)?;
                for (id, key, source_hash) in &mut source_units {
                    *id = ephemeral.put_unit(
                        key,
                        &store.load_unit(*id)?,
                        source_hash,
                        &frontend,
                        true,
                    )?;
                }
                store = ephemeral;
            }
            let units = source_units
                .iter()
                .map(|(id, _, _)| *id)
                .collect::<Vec<_>>();
            let snapshot = store.publish(&units, store.current()?, &key, complete)?;
            let mut cancelled = None;
            let result = publish_graph_owned(
                &mut store,
                snapshot,
                &key,
                graph,
                &encoded,
                &mut || match check() {
                    Ok(()) => Ok(()),
                    Err(e) => {
                        cancelled = Some(e);
                        Err(StructuralError::Invalid("project acquisition cancelled"))
                    }
                },
            );
            if let Some(error) = cancelled {
                return Err(error);
            }
            let id = result?;
            (id, analysis)
        };
        check()?;
        store.pin_snapshot(store.connection().query_row(
            "SELECT snapshot_id FROM k2_graphs WHERE graph_id=?1",
            [graph],
            |r| r.get(0),
        )?)?;
        let reclaimed = store.collect(1, &[])?;
        analysis["graph_key"] = if analysis["files"]
            .as_array()
            .is_some_and(|v| v.len() == count)
        {
            json!(key)
        } else {
            json!("")
        };
        analysis["manifest"] = json!(source_manifest);
        analysis["query_index"] = json!({"backend":"sqlite_columns","hit":found.is_some(),"persistent":store.path().is_some(),"bytes":store.allocated_bytes()?,"reclaimed_snapshots":reclaimed.snapshots});
        analysis["elapsed_ms"] =
            json!((start.elapsed().as_secs_f64() * 1_000_000.).round() / 1000.);
        check()?;
        Ok(AcquiredProject {
            store,
            graph,
            analysis,
        })
    }
}
/// The acquisition lock is released before callers start executing queries.
struct AcquisitionLock(Option<File>);
impl AcquisitionLock {
    fn acquire(
        database: &Path,
        enabled: bool,
        check: &mut impl FnMut() -> Result<()>,
    ) -> Result<Self> {
        if !enabled {
            return Ok(Self(None));
        }
        let path = database.with_extension("acquire.lock");
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new().create(true).append(true).open(path)?;
        loop {
            check()?;
            // SAFETY: file owns a valid descriptor for the entire lock lifetime.
            let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
            if result == 0 {
                return Ok(Self(Some(file)));
            }
            let error = std::io::Error::last_os_error();
            if error.kind() != std::io::ErrorKind::WouldBlock
                && error.kind() != std::io::ErrorKind::Interrupted
            {
                return Err(error.into());
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}
impl Drop for AcquisitionLock {
    fn drop(&mut self) {
        if let Some(file) = self.0.take() {
            // SAFETY: owned descriptor remains live during unlock.
            unsafe {
                libc::flock(file.as_raw_fd(), libc::LOCK_UN);
            }
        }
    }
}
