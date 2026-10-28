//! Build coherent, shared execution owners without acquiring them on cold lookups.
use crate::{Result, SearchError};
use ken_index::encoder::ManagedDocumentEncoder;
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, ManagedEncoder, RetrievalProfile};
use ken_retrieval::{
    DocumentEncoder, RetrievalError,
    context_preparation::ContextSourceEncoder,
    encoder::EncoderLoader,
    numeric_ranker::NumericRanker,
    owner_ranking::{EvidenceReranker, ExpansionConfig},
    paired_reranker::PairedReranker,
    piece_ranking::PieceReranker,
    query_encoder::{ManagedQueryEncoder, QueryEncoder},
    stemming::EnglishStems,
    word_encoder::{ManagedWordEncoder, WordEncoder},
};
use ken_text::PythonText;
use std::{rc::Rc, sync::Arc};
pub trait SearchWords: WordEncoder + QueryEncoder + DocumentEncoder {}
impl<T: WordEncoder + QueryEncoder + DocumentEncoder> SearchWords for T {}
/// Inputs for one coherent search policy; all rankers receive the same words.
pub struct SearchResourceInputs {
    pub words: Rc<dyn SearchWords>,
    pub context: Rc<dyn ContextSourceEncoder>,
    pub native_model: Arc<NumericRanker>,
    pub piece_model: Arc<NumericRanker>,
    pub neural: Rc<dyn PairedReranker>,
    pub expansion: ExpansionConfig,
    pub base_profile: RetrievalProfile,
    pub profile: RetrievalProfile,
    pub legacy: LegacyRuntimeIdentity,
}
pub struct SearchResources {
    pub(crate) words: Rc<dyn SearchWords>,
    pub(crate) context: Rc<dyn ContextSourceEncoder>,
    pub(crate) owner_ranker: EvidenceReranker,
    pub(crate) piece_ranker: PieceReranker,
    pub(crate) neural: Rc<dyn PairedReranker>,
    pub(crate) base_profile: RetrievalProfile,
    pub(crate) profile: RetrievalProfile,
    pub(crate) legacy: LegacyRuntimeIdentity,
    pub(crate) fingerprint: String,
}
pub trait SearchResourceProvider {
    fn build(&self) -> Result<SearchResources>;
}
impl SearchResources {
    pub fn new(input: SearchResourceInputs) -> Result<Self> {
        let SearchResourceInputs {
            words,
            context,
            native_model,
            piece_model,
            neural,
            expansion,
            base_profile,
            profile,
            legacy,
        } = input;
        base_profile.validate().map_err(RetrievalError::from)?;
        profile.validate().map_err(RetrievalError::from)?;
        let mut source = profile.clone();
        source.contextual = None;
        source.evidence = None;
        let policy = profile
            .contextual
            .as_ref()
            .ok_or_else(|| invalid("best search requires contextual policy"))?;
        let evidence = profile
            .evidence
            .as_ref()
            .ok_or_else(|| invalid("best search requires evidence policy"))?;
        if source != base_profile
            || base_profile.identity != base_profile.behavior
            || words.spec() != &evidence.word_model
            || words.spec().model_id != base_profile.identity.model_id
            || &policy.model != context.spec()
            || policy.view_model.as_ref() != Some(context.view_spec())
            || evidence.feature_version != 3
            || evidence.evidence_version != 3
        {
            return Err(invalid(
                "best search resources do not match their pinned profiles",
            ));
        }
        let stems = EnglishStems::shared();
        let owner_ranker =
            EvidenceReranker::new(native_model, words.clone(), stems.clone(), Some(expansion))?;
        owner_ranker.validate(evidence)?;
        let piece_ranker = PieceReranker::new(piece_model, words.clone(), stems)?;
        let fingerprint = profile.fingerprint(&legacy).map_err(RetrievalError::from)?;
        Ok(Self {
            words,
            context,
            owner_ranker,
            piece_ranker,
            neural,
            base_profile,
            profile,
            legacy,
            fingerprint,
        })
    }
    pub fn profile(&self) -> &RetrievalProfile {
        &self.profile
    }
    pub fn base_profile(&self) -> &RetrievalProfile {
        &self.base_profile
    }
    pub fn words(&self) -> Rc<dyn SearchWords> {
        self.words.clone()
    }
    pub fn legacy(&self) -> &LegacyRuntimeIdentity {
        &self.legacy
    }
    pub(crate) fn loader(&self) -> Rc<dyn EncoderLoader> {
        Rc::new(SharedWords {
            words: self.words.clone(),
            source_spec: self.base_profile.identity.clone(),
        })
    }
}
fn invalid(s: &str) -> SearchError {
    RetrievalError::Invalid(s.into()).into()
}
struct SharedWords {
    words: Rc<dyn SearchWords>,
    source_spec: EncoderSpec,
}
impl EncoderLoader for SharedWords {
    fn load(&self, spec: &EncoderSpec) -> ken_retrieval::Result<Rc<dyn DocumentEncoder>> {
        if &self.source_spec != spec {
            return Err(RetrievalError::Invalid(
                "shared words do not match source encoder".into(),
            ));
        }
        Ok(self.words.clone())
    }
}
pub(crate) struct NativeWords {
    owner: Arc<ManagedEncoder>,
    words: ManagedWordEncoder,
}
impl NativeWords {
    pub fn new(owner: Arc<ManagedEncoder>, spec: EncoderSpec) -> Self {
        Self {
            words: ManagedWordEncoder::new(owner.clone(), spec),
            owner,
        }
    }
}
impl WordEncoder for NativeWords {
    fn spec(&self) -> &EncoderSpec {
        self.words.spec()
    }
    fn embed_query(&self, t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.words.embed_query(t)
    }
    fn embed_passages(&self, t: &[PythonText]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.words.embed_passages(t)
    }
}
impl QueryEncoder for NativeWords {
    fn embed_query(&self, t: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        ManagedQueryEncoder(self.owner.clone()).embed_query(t)
    }
}
impl DocumentEncoder for NativeWords {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        ManagedDocumentEncoder(self.owner.clone()).dim()
    }
    fn token_count(&self, t: &str) -> ken_retrieval::Result<usize> {
        ManagedDocumentEncoder(self.owner.clone()).token_count(t)
    }
    fn embed_passages(&self, t: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        ManagedDocumentEncoder(self.owner.clone()).embed_passages(t)
    }
}
