//! Provision project state, coordinate host ownership, and run the native indexer.
mod indexing;
mod metadata;
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    project_files::ProjectFiles,
};
use ken_hosts::{Bundles, HostInstaller, NativeCommand};
use ken_index::{DocumentEncoder, IndexStats};
use ken_maintenance::UserConfig;
use ken_models::model_policy::ModelPolicy;
use ken_retrieval::project_embeddings::configure_project;
use ken_store::ProjectStore;
use ken_syntax::GrammarCatalog;
use rusqlite::Connection;
use serde::Serialize;
use std::{
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Files(#[from] ken_core::project_files::Error),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
    #[error(transparent)]
    Sources(#[from] ken_core::source_filter::SourceError),
    #[error(transparent)]
    Hosts(#[from] ken_hosts::Error),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Index(#[from] ken_index::IndexError),
    #[error(transparent)]
    Retrieval(#[from] ken_retrieval::RetrievalError),
    #[error(transparent)]
    Config(#[from] ken_maintenance::Error),
    #[error(transparent)]
    Model(#[from] ken_models::ModelError),
    #[error(transparent)]
    Database(#[from] rusqlite::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
/// Resolve the explicitly selected eager encoder within the install operation.
pub type EncoderProvider<'a> = dyn FnMut(&Connection, &str) -> Result<Rc<dyn DocumentEncoder>> + 'a;
#[derive(Clone, Debug, Default)]
pub struct InstallOptions {
    pub hosts: ken_hosts::InstallOptions,
    pub embed: bool,
    pub embed_limit: Option<i64>,
}
impl InstallOptions {
    fn validate(&self) -> Result<()> {
        if self.embed_limit.is_some_and(|n| n < 0) {
            return Err(Error::Invalid("--embed-limit must be >= 0".into()));
        }
        if self.embed_limit.is_some() && !self.embed {
            return Err(Error::Invalid("--embed-limit requires --embed".into()));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, Default)]
pub struct UninstallOptions {
    pub keep_db: bool,
}
#[derive(Debug, Serialize)]
pub struct InstallReport {
    pub project_root: PathBuf,
    pub project_id: String,
    pub db_path: PathBuf,
    pub files_indexed: usize,
    pub symbols: usize,
    pub elapsed_s: f64,
    pub index: IndexStats,
    pub model: String,
    pub metadata_created: bool,
    pub gitignore_changed: bool,
    pub embedding_files: usize,
    pub hosts: ken_hosts::InstallReport,
    pub warnings: Vec<String>,
}
#[derive(Debug, Serialize)]
pub struct UninstallReport {
    pub project_root: PathBuf,
    pub removed_project_data: bool,
    pub hosts: ken_hosts::InstallReport,
}
/// The concrete host must stop only an existing daemon and must not spawn one.
pub trait DaemonLifecycle {
    fn stop_existing(&self, root: &Path) -> Result<()>;
}
pub struct ProjectInstallation {
    files: ProjectFiles,
    paths: ProjectPaths,
    catalog: Arc<GrammarCatalog>,
    native: NativeCommand,
    bundles: Bundles,
    config: UserConfig,
    environment_model: Option<String>,
}
enum Encoder<'a> {
    Borrowed(&'a dyn DocumentEncoder),
    Owned(Rc<dyn DocumentEncoder>),
}
impl Encoder<'_> {
    fn get(&self) -> &dyn DocumentEncoder {
        match self {
            Self::Borrowed(value) => *value,
            Self::Owned(value) => value.as_ref(),
        }
    }
}
fn paths(files: &ProjectFiles) -> Result<ProjectPaths> {
    Ok(ProjectPaths::at(
        &files.path,
        &DiscoveryContext {
            cwd: files.path.clone(),
            forced_root: None,
            home: None,
        },
    )?)
}
fn inspect_database_paths(files: &ProjectFiles) -> Result<()> {
    for name in [
        ".ken/meta.json",
        ".ken/ken.db",
        ".ken/ken.db-wal",
        ".ken/ken.db-shm",
        ".ken/ken.db-journal",
    ] {
        if files.exists(name)? && !files.is_file(name)? {
            return Err(Error::Invalid(format!(
                "project state must be a regular file: {name}"
            )));
        }
    }
    if files.exists(".ken/vectors")? && !files.is_directory(".ken/vectors")? {
        return Err(Error::Invalid("project vectors must be a directory".into()));
    }
    Ok(())
}
impl ProjectInstallation {
    pub fn new(
        root: &Path,
        catalog: Arc<GrammarCatalog>,
        native: NativeCommand,
        bundles: Bundles,
        config: UserConfig,
        environment_model: Option<String>,
    ) -> Result<Self> {
        let files = ProjectFiles::new(root)?;
        if files.path.to_str().is_none() {
            return Err(Error::Invalid(
                "project installation requires a UTF-8 canonical root path".into(),
            ));
        }
        let paths = paths(&files)?;
        let native = NativeCommand::new(native.program, native.prefix_args)?;
        Ok(Self {
            files,
            paths,
            catalog,
            native,
            bundles,
            config,
            environment_model,
        })
    }
    pub fn install(
        &self,
        options: &InstallOptions,
        encoder: Option<&dyn DocumentEncoder>,
        now: i64,
    ) -> Result<InstallReport> {
        self.install_using(options, now, |_, _| {
            encoder.map(Encoder::Borrowed).ok_or_else(|| {
                Error::Invalid("eager embedding requires an explicit native encoder".into())
            })
        })
    }
    pub fn install_with_provider(
        &self,
        options: &InstallOptions,
        now: i64,
        provider: &mut EncoderProvider<'_>,
    ) -> Result<InstallReport> {
        self.install_using(options, now, |db, model| {
            Ok(Encoder::Owned(provider(db, model)?))
        })
    }
    fn install_using<'a>(
        &self,
        options: &InstallOptions,
        now: i64,
        provider: impl FnOnce(&Connection, &str) -> Result<Encoder<'a>>,
    ) -> Result<InstallReport> {
        options.validate()?;
        let guard = self.files.lock()?;
        let directory = self
            .files
            .directory_handle(".ken", true)?
            .expect("created project state");
        self.files.check_directory(".ken", &directory)?;
        inspect_database_paths(&self.files)?;
        let (project_id, metadata_created, _) =
            metadata::provision(&self.files, self.paths.root(), now)?;
        self.files.check_directory(".ken", &directory)?;
        let mut store = ProjectStore::open(&self.paths)?;
        self.files.check_directory(".ken", &directory)?;
        store.initialize()?;
        store.database().set_meta("project_id", &project_id)?;
        store
            .database()
            .set_meta("ken_version", env!("CARGO_PKG_VERSION"))?;
        let default = self.config.default_model()?;
        let selected = configure_project(
            store.database().connection(),
            &ModelPolicy::new(default.as_deref()),
            self.environment_model.as_deref(),
        )?;
        let gitignore_changed = metadata::gitignore(&self.files)?;
        let host =
            HostInstaller::new(self.paths.root(), self.native.clone(), self.bundles.clone())?;
        let plan = host.plan_install(&options.hosts)?;
        // Both owners use the same project lock; release before the host plan takes it.
        drop(guard);
        let hosts = plan.apply()?;
        let _guard = self.files.lock()?;
        self.files.check_directory(".ken", &directory)?;
        inspect_database_paths(&self.files)?;
        let (eager, rest) = indexing::partition(indexing::sources(&self.paths)?, options);
        let encoder = if eager.is_empty() {
            None
        } else {
            Some(provider(store.database().connection(), &selected.model)?)
        };
        let mut warnings = Vec::new();
        let index = indexing::index(
            &mut store,
            &self.paths,
            self.catalog.clone(),
            &eager,
            &rest,
            encoder.as_ref().map(Encoder::get),
            &selected.model,
            now,
            &mut warnings,
        )?;
        self.files.check_directory(".ken", &directory)?;
        indexing::migrate(
            &mut store,
            &selected.model,
            encoder.as_ref().map(Encoder::get),
            &mut warnings,
        );
        self.files.check_directory(".ken", &directory)?;
        Ok(InstallReport {
            project_root: self.paths.root().into(),
            project_id,
            db_path: self.paths.db(),
            files_indexed: index.parsed,
            symbols: index.symbols,
            elapsed_s: index.elapsed_s,
            index,
            model: selected.model,
            metadata_created,
            gitignore_changed,
            embedding_files: eager.len(),
            hosts,
            warnings,
        })
    }
    pub fn uninstall(
        &self,
        options: &UninstallOptions,
        daemon: &dyn DaemonLifecycle,
    ) -> Result<UninstallReport> {
        uninstall(self.paths.root(), self.native.clone(), options, daemon)
    }
}
/// Uninstall needs no grammar/model/resource manifest or encoder factory.
pub fn uninstall(
    root: &Path,
    native: NativeCommand,
    options: &UninstallOptions,
    daemon: &dyn DaemonLifecycle,
) -> Result<UninstallReport> {
    let files = ProjectFiles::new(root)?;
    let guard = files.lock()?;
    let directory = files
        .directory_handle(".ken", false)?
        .ok_or_else(|| Error::Invalid(format!("no .ken project at {}", files.path.display())))?;
    let before = files
        .read(".ken/meta.json")?
        .ok_or_else(|| Error::Invalid(format!("no .ken project at {}", files.path.display())))?;
    metadata::validate(&serde_json::from_slice(&before)?)?;
    daemon.stop_existing(&files.path)?;
    files.check_directory(".ken", &directory)?;
    let host = HostInstaller::new(&files.path, native, Bundles::new())?;
    let plan = host.plan_uninstall()?;
    drop(guard);
    let hosts = plan.apply()?;
    let _guard = files.lock()?;
    files.check_directory(".ken", &directory)?;
    if files.read(".ken/meta.json")?.as_deref() != Some(before.as_slice()) {
        return Err(Error::Invalid(
            "project metadata changed during uninstall".into(),
        ));
    }
    if !options.keep_db {
        files.remove_tree(".ken", &directory)?;
    }
    Ok(UninstallReport {
        project_root: files.path.clone(),
        removed_project_data: !options.keep_db,
        hosts,
    })
}
