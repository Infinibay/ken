//! Production composition uses the selected project model, never BestSearch roles.
use crate::{
    Error, Result,
    queue::{Action, Batch, BatchIndexer},
    server::{self, DaemonConfig, Maintenance},
    state::DaemonState,
};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_filter::SourceFilter,
    source_walk::ProjectSources,
};
use ken_index::{IndexOptions, Indexer};
use ken_models::{
    ModelFactory,
    model_policy::{ModelPolicy, ProjectModelFacts, is_asymmetric},
};
use ken_retrieval::{
    project_embeddings::{ProjectEmbeddings, TransformerOverrides, configure_project},
    query_encoder::QueryEncoder,
};
use ken_store::ProjectStore;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use rusqlite::OptionalExtension;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};
/// Immutable host inputs. Device/native runtime admission is already held by
/// ModelFactory; callers may supply a configured factory without global state.
pub struct NativeResources {
    pub factory: Arc<ModelFactory>,
    pub grammar_manifest: PathBuf,
    pub model_policy: ModelPolicy,
    pub environment: BTreeMap<String, String>,
    pub check_worker: Option<PathBuf>,
}
struct SharedQuery(Arc<ProjectEmbeddings>);
impl QueryEncoder for SharedQuery {
    fn embed_query(&self, text: &ken_text::PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.0.embed_query(text)
    }
}
impl NativeResources {
    pub fn installed(installation: &Path, environment: BTreeMap<String, String>) -> Result<Self> {
        let (fastembed, transformer) = device_requests(&environment);
        Ok(Self {
            factory: ken_search::SearchInstallation::open_model_factory_with_devices(
                installation,
                fastembed,
                transformer,
            )
            .map_err(crate::invalid)?,
            grammar_manifest: ken_search::SearchInstallation::grammar_manifest(installation)
                .map_err(crate::invalid)?,
            model_policy: user_model_policy(&environment),
            environment,
            check_worker: None,
        })
    }
    pub fn compose(self, root: &Path) -> Result<(DaemonState, Maintenance)> {
        let canonical_root = root.canonicalize()?;
        let root = canonical_root.as_path();
        let context = DiscoveryContext {
            cwd: root.into(),
            home: None,
            forced_root: None,
        };
        let paths = ProjectPaths::at(root, &context).map_err(crate::invalid)?;
        let mut bootstrap = ProjectStore::open(&paths)?;
        bootstrap.initialize()?;
        let before = bootstrap.database().model_state()?;
        let facts = ProjectModelFacts {
            recorded_model: before.recorded_model,
            file_vectors_present: before.file_vectors_present,
        };
        let environment_model = self.environment.get("KEN_EMBED_MODEL").map(String::as_str);
        let upgrade = self
            .model_policy
            .pending_upgrade(&facts, environment_model)
            .map(|u| (u.current, u.recommended));
        let resolved = configure_project(
            bootstrap.database().connection(),
            &self.model_policy,
            environment_model,
        )?;
        let raw_space: Option<String> = bootstrap
            .database()
            .connection()
            .query_row(
                "SELECT value FROM meta WHERE key='embed_doc_space'",
                [],
                |r| r.get(0),
            )
            .optional()?;
        let space = raw_space
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(if facts.file_vectors_present { 1 } else { 2 });
        let reembed=(is_asymmetric(&resolved.model)&&space<2&&facts.file_vectors_present).then(||format!("{} encodes questions and documents differently, and this index was built before ken applied that distinction to stored vectors",resolved.model));
        drop(bootstrap);
        let encoder = Arc::new(ProjectEmbeddings::new(
            self.factory,
            resolved.model,
            TransformerOverrides {
                sequence_length: self.environment.get("KEN_EMBED_MAX_SEQ").cloned(),
                batch_size: self.environment.get("KEN_EMBED_BATCH").cloned(),
            },
        ));
        let mut state = DaemonState::open(
            root,
            Rc::new(SharedQuery(encoder.clone())),
            Box::new(ken_context::NativeNumerics::default()),
            ken_context::Policy::capture(&self.environment)?,
        )?;
        state.brief_upgrade = upgrade;
        state.brief_reembed = reembed;
        if let Some(worker) = self.check_worker {
            let resources = ken_checks_application::Resources::prepared(
                &self.grammar_manifest,
                ken_checks_application::WorkerProgram::new(worker),
            )?;
            state.attach_checks(ken_checks_application::ChecksApplication::new(
                root, resources,
            )?)?;
        }
        let index = IndexResources {
            grammar_manifest: self.grammar_manifest,
            model: encoder.model().to_owned(),
            encoder,
        };
        let maintenance = index.maintenance(paths.root());
        Ok((state, maintenance))
    }
}
/// The CLI supplies its user-configured model policy through NativeResources when
/// available. This convenience uses the installation's explicit resource profile.
pub fn run(
    root: &Path,
    installation: &Path,
    check_worker: Option<PathBuf>,
    environment: &BTreeMap<String, String>,
) -> Result<()> {
    let mut resources = NativeResources::installed(installation, environment.clone())?;
    resources.check_worker = check_worker;
    let (state, maintenance) = resources.compose(root)?;
    server::serve(DaemonConfig::new(root), state, Some(maintenance))
}
/// Read the established user configuration using only the host's snapshot.
/// Malformed/missing files are optional preferences, never project pin loss.
pub fn user_model_policy(environment: &BTreeMap<String, String>) -> ModelPolicy {
    let path = |key: &str| environment.get(key).map(PathBuf::from);
    let config = ken_maintenance::UserConfig::new(&ken_maintenance::ConfigEnvironment {
        config_dir: path("KEN_CONFIG_DIR"),
        xdg_config_home: path("XDG_CONFIG_HOME"),
        home: path("HOME").unwrap_or_default(),
    });
    match config.recommended_model() {
        Ok(model) => ModelPolicy::new(Some(&model)),
        Err(error) => {
            eprintln!("ken user model preference unavailable: {error}");
            ModelPolicy::new(None)
        }
    }
}
/// Grammar and document encoding inputs for the dedicated index worker. A host
/// can inject a deterministic model without replacing indexing or storage.
pub struct IndexResources {
    pub grammar_manifest: PathBuf,
    pub model: String,
    pub encoder: Arc<dyn ken_retrieval::DocumentEncoder + Send + Sync>,
}
impl IndexResources {
    pub fn maintenance(self, root: &Path) -> Maintenance {
        let root = root.to_owned();
        Maintenance {
            factory: Box::new(move || Ok(Box::new(NativeIndexer::open(&root, self)?))),
        }
    }
}
struct NativeIndexer {
    paths: ProjectPaths,
    store: ProjectStore,
    parsers: ParserRegistry,
    resources: IndexResources,
}
impl NativeIndexer {
    fn open(root: &Path, resources: IndexResources) -> Result<Self> {
        let context = DiscoveryContext {
            cwd: root.into(),
            home: None,
            forced_root: None,
        };
        let paths = ProjectPaths::at(root, &context).map_err(crate::invalid)?;
        let mut store = ProjectStore::open(&paths)?;
        store.initialize()?;
        let parsers = ParserRegistry::new(
            GrammarCatalog::prepared(&resources.grammar_manifest).map_err(crate::invalid)?,
        );
        Ok(Self {
            paths,
            store,
            parsers,
            resources,
        })
    }
    fn sources(&self) -> Result<Vec<PathBuf>> {
        let context = DiscoveryContext {
            cwd: self.paths.root().into(),
            home: None,
            forced_root: None,
        };
        let sources = ProjectSources::new(self.paths.clone(), context);
        sources
            .walk(Path::new("."))
            .map_err(crate::invalid)?
            .filter_map(|entry| match entry {
                Ok(entry) if !entry.is_dir => Some(Ok(entry.path)),
                Ok(_) => None,
                Err(error) => Some(Err(crate::invalid(error))),
            })
            .collect()
    }
}
impl BatchIndexer for NativeIndexer {
    fn apply(&mut self, batch: &Batch) -> Result<()> {
        let mut reindex = Vec::new();
        if batch.resync {
            reindex = self.sources()?;
            let current = reindex
                .iter()
                .map(|p| p.to_string_lossy().into_owned())
                .collect::<BTreeSet<_>>();
            let old = self
                .store
                .database()
                .connection()
                .prepare("SELECT path FROM ci_files")?
                .query_map([], |r| r.get::<_, String>(0))?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            for path in old {
                if !current.contains(&path) {
                    ken_index::delete_path(self.store.database().connection(), &path)?;
                }
            }
        } else {
            let mut filter = SourceFilter::new(self.paths.root()).map_err(crate::invalid)?;
            let context = DiscoveryContext {
                cwd: self.paths.root().into(),
                home: None,
                forced_root: None,
            };
            for (path, action) in &batch.events {
                let resolved = self
                    .paths
                    .resolve_inside(Path::new(path), &context)
                    .map_err(crate::invalid)?;
                let relative = resolved
                    .strip_prefix(self.paths.root())
                    .map_err(crate::invalid)?;
                if relative.as_os_str().is_empty() {
                    return Err(Error::Invalid("index event requires a file path".into()));
                }
                if filter.is_ignored(relative, false).map_err(crate::invalid)?
                    || filter.is_ignored(relative, true).map_err(crate::invalid)?
                {
                    continue;
                }
                let relative_text = relative.to_string_lossy();
                match action {
                    Action::Delete => {
                        ken_index::delete_path(self.store.database().connection(), &relative_text)?;
                    }
                    Action::Reindex => {
                        if resolved.is_dir() {
                            return Err(Error::Invalid(
                                "directory index event requires resync".into(),
                            ));
                        }
                        reindex.push(relative.to_owned());
                    }
                }
            }
        }
        if !reindex.is_empty() {
            let options = IndexOptions {
                legacy_encoder: Some(self.resources.encoder.as_ref()),
                legacy_model: Some(&self.resources.model),
                ..Default::default()
            };
            Indexer::new(&self.parsers).index_files(
                self.store.database_mut(),
                &self.paths,
                &reindex,
                &options,
                &mut |_: &str, _: &str| {},
            )?;
        }
        Ok(())
    }
}

/// Capture requests without probing hardware or loading models. Actual runtime
/// availability/fallback remains owned by the prepared model backend.
pub fn device_requests(
    environment: &BTreeMap<String, String>,
) -> (
    ken_models::FastEmbedDeviceRequest,
    ken_models::TransformerDeviceRequest,
) {
    let preference = environment.get("KEN_EMBED_DEVICE").map(String::as_str);
    let ids = environment.get("KEN_EMBED_DEVICE_ID").map(String::as_str);
    let fast = ken_models::FastEmbedDeviceRequest::from_inputs(preference, ids);
    let pref = preference
        .unwrap_or("auto")
        .trim_matches(ken_text::unicode::whitespace)
        .to_lowercase();
    let transformer = match pref.as_str() {
        "cpu" => ken_models::TransformerDeviceRequest::Cpu,
        "auto" | "gpu" => ken_models::TransformerDeviceRequest::Auto,
        "mps" => ken_models::TransformerDeviceRequest::Mps,
        "cuda" => {
            let first = ids
                .unwrap_or("")
                .trim_matches(ken_text::unicode::whitespace)
                .split(',')
                .next()
                .unwrap_or("");
            let index = if !first.is_empty() && first.bytes().all(|b| b.is_ascii_digit()) {
                first.parse::<usize>().unwrap_or(usize::MAX)
            } else {
                0
            };
            ken_models::TransformerDeviceRequest::Cuda(index)
        }
        _ => ken_models::TransformerDeviceRequest::Cpu,
    };
    (fast, transformer)
}
