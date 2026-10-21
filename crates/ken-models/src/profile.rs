//! Serializable retrieval concepts; identities and runtime loading are separate.
use crate::{ModelError, TransformerDtype};
use serde::{Deserialize, Serialize};

pub(crate) fn invalid(message: &str) -> ModelError {
    ModelError::Registration(message.into())
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub enum EncoderBackend {
    #[serde(rename = "static")]
    Static,
    #[serde(rename = "model2vec")]
    Model2Vec,
    #[serde(rename = "sentence-transformers")]
    SentenceTransformers,
    #[serde(rename = "mlx")]
    Mlx,
    #[serde(rename = "provided")]
    Provided,
}

fn static_backend() -> EncoderBackend {
    EncoderBackend::Static
}
fn float32() -> TransformerDtype {
    TransformerDtype::Float32
}
fn sequence_length() -> usize {
    512
}
fn batch_size() -> usize {
    16
}
fn candidate_limit() -> usize {
    100
}
fn passage_unit() -> String {
    "passage".into()
}
fn one() -> usize {
    1
}
fn six() -> usize {
    6
}
fn three() -> usize {
    3
}
fn channel_limit() -> usize {
    300
}
fn broad_limit() -> usize {
    1200
}
fn max_tokens() -> usize {
    256
}
fn rrf_k() -> usize {
    60
}
fn passage_tokenizer() -> String {
    "code-lexical-v1".into()
}
fn stemming() -> String {
    "snowball-english-v1".into()
}

pub(crate) fn hex_revision(value: &str, sizes: &[usize]) -> bool {
    sizes.contains(&value.len())
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct EncoderSpec {
    pub model_id: String,
    pub revision: String,
    #[serde(default = "static_backend")]
    pub backend: EncoderBackend,
    #[serde(default = "float32")]
    pub dtype: TransformerDtype,
    #[serde(default = "sequence_length")]
    pub sequence_length: usize,
    #[serde(default = "batch_size")]
    pub batch_size: usize,
}

impl EncoderSpec {
    pub fn from_json(input: &str) -> Result<Self, ModelError> {
        let value: Self = serde_json::from_str(input)?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ModelError> {
        if !hex_revision(&self.revision, &[40, 64]) {
            return Err(invalid("an immutable model revision/hash is required"));
        }
        if self.sequence_length == 0 || self.batch_size == 0 {
            return Err(invalid(
                "positive encoder sequence and batch budgets required",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct JointRanking {
    pub model: EncoderSpec,
    #[serde(default = "candidate_limit")]
    pub candidate_limit: usize,
    #[serde(default = "passage_unit")]
    pub rank_unit: String,
    #[serde(default = "one")]
    pub evidence_results: usize,
    #[serde(default = "six")]
    pub max_windows: usize,
    #[serde(default = "three")]
    pub max_fragments: usize,
}

impl JointRanking {
    fn validate(&self) -> Result<(), ModelError> {
        self.model.validate()?;
        if !matches!(self.rank_unit.as_str(), "entity" | "passage") {
            return Err(invalid("unknown relevance unit"));
        }
        if self.candidate_limit == 0
            || self.max_windows == 0
            || !(1..=4).contains(&self.max_fragments)
        {
            return Err(invalid("invalid relevance/evidence budgets"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct EvidenceRanking {
    pub model_revision: String,
    pub word_model: EncoderSpec,
    #[serde(default)]
    pub expansion_revision: Option<String>,
    #[serde(default = "stemming")]
    pub stemming: String,
    #[serde(default = "one")]
    pub feature_version: usize,
    #[serde(default = "one")]
    pub evidence_version: usize,
}

impl EvidenceRanking {
    fn validate(&self) -> Result<(), ModelError> {
        self.word_model.validate()?;
        if !hex_revision(&self.model_revision, &[64]) {
            return Err(invalid("an immutable numeric model revision is required"));
        }
        if self
            .expansion_revision
            .as_ref()
            .is_some_and(|r| !hex_revision(r, &[64]))
        {
            return Err(invalid("an immutable query expansion revision is required"));
        }
        if !(1..=3).contains(&self.feature_version) || !(1..=3).contains(&self.evidence_version) {
            return Err(invalid("unsupported ranking feature version"));
        }
        if self.stemming != "snowball-english-v1" {
            return Err(invalid("unsupported ranking stemming algorithm"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ContextualRetrieval {
    pub model: EncoderSpec,
    #[serde(default = "channel_limit")]
    pub channel_limit: usize,
    #[serde(default = "broad_limit")]
    pub broad_limit: usize,
    #[serde(default = "one")]
    pub projection_version: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub view_model: Option<EncoderSpec>,
}

impl ContextualRetrieval {
    fn validate(&self) -> Result<(), ModelError> {
        self.model.validate()?;
        if self.channel_limit == 0 || self.broad_limit < self.channel_limit {
            return Err(invalid(
                "positive, consistent contextual proposal budgets required",
            ));
        }
        if self.projection_version != 1 {
            return Err(invalid("unsupported contextual source projection"));
        }
        if let Some(view) = &self.view_model {
            view.validate()?;
            if view == &self.model {
                return Err(invalid(
                    "separate source views require their distinct projection identity",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RetrievalProfile {
    pub identity: EncoderSpec,
    pub behavior: EncoderSpec,
    #[serde(default = "max_tokens")]
    pub max_tokens: usize,
    #[serde(default = "candidate_limit")]
    pub candidate_limit: usize,
    #[serde(default = "rrf_k")]
    pub rrf_k: usize,
    #[serde(default = "passage_tokenizer")]
    pub passage_tokenizer: String,
    #[serde(default = "three")]
    pub representation_version: usize,
    #[serde(default)]
    pub joint: Option<JointRanking>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evidence: Option<EvidenceRanking>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub contextual: Option<ContextualRetrieval>,
}

impl RetrievalProfile {
    pub fn from_json(input: &str) -> Result<Self, ModelError> {
        Self::from_json_with_upgrade(input, false)
    }

    pub fn from_json_with_upgrade(input: &str, upgrade: bool) -> Result<Self, ModelError> {
        let mut raw: serde_json::Value = serde_json::from_str(input)?;
        if upgrade && raw["representation_version"] == 2 {
            raw.as_object_mut()
                .ok_or_else(|| invalid("profile object required"))?
                .remove("representation_version");
        }
        let value: Self = serde_json::from_value(raw)?;
        value.validate()?;
        Ok(value)
    }

    pub fn to_json(&self) -> Result<String, ModelError> {
        self.validate()?;
        Ok(crate::assets::python_json(&serde_json::to_value(self)?))
    }

    pub fn validate(&self) -> Result<(), ModelError> {
        self.identity.validate()?;
        self.behavior.validate()?;
        if self.max_tokens == 0 || self.candidate_limit == 0 || self.rrf_k == 0 {
            return Err(invalid("positive retrieval budgets required"));
        }
        if !matches!(
            self.passage_tokenizer.as_str(),
            "code-lexical-v1" | "behavior-model"
        ) {
            return Err(invalid("unknown source passage tokenizer"));
        }
        if self.representation_version != 3 {
            return Err(invalid(
                "unsupported representation version; reindex with current profile",
            ));
        }
        if self.joint.is_some() && self.evidence.is_some() {
            return Err(invalid("choose one owner ranking profile"));
        }
        if let Some(joint) = &self.joint {
            joint.validate()?;
        }
        if let Some(evidence) = &self.evidence {
            evidence.validate()?;
        }
        if let Some(contextual) = &self.contextual {
            contextual.validate()?;
        }
        let contextual_features = self
            .evidence
            .as_ref()
            .is_some_and(|v| v.feature_version >= 2);
        if contextual_features != self.contextual.is_some() {
            return Err(invalid(
                "contextual retrieval and its pinned ranking features are required together",
            ));
        }
        let views = self
            .evidence
            .as_ref()
            .is_some_and(|v| v.feature_version == 3);
        if views
            != self
                .contextual
                .as_ref()
                .is_some_and(|v| v.view_model.is_some())
        {
            return Err(invalid(
                "source views and their pinned ranking features are required together",
            ));
        }
        Ok(())
    }
}
