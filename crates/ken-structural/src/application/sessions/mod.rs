//! Explicit source revision ownership, compilation reuse and lossless delivery.
mod compilation;
mod execution;
mod reporting;
use super::modules::{ModuleError, ModuleResolver, ResolvedQuery};
use crate::{
    AcquiredProject, BuildError, NativeFrontend, ProjectAcquisition, ProjectBuilder, ScanLimits,
};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_query::{
    CompiledQuery, ParseError,
    execution::{Cancellation, ExecutionError},
};
use ken_store::{artifact_cache::ArtifactCache, structural::StructuralError};
use ken_syntax::GrammarCatalog;
pub use reporting::{QueryResponse, query_response};
use serde::{Deserialize, Serialize};
use serde_json::{Value as Json, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{Arc, Mutex, RwLock},
    thread::{self, ThreadId},
    time::{Duration, Instant},
};
#[derive(Debug, thiserror::Error)]
pub enum SessionError {
    #[error("{0}")]
    SourcesChanged(String),
    #[error("query sessions belong to their creating process and thread")]
    Owner,
    #[error("query session is closed")]
    Closed,
    #[error("invalid execution budget")]
    InvalidBudget,
    #[error("local hazard preparation cannot answer a full-source query")]
    InvalidProfile,
    #[error("prepared query sessions require retained source storage; increase cache_mb")]
    PersistentStorageRequired,
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Build(#[from] BuildError),
    #[error(transparent)]
    Module(#[from] ModuleError),
    #[error(transparent)]
    Parse(#[from] ParseError),
    #[error(transparent)]
    Execution(#[from] ExecutionError),
    #[error(transparent)]
    Store(#[from] StructuralError),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
    #[error(transparent)]
    Cache(#[from] ken_store::artifact_cache::InvalidCacheBudget),
}
pub type Result<T> = std::result::Result<T, SessionError>;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceProfile {
    #[default]
    Full,
    LocalHazards,
}
#[derive(Clone, Debug)]
pub struct SessionOptions {
    pub path: PathBuf,
    pub cache_mb: f64,
    pub max_file_bytes: u64,
    pub source_paths: Option<Vec<String>>,
    pub source_profile: SourceProfile,
}
impl Default for SessionOptions {
    fn default() -> Self {
        Self {
            path: ".".into(),
            cache_mb: 500.,
            max_file_bytes: 2_000_000,
            source_paths: None,
            source_profile: SourceProfile::Full,
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QueryPhase {
    Compile,
    Query,
    Report,
    Encoded,
}
pub type QueryObserver = dyn Fn(QueryPhase) + Send + Sync;
#[derive(Clone, Default)]
pub struct QueryOptions {
    pub saved_query: Option<String>,
    pub query_name: Option<String>,
    pub libraries: Option<BTreeMap<String, String>>,
    pub reference: bool,
    pub profile: bool,
    pub timeout_ms: Option<f64>,
    pub max_states: Option<u64>,
    pub max_rows: Option<u64>,
    pub cancellation: Cancellation,
    pub include_entities: bool,
    pub deadline: Option<Instant>,
    pub observer: Option<Arc<QueryObserver>>,
}
impl QueryOptions {
    fn validate(&self) -> Result<()> {
        if self.timeout_ms.is_some_and(|m| !m.is_finite() || m < 0.)
            || self.max_states == Some(0)
            || self.max_rows == Some(0)
        {
            Err(SessionError::InvalidBudget)
        } else {
            Ok(())
        }
    }
    fn phase(&self, phase: QueryPhase) {
        if let Some(observer) = &self.observer {
            observer(phase);
        }
    }
    fn deadline(&self, started: Instant) -> Result<Option<Instant>> {
        let own = self
            .timeout_ms
            .map(|ms| {
                Duration::try_from_secs_f64(ms / 1000.)
                    .ok()
                    .and_then(|d| started.checked_add(d))
                    .ok_or(SessionError::InvalidBudget)
            })
            .transpose()?;
        Ok(match (own, self.deadline) {
            (Some(a), Some(b)) => Some(a.min(b)),
            (a, b) => a.or(b),
        })
    }
}
#[derive(Default)]
struct RevisionState {
    epoch: u64,
    dirty: bool,
}
#[derive(Clone, Default)]
pub struct InvalidationHandle(Arc<Mutex<RevisionState>>);
impl InvalidationHandle {
    pub fn invalidate(&self) {
        let mut state = self.0.lock().unwrap_or_else(|e| e.into_inner());
        state.epoch = state.epoch.wrapping_add(1);
        state.dirty = true;
    }
}
struct Resources {
    paths: ProjectPaths,
    context: DiscoveryContext,
    catalog: Arc<GrammarCatalog>,
    packaged: RwLock<BTreeMap<String, String>>,
    cache_directory: Option<PathBuf>,
}
/// Source policy and native resources are captured at this boundary; each open
/// session receives its own reader, compilation cache and packaged snapshot.
#[derive(Clone)]
pub struct QueryApplication {
    resources: Arc<Resources>,
}
impl QueryApplication {
    pub fn new(
        root: &Path,
        catalog: Arc<GrammarCatalog>,
        packaged: BTreeMap<String, String>,
    ) -> Result<Self> {
        Self::new_with_cache_directory(root, catalog, packaged, None)
    }
    pub fn new_with_cache_directory(
        root: &Path,
        catalog: Arc<GrammarCatalog>,
        packaged: BTreeMap<String, String>,
        cache_directory: Option<PathBuf>,
    ) -> Result<Self> {
        let context = DiscoveryContext::from_process()?;
        let cache_directory = cache_directory
            .map(|path| std::path::absolute(context.cwd.join(path)))
            .transpose()
            .map_err(|e| SessionError::Invalid(e.to_string()))?;
        let paths = ProjectPaths::at(root, &context)?;
        if !paths.root().is_dir() {
            return Err(SessionError::Invalid(
                "project root does not exist or is not a directory".into(),
            ));
        }
        Ok(Self {
            resources: Arc::new(Resources {
                paths,
                context,
                catalog,
                packaged: RwLock::new(packaged),
                cache_directory,
            }),
        })
    }
    pub fn root(&self) -> &Path {
        self.resources.paths.root()
    }
    pub fn replace_packaged_libraries(&self, packaged: BTreeMap<String, String>) -> Result<()> {
        *self
            .resources
            .packaged
            .write()
            .map_err(|_| SessionError::Invalid("packaged library state poisoned".into()))? =
            packaged;
        Ok(())
    }
    pub fn open(&self, options: SessionOptions) -> Result<QuerySession> {
        self.open_checked(options, &mut || Ok(()))
    }
    pub fn open_transient(&self, options: SessionOptions) -> Result<QuerySession> {
        self.open_transient_checked(options, &mut || Ok(()))
    }
    pub fn open_transient_checked(
        &self,
        mut options: SessionOptions,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<QuerySession> {
        options.cache_mb = 0.;
        self.open_session(options, false, check)
    }
    pub fn open_checked(
        &self,
        options: SessionOptions,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<QuerySession> {
        self.open_session(options, true, check)
    }
    fn open_session(
        &self,
        options: SessionOptions,
        persistent: bool,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<QuerySession> {
        let budget = Budgets::new(&options, persistent)?;
        let libraries = self
            .resources
            .packaged
            .read()
            .map_err(|_| SessionError::Invalid("packaged library state poisoned".into()))?
            .clone();
        let mut session = QuerySession {
            resources: self.resources.clone(),
            options,
            budget,
            persistent,
            owner_pid: std::process::id(),
            owner_thread: thread::current().id(),
            closed: false,
            invalidation: InvalidationHandle::default(),
            revision: None,
            modules: ModuleResolver::new(self.root(), libraries),
            compiled: compilation::CompilationCache::new(budget.memory_bytes),
            generation: 0,
        };
        session.refresh_checked(check)?;
        Ok(session)
    }
}
#[derive(Clone, Copy)]
struct Budgets {
    total_mb: f64,
    disk_mb: f64,
    memory_bytes: usize,
    disk_bytes: u64,
}
impl Budgets {
    fn new(options: &SessionOptions, persistent: bool) -> Result<Self> {
        let total = options.cache_mb;
        let bytes = total * 1_000_000.;
        if !total.is_finite() || total < 0. || !bytes.is_finite() || bytes > u64::MAX as f64 {
            return Err(SessionError::Invalid(
                "cache max_mb must be finite and nonnegative".into(),
            ));
        }
        let memory = (total / 5.).min(100.);
        let disk = total - memory;
        if persistent && disk < 0.512 {
            return Err(SessionError::PersistentStorageRequired);
        }
        if options.max_file_bytes == 0 {
            return Err(SessionError::Invalid(
                "max_file_bytes must be positive".into(),
            ));
        }
        Ok(Self {
            total_mb: total,
            disk_mb: disk,
            memory_bytes: (memory * 1_000_000.).min(usize::MAX as f64) as usize,
            disk_bytes: (disk * 1_000_000.) as u64,
        })
    }
}
struct Revision {
    project: AcquiredProject,
    snapshot: i64,
    units: usize,
    coverage: bool,
    analysis: Json,
    frontend: String,
}
/// An owner-thread retained immutable revision. Watcher notifications only set
/// an epoch; they never replace its reader or update source facts during query.
pub struct QuerySession {
    resources: Arc<Resources>,
    options: SessionOptions,
    budget: Budgets,
    persistent: bool,
    owner_pid: u32,
    owner_thread: ThreadId,
    closed: bool,
    invalidation: InvalidationHandle,
    revision: Option<Revision>,
    modules: ModuleResolver,
    compiled: compilation::CompilationCache,
    generation: u64,
}
impl QuerySession {
    fn check_owner(&self) -> Result<()> {
        if self.owner_pid != std::process::id() || self.owner_thread != thread::current().id() {
            return Err(SessionError::Owner);
        }
        if self.closed {
            return Err(SessionError::Closed);
        }
        Ok(())
    }
    pub fn invalidation_handle(&self) -> InvalidationHandle {
        self.invalidation.clone()
    }
    pub fn invalidate(&self) {
        self.invalidation.invalidate();
    }
    fn state(&self) -> (u64, bool) {
        let state = self
            .invalidation
            .0
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        (state.epoch, state.dirty)
    }
    fn ready_epoch(&self, operation: &str) -> Result<u64> {
        let (epoch, dirty) = self.state();
        if dirty {
            Err(SessionError::SourcesChanged(format!(
                "sources invalidated; refresh before {operation}"
            )))
        } else {
            Ok(epoch)
        }
    }
    pub fn refresh(&mut self) -> Result<()> {
        self.refresh_checked(&mut || Ok(()))
    }
    pub fn refresh_checked(&mut self, check: &mut dyn FnMut() -> Result<()>) -> Result<()> {
        self.check_owner()?;
        let (epoch, _) = self.state();
        let resources = self.resources.clone();
        let libraries = resources
            .packaged
            .read()
            .map_err(|_| SessionError::Invalid("packaged library state poisoned".into()))?
            .clone();
        let (cache_path, database) = if let Some(directory) = &resources.cache_directory {
            (
                directory.join("source-cache.sqlite"),
                directory.join("store.sqlite"),
            )
        } else {
            (
                resources.paths.resolve_inside(
                    Path::new(".ken/structural/cache.sqlite"),
                    &resources.context,
                )?,
                resources.paths.resolve_inside(
                    Path::new(".ken/structural/v2/store.sqlite"),
                    &resources.context,
                )?,
            )
        };
        let frontend = NativeFrontend::new(&resources.catalog);
        let cache = ArtifactCache::open(&cache_path, (self.budget.total_mb / 5.).min(100.))?;
        let mut builder = ProjectBuilder::new(
            resources.paths.clone(),
            resources.context.clone(),
            &frontend,
            cache,
        );
        let mut failure = None;
        let acquired = ProjectAcquisition::new(&mut builder, &database, self.persistent)
            .acquire_sources(
                &self.options.path,
                self.options.source_paths.as_deref(),
                ScanLimits {
                    max_files: None,
                    max_file_bytes: self.options.max_file_bytes,
                },
                || {
                    if let Err(error) = check() {
                        failure = Some(error);
                        return Err(BuildError::Invalid("session acquisition interrupted"));
                    }
                    if self.state().0 != epoch {
                        failure = Some(SessionError::SourcesChanged(
                            "sources changed during refresh; refresh again".into(),
                        ));
                        return Err(BuildError::Invalid("session acquisition invalidated"));
                    }
                    Ok(())
                },
            );
        if let Some(failure) = failure {
            return Err(failure);
        }
        let mut project = acquired?;
        if self.persistent && !project.persistent() {
            return Err(SessionError::PersistentStorageRequired);
        }
        let snapshot = {
            let index = project.index()?;
            index.snapshot_id()
        };
        let units = project.source_store().connection().query_row(
            "SELECT count(*) FROM k2_snapshot_units WHERE snapshot_id=?",
            [snapshot],
            |r| r.get::<_, i64>(0),
        )? as usize;
        let allocated = project.allocated_bytes()?;
        if project.persistent() && allocated > self.budget.disk_bytes {
            return Err(SessionError::PersistentStorageRequired);
        }
        project.source_store_mut().limit_bytes =
            project.persistent().then_some(self.budget.disk_bytes);
        project.source_store_mut().defer_busy_renewal = true;
        project
            .source_store()
            .connection()
            .busy_timeout(Duration::ZERO)?;
        let analysis = project.analysis.clone();
        let coverage = analysis["coverage_complete"].as_bool().unwrap_or(false);
        let frontend = crate::Frontend::revision(&frontend).to_owned();
        let retain = match self.revision.as_ref() {
            Some(old)
                if project.persistent()
                    && old.project.persistent()
                    && old.snapshot == snapshot
                    && old.project.graph == project.graph
                    && old.frontend == frontend
                    && old.project.source_store().path() == project.source_store().path() =>
            {
                match old
                    .project
                    .source_store()
                    .check_pinned_snapshot(old.snapshot)
                {
                    Ok(()) => true,
                    Err(StructuralError::Expired) => false,
                    Err(error) => return Err(error.into()),
                }
            }
            _ => false,
        };
        let mut state = self
            .invalidation
            .0
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        if state.epoch != epoch {
            return Err(SessionError::SourcesChanged(
                "sources changed during refresh; refresh again".into(),
            ));
        }
        let previous = if retain {
            let current = self.revision.as_mut().unwrap();
            current.units = units;
            current.coverage = coverage;
            current.analysis = analysis;
            Some(project)
        } else {
            self.generation = self.generation.saturating_add(1);
            self.revision
                .replace(Revision {
                    project,
                    snapshot,
                    units,
                    coverage,
                    analysis,
                    frontend,
                })
                .map(|r| r.project)
        };
        state.dirty = false;
        drop(state);
        let old_modules = std::mem::replace(
            &mut self.modules,
            ModuleResolver::new(resources.paths.root(), libraries),
        );
        drop(old_modules);
        if let Some(previous) = previous {
            previous.close()?;
        }
        Ok(())
    }
    pub fn resolve_query(
        &mut self,
        source: Option<&str>,
        saved_query: Option<&str>,
        query_name: Option<&str>,
        libraries: Option<&BTreeMap<String, String>>,
    ) -> Result<ResolvedQuery> {
        self.check_owner()?;
        Ok(self
            .modules
            .resolve(source, saved_query, query_name, libraries)?)
    }
    fn prepared(
        &mut self,
        resolved: &ResolvedQuery,
        reference: bool,
    ) -> Result<(Arc<CompiledQuery>, Json)> {
        self.compiled.compile(resolved, reference)
    }
    fn check_profile(&self, compiled: &CompiledQuery, reference: bool) -> Result<()> {
        if self.options.source_profile == SourceProfile::LocalHazards
            && (reference || !execution::local_hazards(compiled))
        {
            Err(SessionError::InvalidProfile)
        } else {
            Ok(())
        }
    }
    pub fn search(&mut self, source: Option<&str>, options: QueryOptions) -> Result<QueryResponse> {
        let started = Instant::now();
        self.search_started(source, &options, started)
    }
    fn search_started(
        &mut self,
        source: Option<&str>,
        options: &QueryOptions,
        started: Instant,
    ) -> Result<QueryResponse> {
        options.validate()?;
        let deadline = options.deadline(started)?;
        self.check_owner()?;
        let resolved = self.resolve_query(
            source,
            options.saved_query.as_deref(),
            options.query_name.as_deref(),
            options.libraries.as_ref(),
        )?;
        let epoch = self.ready_epoch("querying")?;
        options.phase(QueryPhase::Compile);
        let (compiled, compilation) = self.prepared(&resolved, options.reference)?;
        let compile_ms = started.elapsed().as_secs_f64() * 1000.;
        self.check_profile(&compiled, options.reference)?;
        options.phase(QueryPhase::Query);
        let revision = self.revision.as_ref().ok_or(SessionError::Closed)?;
        let outcome = execution::run(revision, &compiled, options, deadline)?;
        let mut response = query_response(&compiled.program, outcome, revision.coverage);
        let diagnostics = ken_query::authoring::diagnose(&compiled.program);
        if !diagnostics.is_empty() {
            response.diagnostics = Some(diagnostics);
        }
        response.analysis = Some(
            json!({"snapshot":revision.snapshot,"frontend":revision.frontend,"freshness":"captured_snapshot","source_profile":self.options.source_profile,"parsed_units":0,"reused_units":revision.units,"cache_mb":self.budget.total_mb,"disk_budget_mb":self.budget.disk_mb,"compilation_cache":compilation,"result_cache":"disabled","ephemeral":!self.persistent,"states":response.states,"scanned_nodes":response.scanned_nodes,"compile_ms":compile_ms,"build_ms":0.,"query_ms":response.elapsed_ms,"total_ms":started.elapsed().as_secs_f64()*1000.,"semantic_storage":"shared_disk","reader_generation":self.generation,"manifest":revision.analysis.get("manifest").cloned().unwrap_or(json!([])),"native_query_index":revision.analysis.get("query_index").cloned().unwrap_or(Json::Null)}),
        );
        if let Some(paths) = &self.options.source_paths {
            let paths = paths
                .iter()
                .cloned()
                .collect::<std::collections::BTreeSet<_>>();
            response.source_scope = Some(json!({"kind":"explicit_files","paths":paths}));
        }
        if options.include_entities {
            response.entities = Some(match reporting::locations(revision, &response.rows) {
                Ok(locations) => locations,
                Err(error) if execution::snapshot_expired(&error) => {
                    response.rows.clear();
                    response.complete = false;
                    response.reason = Some("snapshot_expired".into());
                    response.unknown_candidates = 0;
                    response.results_truncated = false;
                    response.plan.clear();
                    response.optional_evidence.clear();
                    BTreeMap::new()
                }
                Err(error) => return Err(error),
            });
        }
        if options.profile {
            response.analysis.as_mut().unwrap()["operator_profile"] = json!(response.profile);
        }
        let mut extra = json!({"analysis":response.analysis.take().unwrap()});
        resolved.annotate(&mut extra)?;
        response.analysis = extra.get_mut("analysis").map(std::mem::take);
        self.finish_delivery(
            &mut response,
            started,
            deadline,
            epoch,
            &options.cancellation,
        );
        options.phase(QueryPhase::Report);
        self.finish_delivery(
            &mut response,
            started,
            deadline,
            epoch,
            &options.cancellation,
        );
        Ok(response)
    }
    fn finish_delivery(
        &self,
        response: &mut QueryResponse,
        started: Instant,
        deadline: Option<Instant>,
        epoch: u64,
        cancellation: &Cancellation,
    ) -> bool {
        if let Some(analysis) = &mut response.analysis {
            analysis["total_ms"] = json!(started.elapsed().as_secs_f64() * 1000.);
        }
        let (current, dirty) = self.state();
        let reason = if dirty || current != epoch {
            Some("snapshot_invalidated")
        } else if cancellation.is_cancelled() {
            Some("cancelled")
        } else if deadline.is_some_and(|d| Instant::now() >= d) {
            Some("timeout")
        } else {
            None
        };
        if response.complete
            && let Some(reason) = reason
        {
            response.complete = false;
            response.reason = Some(reason.into());
            return true;
        }
        false
    }
    pub fn search_json(&mut self, source: Option<&str>, options: QueryOptions) -> Result<String> {
        let started = Instant::now();
        options.validate()?;
        let deadline = options.deadline(started)?;
        let epoch = self.state().0;
        let mut response = self.search_started(source, &options, started)?;
        let mut encoded = serde_json::to_string(&response)?;
        options.phase(QueryPhase::Encoded);
        let corrected = self.finish_delivery(
            &mut response,
            started,
            deadline,
            epoch,
            &options.cancellation,
        );
        if corrected {
            encoded = serde_json::to_string(&response)?;
        } else {
            let total = started.elapsed().as_secs_f64() * 1000.;
            encoded = reporting::encoded_total(encoded, total)?;
        }
        if self.finish_delivery(
            &mut response,
            started,
            deadline,
            epoch,
            &options.cancellation,
        ) {
            encoded = serde_json::to_string(&response)?;
        }
        Ok(encoded)
    }
    pub fn prepare_graph(&mut self) -> Result<()> {
        self.check_owner()?;
        self.ready_epoch("preparing graph")?;
        let revision = self.revision.as_ref().ok_or(SessionError::Closed)?;
        revision
            .project
            .source_store()
            .check_pinned_snapshot(revision.snapshot)?;
        revision.project.retained_index()?;
        Ok(())
    }
    pub fn prepare_semantics(&mut self) -> Result<()> {
        self.check_owner()?;
        self.ready_epoch("preparing semantics")?;
        self.prepare_graph()
    }
    pub fn prepare_query(&mut self, source: Option<&str>, options: QueryOptions) -> Result<f64> {
        self.check_owner()?;
        let resolved = self.resolve_query(
            source,
            options.saved_query.as_deref(),
            options.query_name.as_deref(),
            options.libraries.as_ref(),
        )?;
        let (compiled, _) = self.prepared(&resolved, options.reference)?;
        self.check_profile(&compiled, options.reference)?;
        self.ready_epoch("preparing query")?;
        self.prepare_graph()?;
        Ok(0.)
    }
    pub fn maintain(&mut self) -> Result<()> {
        self.check_owner()?;
        let revision = self.revision.as_ref().ok_or(SessionError::Closed)?;
        revision
            .project
            .source_store()
            .check_pinned_snapshot(revision.snapshot)?;
        Ok(())
    }
    pub fn close(&mut self) -> Result<()> {
        if self.owner_pid != std::process::id() || self.owner_thread != thread::current().id() {
            return Err(SessionError::Owner);
        }
        self.closed = true;
        let project = self.revision.take().map(|r| r.project);
        self.compiled.clear();
        let modules = self.modules.close();
        let storage = project.map(AcquiredProject::close).transpose();
        modules?;
        storage?;
        Ok(())
    }
}
