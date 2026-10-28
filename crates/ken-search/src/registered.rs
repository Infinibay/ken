//! Assemble the registered CPU policy from explicit application-owned resources.
use crate::{Result, SearchResourceInputs, SearchResourceProvider, SearchResources};
use ken_models::{
    ContextualRetrieval, EvidenceRanking, FrozenTranslationRuntime, LegacyRuntimeIdentity,
    ModelCatalog, ModelFactory, RetrievalProfile, TranslationModel,
};
use ken_retrieval::{
    RetrievalError, context_preparation::ContextSourceEncoder, owner_ranking::ExpansionConfig,
    paired_reranker::OnnxPairedReranker, rank_models::ProductionRankModels,
};
use std::{rc::Rc, sync::Arc};
pub struct RegisteredSearchResources {
    factory: Arc<ModelFactory>,
    rank_models: Arc<ProductionRankModels>,
    legacy: LegacyRuntimeIdentity,
}
impl RegisteredSearchResources {
    pub fn new(
        factory: Arc<ModelFactory>,
        rank_models: Arc<ProductionRankModels>,
        legacy: LegacyRuntimeIdentity,
    ) -> Self {
        Self {
            factory,
            rank_models,
            legacy,
        }
    }
    pub fn inputs(&self) -> Result<SearchResourceInputs> {
        let spec = ModelCatalog::built_in()
            .map_err(RetrievalError::from)?
            .potion_spec();
        let base_profile = RetrievalProfile::from_json(
            &serde_json::json!({"identity":spec,"behavior":spec}).to_string(),
        )
        .map_err(RetrievalError::from)?;
        let owner = self
            .factory
            .encoder(&spec, &self.legacy)
            .map_err(RetrievalError::from)?;
        let word_spec = owner
            .registered_static_spec(&self.legacy)
            .map_err(RetrievalError::from)?;
        let words = Rc::new(crate::resources::NativeWords::new(owner, word_spec.clone()));
        let context = Rc::new(crate::context_encoder::NativeContext::new(
            self.factory.context().map_err(RetrievalError::from)?,
        )?);
        let native_model = self.rank_models.native()?;
        let piece_model = self.rank_models.piece()?;
        let expansion = self.factory.expansion().map_err(RetrievalError::from)?;
        let revision = TranslationModel::from_json(include_str!(
            "../../ken-models/resources/es-en-ct2-int8.json"
        ))
        .map_err(RetrievalError::from)?
        .compatible_revision(FrozenTranslationRuntime::Linux482);
        let neural = Rc::new(OnnxPairedReranker(
            self.factory.reranker().map_err(RetrievalError::from)?,
        ));
        let mut profile = base_profile.clone();
        profile.contextual = Some(ContextualRetrieval {
            model: context.spec().clone(),
            channel_limit: 300,
            broad_limit: 1200,
            projection_version: 1,
            view_model: Some(context.view_spec().clone()),
        });
        profile.evidence = Some(EvidenceRanking {
            model_revision: native_model.fingerprint().map_err(RetrievalError::from)?,
            word_model: word_spec,
            expansion_revision: Some(revision.clone()),
            stemming: "snowball-english-v1".into(),
            feature_version: 3,
            evidence_version: 3,
        });
        Ok(SearchResourceInputs {
            words,
            context,
            native_model,
            piece_model,
            neural,
            expansion: ExpansionConfig {
                expand_query: Some(Rc::new(move |query| {
                    let query = query.to_utf8().ok_or_else(|| {
                        RetrievalError::Invalid(
                            "query expansion contains non-scalar Unicode".into(),
                        )
                    })?;
                    Ok(expansion.expand(&query)?.into())
                })),
                revision: Some(revision),
            },
            base_profile,
            profile,
            legacy: self.legacy.clone(),
        })
    }
}
impl SearchResourceProvider for RegisteredSearchResources {
    fn build(&self) -> Result<SearchResources> {
        SearchResources::new(self.inputs()?)
    }
}
