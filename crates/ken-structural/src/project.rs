//! Coordinate manifest acquisition, reusable lowering and complete project linking.
use crate::{BuildError, Result, ScanLimits, Skipped, SourceManifest};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_program::{IR_VERSION, StructuralIr, project::link_project_owned_with_check};
use ken_store::artifact_cache::{ArtifactCache, CacheStats};
use ken_syntax::{GrammarCatalog, Language, structural::lower_source};
use serde::Serialize;
use std::{collections::BTreeSet, path::Path, time::Instant};
/// The revision must change whenever lowering semantics change. Failed lowering
/// is an explicit omitted file, never a successful empty source unit.
pub trait Frontend {
    fn revision(&self) -> &str;
    fn lower(
        &self,
        bytes: &[u8],
        language: Language,
        path: &str,
    ) -> std::result::Result<StructuralIr, String>;
}
pub struct NativeFrontend<'a> {
    catalog: &'a GrammarCatalog,
    revision: String,
}
impl<'a> NativeFrontend<'a> {
    pub fn new(catalog: &'a GrammarCatalog) -> Self {
        Self {
            catalog,
            revision: format!(
                "native-structural/1:{}:{}:{}",
                crate::IMPLEMENTATION_FINGERPRINT,
                std::env::consts::OS,
                std::env::consts::ARCH
            ),
        }
    }
}
impl Frontend for NativeFrontend<'_> {
    fn revision(&self) -> &str {
        &self.revision
    }
    fn lower(
        &self,
        bytes: &[u8],
        language: Language,
        path: &str,
    ) -> std::result::Result<StructuralIr, String> {
        lower_source(self.catalog, language, bytes, path).map_err(|e| e.to_string())
    }
}
#[derive(Debug, Serialize)]
pub struct ResolutionCounts {
    pub resolved_calls: usize,
    pub unresolved_calls: usize,
}
#[derive(Debug, Serialize)]
pub struct BuildAnalysis {
    pub resolution: ResolutionCounts,
    pub files: Vec<String>,
    pub skipped: Vec<Skipped>,
    pub coverage_complete: bool,
    pub diagnostics: Vec<String>,
    pub cache: CacheStats,
    pub graph_key: String,
    pub elapsed_ms: f64,
}
pub struct BuildReport {
    pub graph: StructuralIr,
    pub analysis: BuildAnalysis,
}
pub struct ProjectBuilder<'a> {
    paths: ProjectPaths,
    context: DiscoveryContext,
    frontend: &'a dyn Frontend,
    cache: ArtifactCache,
}
impl<'a> ProjectBuilder<'a> {
    pub fn new(
        paths: ProjectPaths,
        context: DiscoveryContext,
        frontend: &'a dyn Frontend,
        cache: ArtifactCache,
    ) -> Self {
        Self {
            paths,
            context,
            frontend,
            cache,
        }
    }
    pub fn manifest(
        &self,
        path: &Path,
        limits: ScanLimits,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<SourceManifest> {
        SourceManifest::capture(
            &self.paths,
            &self.context,
            path,
            self.frontend.revision(),
            limits,
            &mut check,
        )
    }
    pub fn build(
        &mut self,
        path: &Path,
        limits: ScanLimits,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<BuildReport> {
        let start = Instant::now();
        let manifest = self.manifest(path, limits, &mut check)?;
        self.assemble(manifest, start, &mut check)
    }
    /// Reuse a captured manifest without re-reading a changing worktree.
    pub fn build_manifest(
        &mut self,
        manifest: SourceManifest,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<BuildReport> {
        self.assemble(manifest, Instant::now(), &mut check)
    }
    fn assemble(
        &mut self,
        manifest: SourceManifest,
        start: Instant,
        check: &mut impl FnMut() -> Result<()>,
    ) -> Result<BuildReport> {
        check()?;
        if manifest.root != self.paths.root() || manifest.revision != self.frontend.revision() {
            return Err(BuildError::Invalid(
                "manifest belongs to a different root or frontend revision",
            ));
        }
        self.cache.reset_stats();
        let graph_key = manifest.graph_key.clone();
        let mut skipped = manifest.skipped;
        let mut files = manifest
            .entries
            .iter()
            .map(|e| e.path().to_string())
            .collect::<Vec<_>>();
        let graph = if let Some(graph) = self.cache.get_ir_checked(&graph_key, |ir| {
            ir.path == "<project>" && ir.language == "mixed" && ir.view == "source"
        }) {
            graph
        } else {
            let mut units = vec![];
            let mut failed = BTreeSet::new();
            for source in manifest.entries {
                check()?;
                let unit = if let Some(unit) = self.cache.get_ir_checked(source.key(), |ir| {
                    ir.path == source.path()
                        && ir.language == source.language().as_str()
                        && ir.view == "source"
                }) {
                    unit
                } else {
                    match self
                        .frontend
                        .lower(source.content(), source.language(), source.path())
                    {
                        Ok(unit)
                            if unit.path == source.path()
                                && unit.language == source.language().as_str()
                                && unit.version == IR_VERSION
                                && unit.view == "source" =>
                        {
                            self.cache.put_ir(source.key(), &unit);
                            unit
                        }
                        Ok(_) => {
                            failed.insert(source.path().to_string());
                            skipped.push(Skipped {
                                path: source.path().into(),
                                reason: "frontend error: mismatched unit identity".into(),
                            });
                            continue;
                        }
                        Err(error) => {
                            failed.insert(source.path().to_string());
                            skipped.push(Skipped {
                                path: source.path().into(),
                                reason: format!("frontend error: {error}"),
                            });
                            continue;
                        }
                    }
                };
                units.push(unit);
            }
            let mut cancelled = None;
            let linked = link_project_owned_with_check(units, || match check() {
                Ok(()) => Ok(()),
                Err(e) => {
                    cancelled = Some(e);
                    Err(ken_program::ProgramError::Invalid(
                        "project build cancelled",
                    ))
                }
            });
            if let Some(error) = cancelled {
                return Err(error);
            }
            let graph = linked?;
            check()?;
            if failed.is_empty() {
                self.cache.put_ir(&graph_key, &graph);
            }
            files.retain(|p| !failed.contains(p));
            graph
        };
        check()?; // Includes acquisition/decompression on a warm graph hit.
        let resolved = graph
            .facts
            .iter()
            .filter(|f| matches!(f.relation.as_str(), "TARGET" | "ALLOCATES_TYPE"))
            .map(|f| f.subject.as_str())
            .collect::<BTreeSet<_>>();
        let unresolved = graph
            .facts
            .iter()
            .filter(|f| f.relation == "HAS_CALL" && !resolved.contains(f.object.as_str()))
            .map(|f| f.object.as_str())
            .collect::<BTreeSet<_>>();
        let analysis = BuildAnalysis {
            resolution: ResolutionCounts {
                resolved_calls: resolved.len(),
                unresolved_calls: unresolved.len(),
            },
            files,
            coverage_complete: skipped.is_empty() && graph.diagnostics.is_empty(),
            skipped,
            diagnostics: graph.diagnostics.clone(),
            cache: self.cache.stats(),
            graph_key,
            elapsed_ms: (start.elapsed().as_secs_f64() * 1_000_000.).round() / 1000.,
        };
        check()?;
        Ok(BuildReport { graph, analysis })
    }
}
