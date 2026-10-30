//! Explicit source/profile preparation; all indexing and model policy is delegated.
use crate::{Error, Result};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_walk::ProjectSources,
};
use ken_models::{LegacyRuntimeIdentity, ModelCatalog, RetrievalProfile};
use ken_retrieval::encoder::EncoderLoader;
use ken_store::ProjectStore;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
    time::Instant,
};
pub struct RetrievalApplication {
    grammars: Arc<GrammarCatalog>,
}
fn project(root: &Path) -> Result<(ProjectPaths, ProjectStore, Vec<PathBuf>)> {
    let paths = crate::paths(root)?;
    if !paths.root().is_dir() {
        return Err(Error::Invalid(format!(
            "project directory does not exist: {}",
            paths.root().display()
        )));
    }
    let mut store = ProjectStore::open(&paths)?;
    store.initialize()?;
    let source = ProjectSources::new(
        paths.clone(),
        DiscoveryContext {
            cwd: paths.root().into(),
            forced_root: None,
            home: None,
        },
    );
    let mut files = Vec::new();
    for entry in source.walk(Path::new("."))? {
        let entry = entry?;
        if !entry.is_dir {
            files.push(entry.path);
        }
    }
    Ok((paths, store, files))
}
fn meta(paths: &ProjectPaths) -> Result<()> {
    match std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(paths.meta())
    {
        Ok(mut file) => {
            file.write_all(b"{}")?;
            file.sync_all()?;
            std::fs::File::open(paths.meta().parent().expect("meta parent"))?.sync_all()?;
            Ok(())
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(()),
        Err(error) => Err(error.into()),
    }
}
impl RetrievalApplication {
    pub fn new(grammars: Arc<GrammarCatalog>) -> Self {
        Self { grammars }
    }
    pub fn index(
        &self,
        root: &Path,
        profile: Option<RetrievalProfile>,
        legacy: LegacyRuntimeIdentity,
        loader: Rc<dyn EncoderLoader>,
    ) -> Result<Value> {
        let (paths, mut store, files) = project(root)?;
        let started = Instant::now();
        let profile = match profile {
            Some(profile) => profile,
            None => {
                match ken_retrieval::projections::stored_profile(store.database().connection())?
                    .profile
                {
                    Some(raw) => RetrievalProfile::from_json_with_upgrade(&raw, true)?,
                    None => {
                        let spec = ModelCatalog::built_in()?.static_spec();
                        RetrievalProfile::from_json(
                            &json!({"identity":spec,"behavior":spec}).to_string(),
                        )?
                    }
                }
            }
        };
        let fingerprint = profile.fingerprint(&legacy)?;
        let parsers = ParserRegistry::with_shared_catalog(self.grammars.clone());
        let stats = ken_index::Indexer::new(&parsers).index_files(
            store.database_mut(),
            &paths,
            &files,
            &ken_index::IndexOptions {
                retrieval_profile: Some(profile.clone()),
                retrieval_loader: Some(loader.clone()),
                legacy_runtime: Some(legacy.clone()),
                ..Default::default()
            },
            &mut |_: &str, _: &str| {},
        )?;
        ken_retrieval::projections::index_embeddings(
            store.database_mut(),
            profile.clone(),
            legacy,
            loader,
        )?;
        let passages: i64 = store.database().connection().query_row(
            "SELECT COUNT(*) FROM ci_passages",
            [],
            |r| r.get(0),
        )?;
        meta(&paths)?;
        Ok(
            json!({"profile_version":fingerprint,"profile":serde_json::from_str::<Value>(&profile.to_json()?)?,"source":{"visited":stats.visited,"parsed":stats.parsed,"unchanged":stats.unchanged,"skipped_no_lang":stats.skipped_no_lang,"skipped_too_large":stats.skipped_too_large,"skipped_io_error":stats.skipped_io_error,"symbols":stats.symbols,"imports":stats.imports,"elapsed_s":stats.elapsed_s},"passages":passages,"elapsed_ms":started.elapsed().as_secs_f64()*1000.}),
        )
    }
    pub fn prepare(&self, root: &Path, best: &mut ken_search::BestSearch) -> Result<Value> {
        let (paths, mut store, files) = project(root)?;
        let parsers = ParserRegistry::with_shared_catalog(self.grammars.clone());
        ken_index::Indexer::new(&parsers).index_files(
            store.database_mut(),
            &paths,
            &files,
            &ken_index::IndexOptions {
                retrieval_policy: Some(ken_retrieval::PassagePolicy::default()),
                ..Default::default()
            },
            &mut |_: &str, _: &str| {},
        )?;
        let report = best.prepare(store.database_mut(), &paths)?;
        meta(&paths)?;
        Ok(serde_json::to_value(report)?)
    }
}
