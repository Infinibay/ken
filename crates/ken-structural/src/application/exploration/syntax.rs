use super::super::{
    modules::{ModuleError, ModuleResolver},
    sessions::{QueryResponse, query_response},
};
use super::cache::{Memo, decode, digest, encode};
use crate::{BuildError, ScanLimits, SourceManifest};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_query::{
    BackendPreference, ParseLimits,
    execution::{Cancellation, ExecutionError, indexed_runtime::IndexedOutcome},
    exploration::{NodeRecord, SyntaxExecutionOptions, SyntaxPlan, SyntaxUnit, execute},
};
use ken_syntax::{GrammarCatalog, ParseError};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};
#[derive(Debug, thiserror::Error)]
pub enum ExplorationError {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Build(#[from] BuildError),
    #[error(transparent)]
    Module(#[from] ModuleError),
    #[error(transparent)]
    Parse(#[from] ken_query::ParseError),
    #[error(transparent)]
    Syntax(#[from] ParseError),
    #[error(transparent)]
    Execution(#[from] ExecutionError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}
type Result<T> = std::result::Result<T, ExplorationError>;
#[derive(Clone)]
pub struct ExplorationOptions {
    pub path: PathBuf,
    pub cache_mb: f64,
    pub max_file_bytes: u64,
    pub source_paths: Option<Vec<String>>,
    pub saved_query: Option<String>,
    pub query_name: Option<String>,
    pub libraries: Option<BTreeMap<String, String>>,
    pub reference: bool,
    pub profile: bool,
    pub timeout_ms: Option<f64>,
    pub max_states: Option<u64>,
    pub max_rows: Option<u64>,
    pub cancellation: Cancellation,
    pub deadline: Option<Instant>,
}
impl Default for ExplorationOptions {
    fn default() -> Self {
        Self {
            path: ".".into(),
            cache_mb: 500.,
            max_file_bytes: 2000000,
            source_paths: None,
            saved_query: None,
            query_name: None,
            libraries: None,
            reference: false,
            profile: false,
            timeout_ms: None,
            max_states: None,
            max_rows: None,
            cancellation: Default::default(),
            deadline: None,
        }
    }
}
pub struct SyntaxExploration {
    paths: ProjectPaths,
    context: DiscoveryContext,
    grammars: Arc<GrammarCatalog>,
    packaged: BTreeMap<String, String>,
    cache_directory: Option<PathBuf>,
}
#[derive(Serialize, Deserialize)]
struct Stored {
    source: Vec<u8>,
    records: Vec<NodeRecord>,
}
#[derive(Clone)]
struct Control {
    cancellation: Cancellation,
    deadline: Option<Instant>,
}
impl Control {
    fn reason(&self) -> Option<&'static str> {
        if self.cancellation.is_cancelled() {
            Some("cancelled")
        } else if self.deadline.is_some_and(|d| Instant::now() >= d) {
            Some("timeout")
        } else {
            None
        }
    }
    fn check(&self) -> ken_query::execution::Result<()> {
        self.reason()
            .map_or(Ok(()), |r| Err(ExecutionError::Exhausted(r)))
    }
}
impl SyntaxExploration {
    pub fn new(
        root: &Path,
        grammars: Arc<GrammarCatalog>,
        packaged: BTreeMap<String, String>,
        cache_directory: Option<PathBuf>,
    ) -> Result<Self> {
        let context = DiscoveryContext::from_process()?;
        let paths = ProjectPaths::at(root, &context)?;
        if !paths.root().is_dir() {
            return Err(ExplorationError::Invalid(
                "project root does not exist or is not a directory".into(),
            ));
        }
        let cache_directory = cache_directory
            .map(|p| std::path::absolute(context.cwd.join(p)))
            .transpose()?;
        Ok(Self {
            paths,
            context,
            grammars,
            packaged,
            cache_directory,
        })
    }
    pub fn search_json(&self, source: Option<&str>, options: ExplorationOptions) -> Result<String> {
        Ok(serde_json::to_string(&self.search(source, options)?)?)
    }
    pub fn search(
        &self,
        source: Option<&str>,
        options: ExplorationOptions,
    ) -> Result<QueryResponse> {
        let started = Instant::now();
        let bytes = options.cache_mb * 1000000.;
        if !options.cache_mb.is_finite()
            || options.cache_mb < 0.
            || bytes > u64::MAX as f64
            || options.max_file_bytes == 0
            || options.max_rows == Some(0)
            || options.max_states == Some(0)
            || options.timeout_ms.is_some_and(|v| !v.is_finite() || v < 0.)
        {
            return Err(ExplorationError::Invalid(
                "invalid exploration budget".into(),
            ));
        }
        let own = options
            .timeout_ms
            .map(|ms| {
                Duration::try_from_secs_f64(ms / 1000.)
                    .ok()
                    .and_then(|d| started.checked_add(d))
                    .ok_or_else(|| ExplorationError::Invalid("invalid timeout".into()))
            })
            .transpose()?;
        let control = Control {
            cancellation: options.cancellation.clone(),
            deadline: match (own, options.deadline) {
                (Some(a), Some(b)) => Some(a.min(b)),
                (a, b) => a.or(b),
            },
        };
        // Admission is complete before enumeration, parsing source files or creating cache paths.
        let mut resolver = ModuleResolver::new(self.paths.root(), self.packaged.clone());
        let resolved = resolver.resolve(
            source,
            options.saved_query.as_deref(),
            options.query_name.as_deref(),
            options.libraries.as_ref(),
        )?;
        resolver.close()?;
        let tree = ken_query::parse(&resolved.source, "<query>", ParseLimits::default())?;
        let libraries = resolved
            .libraries()
            .iter()
            .map(|(k, v)| Ok((k.clone(), ken_query::parse(v, k, ParseLimits::default())?)))
            .collect::<std::result::Result<BTreeMap<_, _>, ken_query::ParseError>>()?;
        let compiled = ken_query::compile(
            &tree,
            resolved.query_name.as_deref(),
            &libraries,
            BackendPreference::Automatic,
        )?;
        let plan = SyntaxPlan::compile(&compiled.program)?;
        let compile_ms = ms(started);
        let retention = if bytes >= 512000. { bytes as u64 } else { 0 };
        let path = if let Some(dir) = &self.cache_directory {
            dir.join("syntax.sqlite")
        } else {
            self.paths
                .resolve_inside(Path::new(".ken/structural/v2/syntax.sqlite"), &self.context)?
        };
        let mut units = vec![];
        let mut skipped = vec![];
        let mut manifest = vec![];
        let mut parsed = 0;
        let mut reused = 0;
        let mut parse_ms = 0.;
        let mut projection_ms = 0.;
        let mut persist_ms = 0.;
        let mut evictions = 0;
        let mut allocated = 0;
        let mut cache_error = None;
        let mut cache_enabled = false;
        let mut read_ms = 0.;
        let build_start = Instant::now();
        let acquired = (|| -> Result<()> {
            control.check()?;
            let mut memo = Memo::new(
                (retention > 0).then_some(path.as_path()),
                retention,
                &mut || control.check(),
            )?;
            cache_enabled = memo.enabled();
            let read_start = Instant::now();
            let capture = SourceManifest::capture_sources(
                &self.paths,
                &self.context,
                &options.path,
                options.source_paths.as_deref(),
                crate::IMPLEMENTATION_FINGERPRINT,
                ScanLimits {
                    max_files: None,
                    max_file_bytes: options.max_file_bytes,
                },
                &mut || {
                    control.check().map_err(|e| match e {
                        ExecutionError::Exhausted("cancelled") => BuildError::Invalid("cancelled"),
                        _ => BuildError::Invalid("timeout"),
                    })
                },
            )?;
            read_ms = ms(read_start);
            skipped=capture.skipped().iter().map(|s|json!({"path":s.path,"reason":if s.reason=="no structural frontend"{"unsupported_frontend"}else{&s.reason}})).collect();
            for entry in capture.entries() {
                control.check()?;
                let hash = digest(entry.content(), &mut || control.check())?;
                manifest.push(json!([entry.path(), hash]));
                let key = entry.path();
                let revision = format!("{}:{hash}", crate::IMPLEMENTATION_FINGERPRINT);
                let source: Arc<[u8]> = entry.content().into();
                let mut unit = None;
                if let Some(raw) = memo.get(key, &revision, &mut || control.check())?
                    && let Ok(stored) = decode::<Stored>(&raw, &mut || control.check())
                    && stored.source == entry.content()
                {
                    unit = SyntaxUnit::new_checked(
                        entry.path().into(),
                        entry.language().as_str().into(),
                        source.clone(),
                        stored.records,
                        &mut || control.check(),
                    )
                    .ok();
                }
                if unit.is_some() {
                    reused += 1;
                } else {
                    let begin = Instant::now();
                    let syntax = self.grammars.syntax_checked(
                        entry.language(),
                        entry.content(),
                        entry.path(),
                        &mut || {
                            control.check().map_err(|e| ParseError::Parse {
                                language: entry.language().as_str().into(),
                                reason: e.to_string(),
                            })
                        },
                    );
                    parse_ms += ms(begin);
                    let syntax = match syntax {
                        Ok(tree) => tree,
                        Err(e) => {
                            control.check()?;
                            skipped.push(json!({"path":entry.path(),"reason":"frontend_error","detail":e.to_string()}));
                            continue;
                        }
                    };
                    let begin = Instant::now();
                    let mut records: Vec<NodeRecord> = vec![];
                    let mut pending: Vec<(
                        ken_syntax::SyntaxNode<'_>,
                        Option<usize>,
                        String,
                        bool,
                    )> = vec![(syntax.root(), None, String::new(), false)];
                    while let Some((node, parent, role, exit)) = pending.pop() {
                        control.check()?;
                        if exit {
                            let i = parent.unwrap();
                            records[i].subtree_end = records.len();
                            continue;
                        }
                        let i = records.len();
                        let (kind, category) =
                            ken_syntax::structural::syntax_classification(node.kind());
                        records.push(NodeRecord {
                            native_kind: node.kind().into(),
                            kind,
                            category,
                            role,
                            parent,
                            subtree_end: i + 1,
                            start_byte: node.start_byte(),
                            end_byte: node.end_byte(),
                            flags: node.is_named() as u8
                                | ((node.has_error() as u8) << 1)
                                | ((node.is_missing() as u8) << 2)
                                | ((node.is_error() as u8) << 3),
                        });
                        pending.push((node, Some(i), String::new(), true));
                        for (child, field) in node.children_with_fields().into_iter().rev() {
                            pending.push((child, Some(i), field.unwrap_or("").into(), false));
                        }
                    }
                    let stored = Stored {
                        source: entry.content().into(),
                        records,
                    };
                    let result = SyntaxUnit::new_checked(
                        entry.path().into(),
                        entry.language().as_str().into(),
                        source,
                        stored.records.clone(),
                        &mut || control.check(),
                    )?;
                    projection_ms += ms(begin);
                    parsed += 1;
                    let begin = Instant::now();
                    if retention > 0 {
                        let raw = encode(&stored, &mut || control.check())?;
                        memo.put(key, &revision, &raw, &mut || control.check())?;
                    }
                    persist_ms += ms(begin);
                    unit = Some(result);
                }
                let unit = unit.unwrap();
                if unit.records()[0].flags & 6 != 0 {
                    skipped.push(json!({"path":entry.path(),"reason":"parse_error"}));
                }
                units.push(Arc::new(unit));
            }
            evictions = memo.evictions;
            allocated = memo.allocated();
            cache_error = memo.error;
            Ok(())
        })();
        let stopped = if let Err(error) = acquired {
            if let Some(reason) = control.reason() {
                Some(reason)
            } else {
                return Err(error);
            }
        } else {
            None
        };
        let coverage = skipped.is_empty() && stopped.is_none();
        let build_ms = ms(build_start);
        let mut outcome = execute(
            &plan,
            &units,
            coverage,
            SyntaxExecutionOptions {
                reference: options.reference,
                profile: options.profile,
                cancellation: options.cancellation,
                deadline: control.deadline,
                max_states: options.max_states,
                max_rows: options.max_rows,
            },
        )?;
        if let Some(reason) = stopped {
            outcome.complete = false;
            outcome.reason = Some(reason.into());
        }
        let analysis = json!({"backend":"native_syntax_exploration","storage":"native_preorder/1","semantic_resolution":"not_requested","manifest":manifest,"skipped":skipped,"parsed_units":parsed,"reused_units":reused,"result_cache":"disabled","ephemeral":!cache_enabled,"retention_budget_bytes":retention,"evicted_units":evictions,"allocated_bytes":allocated,"allocation_accounting":"retained_serialized_payload_bytes","cache_error":cache_error,"compile_ms":compile_ms,"build_ms":build_ms,"phase_ms":{"read":read_ms,"parse":parse_ms,"projection":projection_ms,"persist":persist_ms},"states":outcome.states,"scanned_nodes":outcome.scanned_nodes,"scan_accounting":"named_candidates_delivered_from_postings","query_ms":outcome.query_ms,"total_ms":ms(started)});
        let profile = outcome.operator_profile.clone();
        let native = IndexedOutcome {
            rows: outcome.rows,
            complete: outcome.complete,
            reason: outcome.reason,
            unknown_candidates: outcome.unknown_candidates,
            results_truncated: outcome.results_truncated,
            plan: outcome.plan,
            states: outcome.states,
            scanned_nodes: outcome.scanned_nodes,
            elapsed_ms: outcome.query_ms,
            ..Default::default()
        };
        let mut response = query_response(&compiled.program, native, coverage);
        response.capability = "syntax-exploration/1";
        response.analysis = Some(analysis);
        if options.profile {
            response.analysis.as_mut().unwrap()["operator_profile"] = json!(profile);
        }
        if let Some(paths) = options.source_paths {
            response.source_scope = Some(json!({"kind":"explicit_files","paths":paths}));
        }
        Ok(response)
    }
}
fn ms(started: Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1000.
}
