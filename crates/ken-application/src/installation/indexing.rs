//! Select an eager subset; native indexing and storage own all source/vector work.
use super::{InstallOptions, Result};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_walk::ProjectSources,
};
use ken_index::{DocumentEncoder, IndexOptions, IndexStats, Indexer, Progress};
use ken_store::{ProjectStore, VectorSpace};
use ken_syntax::{GrammarCatalog, ParserRegistry};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    sync::Arc,
};
const CODE: &[&str] = &["py", "rs", "js", "jsx", "ts", "tsx", "go", "java", "c", "h"];
const LOW: &[&str] = &[
    ".github",
    "docs",
    "doc",
    "documentation",
    "examples",
    "fixtures",
    "samples",
    "test",
    "tests",
    "tools",
    "vendor",
];
fn key(path: &Path) -> (u8, u8, usize, String) {
    let suffix = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_lowercase();
    let low = path
        .components()
        .any(|part| LOW.contains(&part.as_os_str().to_string_lossy().to_lowercase().as_str()));
    (
        u8::from(!CODE.contains(&suffix.as_str())),
        u8::from(low),
        path.components().count(),
        path.to_string_lossy().replace('\\', "/"),
    )
}
pub(super) fn sources(paths: &ProjectPaths) -> Result<Vec<PathBuf>> {
    let context = DiscoveryContext {
        cwd: paths.root().into(),
        forced_root: None,
        home: None,
    };
    let mut files = Vec::new();
    for entry in ProjectSources::new(paths.clone(), context).walk(Path::new("."))? {
        let entry = entry?;
        if !entry.is_dir {
            files.push(entry.path);
        }
    }
    files.sort();
    Ok(files)
}
pub(super) fn partition(
    files: Vec<PathBuf>,
    options: &InstallOptions,
) -> (Vec<PathBuf>, Vec<PathBuf>) {
    if !options.embed {
        return (vec![], files);
    }
    let limit = options
        .embed_limit
        .map(|n| n as usize)
        .unwrap_or(files.len());
    if limit >= files.len() {
        return (files, vec![]);
    }
    let mut priority = files.clone();
    priority.sort_by_key(|path| key(path));
    priority.truncate(limit);
    let selected = priority.iter().cloned().collect::<BTreeSet<_>>();
    let rest = files
        .into_iter()
        .filter(|path| !selected.contains(path))
        .collect();
    (priority, rest)
}
struct Events<'a>(&'a mut Vec<String>);
impl Progress for Events<'_> {
    fn file(&mut self, _: &str, _: &str) {}
    fn warning(&mut self, message: &str) {
        self.0.push(message.into());
    }
}
fn add(total: &mut IndexStats, other: IndexStats) {
    total.visited += other.visited;
    total.parsed += other.parsed;
    total.unchanged += other.unchanged;
    total.skipped_no_lang += other.skipped_no_lang;
    total.skipped_too_large += other.skipped_too_large;
    total.skipped_io_error += other.skipped_io_error;
    total.symbols += other.symbols;
    total.imports += other.imports;
    total.elapsed_s += other.elapsed_s;
}
// Keep the operation-owned collaborators and eager/rest ordering explicit.
#[allow(clippy::too_many_arguments)]
pub(super) fn index(
    store: &mut ProjectStore,
    paths: &ProjectPaths,
    catalog: Arc<GrammarCatalog>,
    eager: &[PathBuf],
    rest: &[PathBuf],
    encoder: Option<&dyn DocumentEncoder>,
    model: &str,
    now: i64,
    warnings: &mut Vec<String>,
) -> Result<IndexStats> {
    let parsers = ParserRegistry::with_shared_catalog(catalog);
    let indexer = Indexer::new(&parsers);
    let clock = || now;
    let mut total = IndexStats::default();
    let mut events = Events(warnings);
    // Install's optional legacy eager encoding does not instantiate best-search
    // profile roles. Its source passages still use the canonical native policy.
    let mut options = IndexOptions {
        legacy_encoder: encoder,
        legacy_model: Some(model),
        retrieval_policy: Some(ken_retrieval::PassagePolicy::default()),
        now_ms: Some(&clock),
        ..Default::default()
    };
    if !eager.is_empty() {
        add(
            &mut total,
            indexer.index_files(store.database_mut(), paths, eager, &options, &mut events)?,
        );
    }
    options.legacy_encoder = None;
    if !rest.is_empty() {
        add(
            &mut total,
            indexer.index_files(store.database_mut(), paths, rest, &options, &mut events)?,
        );
    }
    Ok(total)
}
pub(super) fn migrate(
    store: &mut ProjectStore,
    model: &str,
    encoder: Option<&dyn DocumentEncoder>,
    warnings: &mut Vec<String>,
) {
    let result = (|| -> Result<()> {
        let mut pending = 0i64;
        for space in VectorSpace::ALL {
            pending += store.database().connection().query_row(
                &format!(
                    "SELECT count(*) FROM {space} WHERE embedding IS NOT NULL AND vec_slot IS NULL"
                ),
                [],
                |row| row.get::<_, i64>(0),
            )?;
        }
        if pending == 0 {
            return Ok(());
        }
        let dim = match encoder {
            Some(encoder) => Some(encoder.dim()?),
            None => ken_models::ModelCatalog::built_in()?
                .models()
                .into_iter()
                .find(|entry| entry.model == model)
                .and_then(|entry| entry.dim),
        };
        let Some(dim) = dim else {
            warnings.push("Inline vectors remain readable; their model dimension is unavailable for optional vector migration.".into());
            return Ok(());
        };
        let moved = ken_store::migrate_inline(store, dim, Some(model), 2000, |_| {})?;
        if moved.values().any(|count| *count > 0)
            && let Err(error) = ken_store::reclaim_database(store.database_mut())
        {
            warnings.push(format!(
                "Vector migration succeeded; optional database reclamation failed: {error}"
            ));
        }
        Ok(())
    })();
    if let Err(error) = result {
        warnings.push(format!(
            "Optional vector migration skipped; inline embeddings remain readable: {error}"
        ));
    }
}
