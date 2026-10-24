use super::{Observation, ScenarioResult, fields, finish_observation, invalid, raw};
use super::{features as f, production};
use ken_models::EncoderSpec;
use ken_retrieval::{
    EntityKey, Result,
    description::OwnerDescription,
    feature_matrix::FeatureMatrix,
    numeric_ranker::NumericRanker,
    piece_candidates::PieceCandidate,
    piece_features::piece_features,
    piece_ranking::PieceReranker,
    query::{CodeMatch, SearchRequest},
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{rc::Rc, sync::Arc};
#[derive(Deserialize)]
struct Input {
    request: SearchRequest,
    pieces: Vec<RawPiece>,
    expanded: Option<PythonText>,
    model: Option<Box<RawValue>>,
    #[serde(default)]
    production: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawPiece {
    kind: String,
    path: String,
    entity: Option<EntityKey>,
    members: Vec<OwnerDescription>,
    matches: Vec<CodeMatch>,
}
impl RawPiece {
    fn materialize(self) -> Result<PieceCandidate> {
        PieceCandidate::new(
            self.kind,
            self.path,
            self.entity,
            self.members.into_iter().map(Arc::new).collect(),
            self.matches,
        )
    }
}
enum Words {
    Synthetic(f::Encoder),
    Static(Rc<production::StaticWords>),
}
impl Words {
    fn take_calls(&self) -> Vec<f::Call> {
        match self {
            Self::Synthetic(e) => e.calls.take(),
            Self::Static(e) => e.take_calls(),
        }
    }
}
impl WordEncoder for Words {
    fn spec(&self) -> &EncoderSpec {
        match self {
            Self::Synthetic(e) => e.spec(),
            Self::Static(e) => e.spec(),
        }
    }
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        match self {
            Self::Synthetic(e) => e.embed_query(text),
            Self::Static(e) => e.embed_query(text),
        }
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        match self {
            Self::Synthetic(e) => e.embed_passages(texts),
            Self::Static(e) => e.embed_passages(texts),
        }
    }
}
fn paths(model: &NumericRanker, features: &FeatureMatrix) -> Result<String> {
    let mut rows = Vec::new();
    for row in features.values.values().chunks(262) {
        let explanation = model.explain_pair(row, row)?;
        rows.push(
            explanation
                .trees
                .iter()
                .map(|t| {
                    json!([
                        format!("{:016x}", t.left_leaf.to_bits()),
                        t.left_path
                            .iter()
                            .map(|step| json!([step.feature_index, step.branch]))
                            .collect::<Vec<_>>()
                    ])
                })
                .collect::<Vec<_>>(),
        );
    }
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(&rows)?)))
}
pub fn run(text: &str, kind: &str, runtime: &production::Runtime<'_>) -> Observation {
    let mut extra = Observation::new();
    let mut observed_encoder = Vec::new();
    let mut observed_stems = Vec::new();
    let outcome = (|| -> ScenarioResult<_> {
        fields(
            text,
            &[
                "request",
                "pieces",
                "expanded",
                "model",
                "production",
                "stemmer",
                "dimensions",
                "vectors",
            ],
            &[],
        )?;
        let input: Input = serde_json::from_str(text)?;
        let mut common: f::Input = serde_json::from_str(text)?;
        if common.stemmer.is_none() {
            common.stemmer = Some("english".into());
        }
        if common.dimensions == 0
            || common.dimensions > 1024
            || common.vectors.len() > 4096
            || common.vectors.values().any(|v| v.len() > 1024)
            || input.pieces.len() > 32
        {
            return Err(invalid("piece encoding exceeds bounded dimensions").into());
        }
        let encoder = Rc::new(if input.production {
            Words::Static(runtime.words()?)
        } else {
            Words::Synthetic(f::Encoder::new(&common))
        });
        let stems = Arc::new(f::Stems::new(&common));
        let pieces = input
            .pieces
            .into_iter()
            .map(RawPiece::materialize)
            .collect::<Result<Vec<_>>>()?;
        let result =
            (|| -> Result<_> {
                if kind == "piece_features" {
                    return f::matrix(&piece_features(
                        &input.request,
                        &pieces,
                        encoder.as_ref(),
                        stems.as_ref(),
                        input.expanded.as_ref(),
                    )?);
                }
                let model = if input.production {
                    runtime.model("piece")?
                } else {
                    Arc::new(NumericRanker::from_json(
                        input
                            .model
                            .as_ref()
                            .ok_or_else(|| invalid("piece forest required"))?
                            .get(),
                    )?)
                };
                let ranked = PieceReranker::new(model.clone(), encoder.clone(), stems.clone())?
                    .rank(&input.request, &pieces, input.expanded.as_ref())?;
                observed_encoder = encoder.take_calls();
                observed_stems =
                    std::mem::take(&mut *stems.calls.lock().expect("scoped stem calls"));
                // The provider configuration is immutable; recomposition exposes the
                // same feature boundary without instrumenting production rankers.
                let feature_matrix =
                    if ken_retrieval::intent::requested_piece_kind(&input.request) == "symbol" {
                        None
                    } else {
                        Some(piece_features(
                            &input.request,
                            &pieces,
                            encoder.as_ref(),
                            stems.as_ref(),
                            input.expanded.as_ref(),
                        )?)
                    };
                let features = feature_matrix.as_ref().map(f::matrix).transpose()?;
                #[derive(serde::Serialize)]
                struct Ranked {
                    order: Vec<usize>,
                    scores: Vec<Value>,
                    features: Option<Box<RawValue>>,
                    #[serde(skip_serializing_if = "Option::is_none")]
                    paths_sha256: Option<String>,
                }
                let paths_sha256 = if input.production {
                    Some(if let Some(features) = &feature_matrix {
                        paths(&model, features)?
                    } else {
                        format!("{:x}", Sha256::digest(b"[]"))
                    })
                } else {
                    None
                };
                raw(&Ranked {
                    order: ranked.iter().map(|m| m.proposal_index).collect(),
                    scores: ranked.iter().map(|m| super::tagged(m.score)).collect(),
                    features,
                    paths_sha256,
                })
            })();
        if kind == "piece_features" || observed_encoder.is_empty() {
            observed_encoder = encoder.take_calls();
            observed_stems = std::mem::take(&mut *stems.calls.lock().expect("scoped stem calls"));
        } else {
            encoder.take_calls();
            std::mem::take(&mut *stems.calls.lock().expect("scoped stem calls"));
        }
        Ok(result?)
    })();
    extra.insert(
        "encoder_calls".into(),
        raw(&observed_encoder).expect("encoder calls"),
    );
    extra.insert(
        "stemmer_calls".into(),
        raw(&observed_stems).expect("stem calls"),
    );
    finish_observation(outcome, extra)
}
