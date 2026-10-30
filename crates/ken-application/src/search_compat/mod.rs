//! Explicit historical search views over their native algorithm owners.
mod evidence;
mod legacy;

pub use evidence::{EvidenceResponse, IndexRequirement};
use ken_core::project::ProjectPaths;
use ken_models::{EncoderSpec, LegacyRuntimeIdentity};
use ken_retrieval::{Result, query::SearchRequest, ranking::RelevanceJudge};
use ken_text::PythonText;
pub use legacy::{LegacyFileHit, LegacyResponse, LegacySymbolHit, OutlineSymbol};
use rusqlite::Connection;
use std::{path::Path, rc::Rc};

/// Resolve only the model selected by the operation that actually needs it.
/// Profile encoders and joint judges must honor their complete pinned spec.
pub trait CompatibilityModels {
    fn legacy_query(&self, conn: &Connection, query: &PythonText) -> Result<Vec<f32>>;
    fn profile_query(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
        query: &PythonText,
    ) -> Result<Vec<f32>>;
    fn joint_judge(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<Rc<dyn RelevanceJudge>>;
}

/// Compose the requested compatibility policy without constructing BestSearch.
pub struct SearchCompatibility {
    models: Rc<dyn CompatibilityModels>,
    legacy: LegacyRuntimeIdentity,
}
impl SearchCompatibility {
    pub fn new(models: Rc<dyn CompatibilityModels>, legacy: LegacyRuntimeIdentity) -> Self {
        Self { models, legacy }
    }
    pub fn legacy(
        &self,
        conn: &Connection,
        project_root: Option<&Path>,
        query: &PythonText,
        scope: &str,
        limit: isize,
    ) -> Result<LegacyResponse> {
        legacy::search(
            self.models.as_ref(),
            conn,
            project_root,
            query,
            scope,
            limit,
        )
    }
    /// Local preparation can be checked before opening an installation or model.
    pub fn evidence_requirement(conn: &Connection) -> Result<Option<EvidenceResponse>> {
        evidence::requirement(conn)
    }
    pub fn evidence(
        &self,
        conn: &Connection,
        paths: &ProjectPaths,
        request: &SearchRequest,
    ) -> Result<EvidenceResponse> {
        evidence::search(self.models.clone(), &self.legacy, conn, paths, request)
    }
}
