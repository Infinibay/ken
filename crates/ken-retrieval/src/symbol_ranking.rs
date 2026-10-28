//! Compose bounded neural relevance and explicit source preferences within native10.
use crate::{
    EntityKey, Result, RetrievalError,
    operation_witnesses::OperationWitnesses,
    owner_descriptions::OwnerDescriptions,
    paired_reranker::PairedReranker,
    query::SearchRequest,
    source_catalog::SourceCatalog,
    symbol_preferences::{apply_symbol_preferences, is_test_case},
    symbol_requirements::requirements,
    symbol_views::{rank_symbol_references, validate_symbol_scores},
};
use ken_syntax::GrammarCatalog;
use ken_text::PythonText;
use serde::Serialize;
use serde_json::Value;
use std::{collections::BTreeSet, rc::Rc, sync::Arc};
pub const SYMBOL_POLICY: &str = "bounded-symbol-relations-v305";
#[derive(Clone, Debug, Serialize)]
pub struct SymbolRanking {
    pub order: Vec<usize>,
    #[serde(serialize_with = "crate::paired_reranker::serialize_scores")]
    pub code_scores: Vec<f64>,
    #[serde(serialize_with = "crate::paired_reranker::serialize_scores")]
    pub mean_scores: Vec<f64>,
    pub code_view_used: Vec<bool>,
    pub witnesses: Vec<BTreeSet<String>>,
    pub additional_inference: Value,
}
pub struct SymbolRanker {
    catalog: Arc<SourceCatalog>,
    neural: Rc<dyn PairedReranker>,
    operations: OperationWitnesses,
}
impl SymbolRanker {
    pub fn new(
        catalog: Arc<SourceCatalog>,
        neural: Rc<dyn PairedReranker>,
        grammars: Arc<GrammarCatalog>,
    ) -> Self {
        Self {
            operations: OperationWitnesses::new(catalog.clone(), grammars),
            catalog,
            neural,
        }
    }
    pub fn rank(
        &mut self,
        request: &SearchRequest,
        keys: &[EntityKey],
        expanded_query: &PythonText,
        original_scores: &[f64],
        descriptions: &mut OwnerDescriptions,
    ) -> Result<SymbolRanking> {
        validate_symbol_scores(keys.len(), original_scores)?;
        if !descriptions.belongs_to(&self.catalog) {
            return Err(RetrievalError::Invalid(
                "symbol descriptions belong to a different catalog".into(),
            ));
        }
        let owned = keys
            .iter()
            .map(|k| descriptions.get(k))
            .collect::<Result<Vec<_>>>()?;
        let views = owned.iter().map(Arc::as_ref).collect::<Vec<_>>();
        let relevance = rank_symbol_references(
            expanded_query,
            &views,
            original_scores,
            self.neural.as_ref(),
        )?;
        let required = requirements(request);
        let witnesses = keys
            .iter()
            .map(|key| {
                if required.operations.is_empty() {
                    Ok(BTreeSet::new())
                } else {
                    self.operations
                        .for_owner(key)
                        .map_err(|e| RetrievalError::Invalid(e.to_string()))
                }
            })
            .collect::<Result<Vec<_>>>()?;
        let test_cases = keys
            .iter()
            .map(|key| {
                if required.test_case {
                    is_test_case(key, &self.catalog)
                        .map_err(|e| RetrievalError::Invalid(e.to_string()))
                } else {
                    Ok(false)
                }
            })
            .collect::<Result<Vec<_>>>()?;
        let implementations = views
            .iter()
            .map(|d| d.fields["executable"].clone())
            .collect::<Vec<_>>();
        let order = apply_symbol_preferences(
            &required,
            &witnesses,
            &test_cases,
            &implementations,
            &relevance.order,
        )?;
        Ok(SymbolRanking {
            order,
            code_scores: relevance.code_scores,
            mean_scores: relevance.mean_scores,
            code_view_used: relevance.code_view_used,
            witnesses,
            additional_inference: relevance.additional_inference,
        })
    }
}
