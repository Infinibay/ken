//! Public evidence search composes the prepared profile and verified source view.
use super::CompatibilityModels;
use ken_core::project::ProjectPaths;
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, ModelCatalog, RetrievalProfile};
use ken_retrieval::{
    Result, RetrievalError, candidates, compact,
    embedding_store::retrieval_snapshot,
    evidence::{EvidenceOptions, complete_evidence, refine_evidence},
    presentation::{SearchResponse, present},
    projections::stored_profile,
    query::SearchRequest,
    query_encoder::{QueryEncoder, QueryEncoders},
    ranking::{RelevanceJudge, rank_candidates},
    source_snapshot::SourceAuthority,
    storage::load_passage_map,
};
use ken_text::PythonText;
use rusqlite::Connection;
use serde::Serialize;
use std::rc::Rc;

#[derive(Debug, Serialize)]
pub struct IndexRequirement {
    ok: bool,
    code: &'static str,
    error: String,
    next_action: &'static str,
    results: [(); 0],
}
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum EvidenceResponse {
    Matches(SearchResponse),
    IndexRequired(IndexRequirement),
}
impl EvidenceResponse {
    fn required(error: impl ToString) -> Self {
        Self::IndexRequired(IndexRequirement {
            ok: false,
            code: "retrieval_index_required",
            error: error.to_string(),
            next_action: "Run ken retrieval index --path PROJECT --profile PROFILE.json, then retry.",
            results: [],
        })
    }
    pub fn is_success(&self) -> bool {
        matches!(self, Self::Matches(_))
    }
    pub fn render(&self, diagnostics: bool) -> String {
        match self {
            Self::Matches(response) => compact::render(response, diagnostics),
            Self::IndexRequired(required) => {
                format!("{}\n{}", required.error, required.next_action)
            }
        }
    }
}
fn active_profile(conn: &Connection) -> Result<RetrievalProfile> {
    match stored_profile(conn)?.profile {
        Some(profile) => RetrievalProfile::from_json(&profile).map_err(|error| {
            RetrievalError::Version(format!(
                "stored retrieval profile needs reindexing: {error}"
            ))
        }),
        None => {
            let spec = ModelCatalog::built_in()?.static_spec();
            Ok(RetrievalProfile::from_json(
                &serde_json::json!({"identity":spec,"behavior":spec}).to_string(),
            )?)
        }
    }
}
fn source_requirement(conn: &Connection) -> Result<()> {
    if load_passage_map(conn, None)?.is_empty() {
        return Err(RetrievalError::Version(
            "no source passages; reindex the project".into(),
        ));
    }
    Ok(())
}
pub(super) fn requirement(conn: &Connection) -> Result<Option<EvidenceResponse>> {
    let checked = (|| {
        active_profile(conn)?;
        source_requirement(conn)
    })();
    match checked {
        Ok(()) => Ok(None),
        Err(error @ RetrievalError::Version(_)) => Ok(Some(EvidenceResponse::required(error))),
        Err(error) => Err(error),
    }
}
struct ProfileQuery {
    models: Rc<dyn CompatibilityModels>,
    spec: EncoderSpec,
    legacy: LegacyRuntimeIdentity,
}
impl QueryEncoder for ProfileQuery {
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        self.models.profile_query(&self.spec, &self.legacy, text)
    }
}
fn query_encoders(
    models: Rc<dyn CompatibilityModels>,
    profile: &RetrievalProfile,
    legacy: &LegacyRuntimeIdentity,
) -> QueryEncoders {
    let identity: Rc<dyn QueryEncoder> = Rc::new(ProfileQuery {
        models: models.clone(),
        spec: profile.identity.clone(),
        legacy: legacy.clone(),
    });
    let behavior = if profile.behavior == profile.identity {
        identity.clone()
    } else {
        Rc::new(ProfileQuery {
            models,
            spec: profile.behavior.clone(),
            legacy: legacy.clone(),
        })
    };
    QueryEncoders { identity, behavior }
}
pub(super) fn search(
    models: Rc<dyn CompatibilityModels>,
    legacy: &LegacyRuntimeIdentity,
    conn: &Connection,
    paths: &ProjectPaths,
    request: &SearchRequest,
) -> Result<EvidenceResponse> {
    request.validate()?;
    if !matches!(request.target(), "file" | "symbol") || request.piece_kind().is_some() {
        return Err(RetrievalError::Invalid(
            "evidence responses require scope=files or symbols".into(),
        ));
    }
    let outcome = (|| {
        let profile = active_profile(conn)?;
        source_requirement(conn)?;
        let source = SourceAuthority::new(paths)
            .map_err(|error| RetrievalError::Invalid(error.to_string()))?;
        let encoders = query_encoders(models.clone(), &profile, legacy);
        let fingerprint = profile.fingerprint(legacy)?;
        let mut judge: Option<Rc<dyn RelevanceJudge>> = None;
        let mut last = None;
        for _ in 0..2 {
            let snapshot = retrieval_snapshot(conn)?;
            let proposed = if profile.contextual.is_some() {
                // Public find supplies no contextual runtime/query preparer. The
                // native owner still grants its original exact-identity bypass.
                candidates::retrieve_contextual(
                    conn, request, &profile, legacy, &encoders, None, None,
                )?
                .0
            } else {
                candidates::retrieve(conn, request, &profile, legacy, &encoders)?
            };
            let exact =
                proposed.len() == 1 && proposed[0].signals.get("exact").is_some_and(|v| *v != 0.);
            let mut matches = if profile.evidence.is_some() && !exact {
                return Err(RetrievalError::Invalid(
                    "evidence ranking profile requires its pinned owner ranker".into(),
                ));
            } else if let Some(ordering) = profile.joint.as_ref().filter(|_| !exact) {
                if judge.is_none() {
                    judge = Some(models.joint_judge(&ordering.model, legacy)?);
                }
                let judge = judge.as_ref().expect("prepared joint judge");
                let bounded = |n| isize::try_from(n).unwrap_or(isize::MAX);
                let matches = rank_candidates(
                    request,
                    &proposed,
                    Some(judge.as_ref()),
                    bounded(ordering.candidate_limit),
                    &ordering.rank_unit,
                )?;
                if ordering.evidence_results != 0 {
                    refine_evidence(
                        &matches,
                        &source,
                        request,
                        judge.as_ref(),
                        &EvidenceOptions {
                            limit: bounded(ordering.evidence_results),
                            max_windows: bounded(ordering.max_windows),
                            max_fragments: bounded(ordering.max_fragments),
                        },
                    )?
                } else {
                    matches
                }
            } else {
                rank_candidates(request, &proposed, None, 100, "passage")?
            };
            if profile
                .evidence
                .as_ref()
                .is_some_and(|p| p.evidence_version == 3)
            {
                matches = complete_evidence(&matches, &source, request)?;
            }
            snapshot.finish()?;
            let response = present(&matches, &source, request, &fingerprint)
                .map_err(|error| RetrievalError::Invalid(error.to_string()))?;
            let stale = response.results.iter().any(|result| result.source().stale);
            last = Some(response);
            if !stale {
                break;
            }
        }
        Ok(EvidenceResponse::Matches(
            last.expect("two presentation attempts"),
        ))
    })();
    match outcome {
        Err(error @ RetrievalError::Version(_)) => Ok(EvidenceResponse::required(error)),
        other => other,
    }
}
