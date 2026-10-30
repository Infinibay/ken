//! Current-documentation hypotheses with optional native structural observations.
//! Retrieval/scoring/current-source and presentation policy stay in responsibility.
use crate::knowledge::EmbeddingResources;
use ken_responsibility::{
    self as domain, CurrentSources, LiveScores, NativeSources, NativeVectors, RankedRows,
    ResponsibilityVectors, Result, WhoOutput, WhoReport, WhoRequest,
};
use ken_syntax::GrammarCatalog;
use rusqlite::Connection;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
};
#[derive(Clone, Debug)]
pub struct WhoOptions {
    pub full: bool,
    pub verify: bool,
    pub timeout_ms: f64,
}
impl Default for WhoOptions {
    fn default() -> Self {
        Self {
            full: false,
            verify: true,
            timeout_ms: 3000.,
        }
    }
}
pub trait Verification {
    fn enrich(&mut self, root: &Path, report: &mut WhoReport, timeout_ms: f64) -> Result<()>;
}
pub struct NativeVerification {
    catalog: Arc<GrammarCatalog>,
    packaged: BTreeMap<String, String>,
}
impl NativeVerification {
    pub fn new(catalog: Arc<GrammarCatalog>, packaged: BTreeMap<String, String>) -> Self {
        Self { catalog, packaged }
    }
}
impl Verification for NativeVerification {
    fn enrich(&mut self, root: &Path, report: &mut WhoReport, timeout_ms: f64) -> Result<()> {
        domain::structure::enrich_native(
            root,
            report,
            timeout_ms,
            self.catalog.clone(),
            self.packaged.clone(),
        )
    }
}
#[allow(clippy::too_many_arguments)]
pub fn who_with(
    conn: &Connection,
    root: &Path,
    request: &WhoRequest,
    options: &WhoOptions,
    vectors: &mut dyn ResponsibilityVectors,
    sources: &mut dyn CurrentSources,
    verification: &mut dyn Verification,
) -> Result<WhoOutput> {
    let mut report = domain::who_with(
        conn,
        root,
        request,
        vectors,
        sources,
        &domain::default_reasoners(),
    )?;
    if options.verify {
        verification.enrich(root, &mut report, options.timeout_ms)?;
    }
    // Retain PythonText in extractive evidence/snippets until the final serializer.
    Ok(domain::report::render(&report, options.full))
}
pub struct WhoApplication {
    root: PathBuf,
    resources: EmbeddingResources,
    catalog: Arc<GrammarCatalog>,
    packaged: BTreeMap<String, String>,
}
impl WhoApplication {
    pub fn new(
        root: &Path,
        resources: EmbeddingResources,
        catalog: Arc<GrammarCatalog>,
        packaged: BTreeMap<String, String>,
    ) -> Result<Self> {
        let root = root.canonicalize()?;
        if !root.is_dir() {
            return Err(domain::Error::Invalid(
                "responsibility project root must be a directory".into(),
            ));
        }
        Ok(Self {
            root,
            resources,
            catalog,
            packaged,
        })
    }
    pub fn who(
        &self,
        conn: &Connection,
        request: &WhoRequest,
        options: &WhoOptions,
    ) -> Result<WhoOutput> {
        let mut vectors = DeferredVectors {
            conn,
            resources: &self.resources,
            native: None,
        };
        let mut sources = NativeSources::new(&self.root, self.catalog.clone())?;
        let mut verification = NativeVerification::new(self.catalog.clone(), self.packaged.clone());
        who_with(
            conn,
            &self.root,
            request,
            options,
            &mut vectors,
            &mut sources,
            &mut verification,
        )
    }
}
/// Selection/pinning is part of the first vector operation, after domain input
/// admission; construction never loads an encoder or inspects model resources.
struct DeferredVectors<'a> {
    conn: &'a Connection,
    resources: &'a EmbeddingResources,
    native: Option<NativeVectors>,
}
impl DeferredVectors<'_> {
    fn owner(&mut self) -> Result<&mut NativeVectors> {
        if self.native.is_none() {
            self.native = Some(NativeVectors::new(self.resources.project(self.conn)?)?);
        }
        Ok(self
            .native
            .as_mut()
            .expect("retained focused native vector owner"))
    }
}
impl ResponsibilityVectors for DeferredVectors<'_> {
    fn embed_query(&mut self, text: &str) -> Result<Vec<f32>> {
        self.owner()?.embed_query(text)
    }
    fn embed_passages(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        self.owner()?.embed_passages(texts)
    }
    fn live_scores(
        &mut self,
        conn: &Connection,
        root: &Path,
        query: &[f32],
    ) -> Result<Option<LiveScores>> {
        self.owner()?.live_scores(conn, root, query)
    }
    fn rank_against(&mut self, query: &[f32], blobs: &[Vec<u8>]) -> Result<RankedRows> {
        self.owner()?.rank_against(query, blobs)
    }
    fn cosine(
        &mut self,
        query: &[f32],
        flat: &[f32],
        rows: usize,
        width: usize,
    ) -> Result<Vec<f32>> {
        self.owner()?.cosine(query, flat, rows, width)
    }
}
