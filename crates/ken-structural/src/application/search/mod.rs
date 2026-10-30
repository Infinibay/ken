//! Public structural searches compose capture, rule execution and presentation.
mod batch;
mod reporting;
use super::catalog::{Catalog, CatalogError, RuleLibrary};
use super::exploration::{PatternBackend, PatternOptions, buckets::BucketOptions};
use crate::{BuildError, NativeFrontend, ProjectAcquisition, ProjectBuilder, ScanLimits};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_reader::SourceFileReader,
};
use ken_query::execution::{
    Cancellation, EvidenceMode, ExecutionError, ExecutionOptions, QueryBudget,
};
use ken_store::artifact_cache::ArtifactCache;
use ken_syntax::GrammarCatalog;
pub use reporting::present;
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    sync::Arc,
};
#[derive(Debug, thiserror::Error)]
pub enum SearchError {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Catalog(#[from] CatalogError),
    #[error(transparent)]
    Build(#[from] BuildError),
    #[error(transparent)]
    Query(#[from] ExecutionError),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Cache(#[from] ken_store::artifact_cache::InvalidCacheBudget),
}
pub type Result<T> = std::result::Result<T, SearchError>;
fn invalid(value: impl Into<String>) -> SearchError {
    SearchError::Invalid(value.into())
}
#[derive(Clone, Default)]
pub struct SearchRequest {
    pub query: String,
    pub rules: Vec<String>,
    pub collections: Vec<String>,
    pub tags: Vec<String>,
    pub rule_files: Vec<PathBuf>,
}
#[derive(Clone)]
pub struct SearchOptions {
    pub path: PathBuf,
    pub cache_mb: Option<f64>,
    pub limits: ScanLimits,
    pub budget: QueryBudget,
    pub evidence_mode: EvidenceMode,
    pub cancellation: Cancellation,
    pub use_result_cache: bool,
}
impl Default for SearchOptions {
    fn default() -> Self {
        Self {
            path: ".".into(),
            cache_mb: None,
            limits: ScanLimits::default(),
            budget: Default::default(),
            evidence_mode: Default::default(),
            cancellation: Default::default(),
            use_result_cache: true,
        }
    }
}
pub struct StructuralApplication {
    paths: ProjectPaths,
    context: DiscoveryContext,
    grammars: Arc<GrammarCatalog>,
    catalog: Catalog,
    cache_directory: Option<PathBuf>,
}
impl StructuralApplication {
    pub fn new(root: &Path, grammars: Arc<GrammarCatalog>) -> Result<Self> {
        Self::new_with_cache_directory(root, grammars, None)
    }
    pub fn new_with_cache_directory(
        root: &Path,
        grammars: Arc<GrammarCatalog>,
        cache_directory: Option<PathBuf>,
    ) -> Result<Self> {
        let context = DiscoveryContext::from_process()?;
        let cache_directory = cache_directory
            .map(|path| std::path::absolute(context.cwd.join(path)))
            .transpose()?;
        let paths = ProjectPaths::at(root, &context)?;
        Ok(Self {
            paths,
            context,
            grammars,
            catalog: Catalog::packaged()?,
            cache_directory,
        })
    }
    pub fn search(&self, request: SearchRequest, options: SearchOptions) -> Result<Value> {
        let selecting = !request.rules.is_empty()
            || !request.collections.is_empty()
            || !request.tags.is_empty();
        if !request.query.is_empty() && selecting {
            return Err(invalid(
                "choose an inline query or saved rule selectors, not both",
            ));
        }
        if request.query.is_empty() && !selecting {
            return Err(invalid(
                "provide a query, rule, collection, tag, or rule file",
            ));
        }
        let library = RuleLibrary::load(self.paths.root(), &self.catalog, &request.rule_files)?;
        let batch = batch::PreparedBatch::select(&library, &request)?;
        let mut response = self.execute(&library, batch, &options)?;
        if !request.query.is_empty() {
            let outcome = response["outcomes"]["query"].clone();
            for (key, value) in outcome.as_object().into_iter().flatten() {
                response[key] = value.clone();
            }
        }
        let files = response["analysis"]["files"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        response["directories"] = reporting::directories(&response["matches"], &files, "rules");
        Ok(response)
    }
    pub fn patterns(&self, names: &[String], options: SearchOptions) -> Result<Value> {
        self.patterns_with_options(
            names,
            PatternOptions {
                search: options,
                ..Default::default()
            },
        )
    }
    pub fn patterns_with_options(
        &self,
        names: &[String],
        options: PatternOptions,
    ) -> Result<Value> {
        let library = RuleLibrary::packaged(&self.catalog)?;
        let request = SearchRequest {
            rules: names.to_vec(),
            collections: vec!["gof".into()],
            ..Default::default()
        };
        let batch = batch::PreparedBatch::select(&library, &request)?;
        let mut search = options.search.clone();
        if options.profile {
            search.use_result_cache = false;
        }
        let mut response =
            self.execute_with_pattern(&library, batch, &search, Some(options.backend))?;
        let mut findings = response["matches"].take();
        for item in findings.as_array_mut().into_iter().flatten() {
            let rule = &item["rule"];
            let category = rule["tags"]
                .as_array()
                .and_then(|tags| tags.get(1))
                .cloned()
                .unwrap_or(Value::Null);
            item["category"] = category;
            item["caveat"] = item["rule"]["caveat"].clone();
        }
        let incomplete = response["outcomes"]
            .as_object()
            .into_iter()
            .flatten()
            .filter(|(_, outcome)| outcome["complete"] == false)
            .map(|(id, outcome)| (id.clone(), outcome["unknown"].clone()))
            .collect::<serde_json::Map<_, _>>();
        response.as_object_mut().unwrap().remove("matches");
        response.as_object_mut().unwrap().remove("rules");
        response["findings"] = findings;
        response["incomplete"] = json!(incomplete);
        response["directories"] = reporting::directories(
            &response["findings"],
            response["analysis"]["files"]
                .as_array()
                .map(Vec::as_slice)
                .unwrap_or_default(),
            "patterns",
        );
        Ok(response)
    }
    pub fn bugs(&self, options: SearchOptions) -> Result<Value> {
        let library = RuleLibrary::packaged(&self.catalog)?;
        let request = SearchRequest {
            collections: vec!["bugs".into()],
            ..Default::default()
        };
        let batch = batch::PreparedBatch::select(&library, &request)?;
        let mut response = self.execute(&library, batch, &options)?;
        let mut findings = response["matches"].take();
        for finding in findings.as_array_mut().into_iter().flatten() {
            finding["message"] = finding["rule"]["description"].clone();
            finding["severity"] = finding["rule"]["severity"].clone();
        }
        response.as_object_mut().unwrap().remove("matches");
        response.as_object_mut().unwrap().remove("rules");
        response["findings"] = findings;
        Ok(response)
    }
    pub fn cache_capacity(&self, override_mb: Option<f64>) -> Result<f64> {
        let path = self
            .paths
            .resolve_inside(Path::new(".ken/structural.json"), &self.context)?;
        let mut selected = json!(500.);
        if path.exists() {
            let bytes = SourceFileReader::new(&self.paths)?
                .open(&path)?
                .read_bounded(1_000_000)?
                .ok_or_else(|| invalid("structural configuration exceeds 1 MB"))?;
            let config: Value = serde_json::from_slice(&bytes)?;
            if let Some(value) = config.pointer("/cache/max_mb") {
                selected = value.clone();
            }
            if config.pointer("/cache/enabled") == Some(&json!(false)) {
                selected = json!(0.);
            }
        }
        if let Some(value) = std::env::var_os("KEN_STRUCTURAL_CACHE_MB") {
            selected = json!(value.to_string_lossy());
        }
        let capacity = if let Some(value) = override_mb {
            Some(value)
        } else {
            match selected {
                Value::Number(value) => value.as_f64(),
                Value::String(value) => value.trim().parse().ok(),
                Value::Bool(value) => Some(f64::from(u8::from(value))),
                _ => None,
            }
        }
        .filter(|value| value.is_finite() && *value >= 0.)
        .ok_or_else(|| invalid("cache max_mb must be finite and nonnegative"))?;
        Ok(capacity)
    }
    fn execute(
        &self,
        library: &RuleLibrary,
        batch: batch::PreparedBatch,
        options: &SearchOptions,
    ) -> Result<Value> {
        self.execute_with_pattern(library, batch, options, None)
    }
    fn execute_with_pattern(
        &self,
        library: &RuleLibrary,
        batch: batch::PreparedBatch,
        options: &SearchOptions,
        backend: Option<PatternBackend>,
    ) -> Result<Value> {
        let started = std::time::Instant::now();
        let deadline = backend
            .and(options.budget.timeout_ms)
            .and_then(|ms| started.checked_add(std::time::Duration::from_millis(ms)));
        ken_query::execution::Execution::new(ExecutionOptions {
            budget: options.budget.clone(),
            ..Default::default()
        })?;
        batch.validate()?;
        let capacity = self.cache_capacity(options.cache_mb)?;
        let frontend = NativeFrontend::new(&self.grammars);
        let (source_cache, database) = if let Some(directory) = &self.cache_directory {
            (
                directory.join("source-cache.sqlite"),
                directory.join("patterns.sqlite"),
            )
        } else {
            (
                self.paths
                    .resolve_inside(Path::new(".ken/structural-cache.sqlite"), &self.context)?,
                self.paths.resolve_inside(
                    Path::new(".ken/structural/v2/patterns.sqlite"),
                    &self.context,
                )?,
            )
        };
        let cache = ArtifactCache::open(&source_cache, capacity)?;
        let mut builder =
            ProjectBuilder::new(self.paths.clone(), self.context.clone(), &frontend, cache);
        let mut project = ProjectAcquisition::new(&mut builder, &database, capacity > 0.).acquire(
            &options.path,
            options.limits,
            || {
                if options.cancellation.is_cancelled() {
                    Err(BuildError::Invalid(
                        "structural source acquisition cancelled",
                    ))
                } else if deadline.is_some_and(|d| std::time::Instant::now() >= d) {
                    Err(BuildError::Invalid("structural source acquisition timeout"))
                } else {
                    Ok(())
                }
            },
        )?;
        let result_path = if let Some(directory) = &self.cache_directory {
            directory.join("results.sqlite")
        } else {
            self.paths
                .resolve_inside(Path::new(".ken/structural-results.sqlite"), &self.context)?
        };
        let mut cache = ArtifactCache::open(
            &result_path,
            if options.use_result_cache {
                capacity
            } else {
                0.
            },
        )?;
        let controls = ExecutionOptions {
            budget: options.budget.clone(),
            evidence_mode: options.evidence_mode,
            cancellation: options.cancellation.clone(),
            ..Default::default()
        };
        let buckets = if backend == Some(PatternBackend::Exploration) {
            let directory = if let Some(directory) = &self.cache_directory {
                directory.clone()
            } else {
                self.paths
                    .resolve_inside(Path::new(".ken/structural/v2"), &self.context)?
            };
            Some(BucketOptions {
                cache_path: (capacity > 0.).then(|| directory.join("pattern-buckets.sqlite")),
                revision: project.analysis["graph_key"].as_str().unwrap_or("").into(),
                disk_bytes: (capacity * 1000000.).min(256000000.) as u64,
                memory_bytes: 64000000,
                cancellation: options.cancellation.clone(),
                deadline,
            })
        } else {
            None
        };
        let mut response = batch.execute(library, &mut project, &mut cache, controls, buckets)?;
        response["ok"] = json!(true);
        let mut analysis = project.analysis.clone();
        analysis["query_cache"] = serde_json::to_value(cache.stats())?;
        if let Some(backend) = backend {
            analysis["pattern_engine"] = json!({"backend":if backend==PatternBackend::Exploration{"exploration"}else{"indexed"},"semantic_backend":"native_sqlite_columns/1","bucket_memory_accounting":"serialized_payload_bytes","storage":if backend==PatternBackend::Exploration{Some("native_buckets/1")}else{None},"buckets":response["pattern_buckets"].take()});
            response.as_object_mut().unwrap().remove("pattern_buckets");
        }
        response["analysis"] = analysis;
        project.close()?;
        Ok(response)
    }
}
