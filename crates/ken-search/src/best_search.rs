//! Serialize source preparation and retain only generation-bound project state.
use crate::{Result, SearchResourceProvider, SearchResources};
use ken_core::project::ProjectPaths;
use ken_index::{IndexOptions, Indexer};
use ken_retrieval::{
    PassagePolicy,
    candidates::{exact_candidates, owner_passages},
    embedding_store::retrieval_snapshot,
    intent::requested_piece_kind,
    piece_cards::build_piece_cards,
    presentation::{SearchResponse, present, present_cards},
    query::SearchRequest,
    ranking::rank_candidates,
    source_catalog::{SourceCatalog, symbol_entity_kind},
    source_snapshot::SourceAuthority,
};
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use rusqlite::Connection;
use std::{path::PathBuf, rc::Rc, sync::Arc};
pub struct BestSearch {
    grammars: Arc<GrammarCatalog>,
    provider: Rc<dyn SearchResourceProvider>,
    resources: Option<Rc<SearchResources>>,
    projects: std::collections::VecDeque<PreparedProject>,
}
fn files(conn: &Connection) -> Result<Vec<PathBuf>> {
    Ok(conn
        .prepare("SELECT path FROM ci_files ORDER BY path")?
        .query_map([], |r| r.get::<_, String>(0).map(PathBuf::from))?
        .collect::<rusqlite::Result<_>>()?)
}
fn quiet(_: &str, _: &str) {}
impl BestSearch {
    pub fn new(grammars: Arc<GrammarCatalog>, provider: Rc<dyn SearchResourceProvider>) -> Self {
        Self {
            grammars,
            provider,
            resources: None,
            projects: Default::default(),
        }
    }
    pub fn search(
        &mut self,
        db: &mut ProjectDatabase,
        paths: &ProjectPaths,
        request: &SearchRequest,
    ) -> Result<SearchResponse> {
        if !db
            .connection()
            .query_row("SELECT EXISTS(SELECT 1 FROM ci_passages)", [], |r| {
                r.get::<_, bool>(0)
            })?
        {
            let files = files(db.connection())?;
            if !files.is_empty() {
                let parsers = ParserRegistry::with_shared_catalog(self.grammars.clone());
                Indexer::new(&parsers).index_files(
                    db,
                    paths,
                    &files,
                    &IndexOptions {
                        retrieval_policy: Some(PassagePolicy::default()),
                        ..Default::default()
                    },
                    &mut quiet,
                )?;
            }
        }
        let snapshot = retrieval_snapshot(db.connection())?;
        let owners = owner_passages(db.connection())?;
        if owners.is_empty() {
            return Ok(SearchResponse::new(request, "best-empty-source-v1"));
        }
        let exact = exact_candidates(db.connection(), request)?;
        if exact.len() == 1 {
            let key = &exact[0].entity;
            let mut kind = requested_piece_kind(request);
            let inferred;
            let request = if request.piece_kind().is_none()
                && request.target() != "file"
                && kind == "symbol"
                && key.kind == "class"
            {
                kind = "class".into();
                inferred = request.with_piece_kind(&kind)?;
                &inferred
            } else {
                request
            };
            let matches = rank_candidates(request, &exact, None, 40, "entity")?;
            let source = Arc::new(SourceAuthority::new(paths)?);
            if kind == "symbol" && !symbol_entity_kind(&key.kind) {
                return Ok(present(&matches, &source, request, "best-exact-source-v1")?);
            }
            let catalog = SourceCatalog::new(
                source,
                owners
                    .into_iter()
                    .filter(|(k, _)| k.path == key.path)
                    .collect(),
            )?;
            let cards = build_piece_cards(&matches, &kind, request.query(), &catalog, 10)?;
            return Ok(present_cards(
                &cards,
                request,
                &catalog,
                "best-exact-source-v1",
            )?);
        }
        snapshot.finish()?;
        let resources = self.resources()?;
        self.projection(db, paths, &resources)?;
        let snapshot = retrieval_snapshot(db.connection())?;
        let response = self.with_project(
            db.connection(),
            paths,
            &resources,
            snapshot.generation,
            |project| {
                let encoders = ken_retrieval::query_encoder::QueryEncoders {
                    identity: resources.words.clone(),
                    behavior: resources.words.clone(),
                };
                let expand = |q: &ken_text::PythonText| resources.owner_ranker.prepare_query(q);
                let (candidates, expanded) = ken_retrieval::candidates::retrieve_contextual(
                    db.connection(),
                    request,
                    &resources.profile,
                    &resources.legacy,
                    &encoders,
                    Some(&project.context),
                    Some(&expand),
                )?;
                let descriptions =
                    ken_retrieval::candidates::owner_descriptions(db.connection(), &candidates)?
                        .into_iter()
                        .collect();
                let matches = resources.owner_ranker.rank(
                    request,
                    &candidates,
                    &descriptions,
                    Some(&expanded),
                    3,
                    None,
                )?;
                let exact = candidates.len() == 1
                    && candidates[0].signals.get("exact").is_some_and(|x| *x != 0.);
                Ok(project.pieces.search(
                    request,
                    &matches,
                    &expanded,
                    &resources.fingerprint,
                    exact,
                )?)
            },
        )?;
        snapshot.finish()?;
        Ok(response)
    }
}

#[derive(Clone, PartialEq, Eq, serde::Serialize)]
pub struct PreparedProjectInfo {
    pub root: PathBuf,
    pub database: String,
    pub generation: i64,
    pub profile_fingerprint: String,
    pub descriptions: usize,
}
#[derive(serde::Serialize)]
pub struct PreparationReport {
    pub indexed_files: usize,
    pub owners: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub profile_version: Option<String>,
}
impl BestSearch {
    pub fn cached_projects(&self) -> Vec<PreparedProjectInfo> {
        self.projects
            .iter()
            .map(|p| PreparedProjectInfo {
                descriptions: p.pieces.descriptions().len(),
                ..p.identity.clone()
            })
            .collect()
    }
    pub fn prepare(
        &mut self,
        db: &mut ProjectDatabase,
        paths: &ProjectPaths,
    ) -> Result<PreparationReport> {
        let indexed_files = db
            .connection()
            .query_row("SELECT COUNT(*) FROM ci_files", [], |r| r.get::<_, i64>(0))?
            as usize;
        if indexed_files == 0 {
            return Ok(PreparationReport {
                indexed_files: 0,
                owners: 0,
                profile_version: None,
            });
        }
        let resources = self.resources()?;
        self.projection(db, paths, &resources)?;
        let snapshot = retrieval_snapshot(db.connection())?;
        let owners = self.with_project(
            db.connection(),
            paths,
            &resources,
            snapshot.generation,
            |p| Ok(p.owners),
        )?;
        snapshot.finish()?;
        resources
            .owner_ranker
            .prepare_query(&"¿Dónde convierte un valor?".into())?;
        resources.neural.score(
            &"find a stored value".into(),
            &vec!["def get(key): return data[key]".into(); 10],
        )?;
        Ok(PreparationReport {
            indexed_files,
            owners,
            profile_version: Some(resources.fingerprint.clone()),
        })
    }
    fn resources(&mut self) -> Result<Rc<SearchResources>> {
        if let Some(resources) = &self.resources {
            return Ok(resources.clone());
        }
        let resources = Rc::new(self.provider.build()?);
        self.resources = Some(resources.clone());
        Ok(resources)
    }
    fn projection(
        &self,
        db: &mut ProjectDatabase,
        paths: &ProjectPaths,
        resources: &SearchResources,
    ) -> Result<()> {
        use ken_retrieval::projections::{index_embeddings, stored_profile};
        let stored = stored_profile(db.connection())?;
        let base = &resources.base_profile;
        let fingerprint = base
            .fingerprint(&resources.legacy)
            .map_err(ken_retrieval::RetrievalError::from)?;
        if stored.fingerprint.as_deref() == Some(&fingerprint)
            && stored
                .profile
                .as_ref()
                .map(|p| ken_models::RetrievalProfile::from_json(p))
                .transpose()
                .map_err(ken_retrieval::RetrievalError::from)?
                .as_ref()
                == Some(base)
            && ken_retrieval::storage::source_extractor_current(db.connection())?
        {
            return Ok(());
        }
        let files = files(db.connection())?;
        let parsers = ParserRegistry::with_shared_catalog(self.grammars.clone());
        let loader = resources.loader();
        Indexer::new(&parsers).index_files(
            db,
            paths,
            &files,
            &IndexOptions {
                retrieval_profile: Some(base.clone()),
                retrieval_loader: Some(loader.clone()),
                legacy_runtime: Some(resources.legacy.clone()),
                ..Default::default()
            },
            &mut quiet,
        )?;
        index_embeddings(db, base.clone(), resources.legacy.clone(), loader)?;
        Ok(())
    }
    fn with_project<T>(
        &mut self,
        conn: &Connection,
        paths: &ProjectPaths,
        resources: &SearchResources,
        generation: i64,
        operation: impl FnOnce(&mut PreparedProject) -> Result<T>,
    ) -> Result<T> {
        let database = conn.query_row(
            "SELECT file FROM pragma_database_list WHERE name='main'",
            [],
            |r| r.get::<_, String>(0),
        )?;
        let identity = PreparedProjectInfo {
            root: paths.root().into(),
            database,
            generation,
            profile_fingerprint: resources.fingerprint.clone(),
            descriptions: 0,
        };
        if !identity.database.is_empty()
            && let Some(i) = self.projects.iter().position(|p| p.identity == identity)
        {
            let project = self.projects.remove(i).expect("located project");
            self.projects.push_back(project);
            return operation(self.projects.back_mut().expect("retained project"));
        }
        let catalog = Arc::new(SourceCatalog::new(
            Arc::new(SourceAuthority::new(paths)?),
            owner_passages(conn)?,
        )?);
        let context = ken_retrieval::context_preparation::prepare_context(
            &catalog,
            generation,
            resources.context.clone(),
            &paths.root().join(".ken/search-context"),
        )?;
        let owners = catalog.owners().len();
        let pieces = ken_retrieval::piece_search::PieceSearch::new(
            catalog,
            resources.piece_ranker.clone(),
            resources.neural.clone(),
            self.grammars.clone(),
        );
        let mut project = PreparedProject {
            identity,
            context,
            pieces,
            owners,
        };
        // Unnamed SQLite connections have no durable database identity. Keep their
        // state only for this call instead of aliasing independent in-memory DBs.
        if project.identity.database.is_empty() {
            return operation(&mut project);
        }
        self.projects.push_back(project);
        while self.projects.len() > 2 {
            self.projects.pop_front();
        }
        operation(self.projects.back_mut().expect("published project"))
    }
}

struct PreparedProject {
    identity: PreparedProjectInfo,
    context: ken_retrieval::contextual::ContextualRetriever,
    pieces: ken_retrieval::piece_search::PieceSearch,
    owners: usize,
}
