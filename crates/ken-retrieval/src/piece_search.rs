//! Coordinate requested-unit ranking while each component owns its source policy.
use crate::{
    EntityKey, Result, RetrievalError,
    intent::{requested_piece_kind, requested_piece_path},
    owner_descriptions::OwnerDescriptions,
    paired_reranker::{NeuralScores, PairedReranker},
    piece_candidates::PieceAssembler,
    piece_cards::{CardEntity, PieceUnit, build_piece_cards, card_text},
    piece_ranking::PieceReranker,
    presentation::{SearchResponse, SearchResult, present_cards},
    query::{CodeMatch, SearchRequest},
    reranker_fusion::fused_reranker_order,
    source_catalog::SourceCatalog,
    source_locator::module_name,
    symbol_ranking::{SYMBOL_POLICY, SymbolRanker},
};
use ken_syntax::GrammarCatalog;
use ken_text::PythonText;
use serde_json::json;
use std::{rc::Rc, sync::Arc};
const NATIVE_LIMIT: usize = 10;
fn invalid(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
fn unit(kind: &str, path: &str, entity: Option<&EntityKey>) -> PieceUnit {
    PieceUnit {
        target_kind: kind.into(),
        path: path.into(),
        entity: entity.map(CardEntity::from),
        module_name: (kind == "module").then(|| module_name(path)).flatten(),
    }
}
pub struct PieceSearch {
    catalog: Arc<SourceCatalog>,
    ranker: PieceReranker,
    neural: Rc<dyn PairedReranker>,
    assembler: PieceAssembler,
    symbols: SymbolRanker,
}
impl PieceSearch {
    pub fn new(
        catalog: Arc<SourceCatalog>,
        ranker: PieceReranker,
        neural: Rc<dyn PairedReranker>,
        grammars: Arc<GrammarCatalog>,
    ) -> Self {
        Self {
            assembler: PieceAssembler::new(catalog.clone()),
            symbols: SymbolRanker::new(catalog.clone(), neural.clone(), grammars),
            catalog,
            ranker,
            neural,
        }
    }
    pub fn descriptions(&self) -> &OwnerDescriptions {
        self.assembler.descriptions()
    }
    pub fn search(
        &mut self,
        request: &SearchRequest,
        matches: &[CodeMatch],
        expanded_query: &PythonText,
        profile_version: &str,
        exact: bool,
    ) -> Result<SearchResponse> {
        let kind = requested_piece_kind(request);
        let cards = build_piece_cards(matches, &kind, expanded_query, &self.catalog, NATIVE_LIMIT)
            .map_err(|e| invalid(&e.to_string()))?;
        let pieces = self.assembler.assemble(matches, &kind, NATIVE_LIMIT)?;
        let ranked = self.ranker.rank(request, &pieces, Some(expanded_query))?;
        let existing = ranked
            .iter()
            .map(|m| {
                let identity = unit(m.piece.kind(), m.piece.path(), m.piece.entity());
                cards
                    .iter()
                    .position(|c| c.unit == identity)
                    .ok_or_else(|| invalid("piece reranking changed native top10 membership"))
            })
            .collect::<Result<Vec<_>>>()?;
        let neural = if exact {
            NeuralScores {
                scores: vec![0.; existing.len()],
                details: json!({}),
            }
        } else {
            self.neural.score(
                expanded_query,
                &existing
                    .iter()
                    .map(|&i| PythonText::from(card_text(&cards[i])))
                    .collect::<Vec<_>>(),
            )?
        };
        if neural.scores.len() != existing.len() || neural.scores.iter().any(|s| !s.is_finite()) {
            return Err(invalid(
                "finite piece reranker scores with matching cardinality required",
            ));
        }
        let symbols = if !exact && kind == "symbol" {
            let keys = existing
                .iter()
                .map(|&i| {
                    let u = &cards[i].unit;
                    u.entity
                        .as_ref()
                        .map(|e| e.at(&u.path))
                        .ok_or_else(|| invalid("symbol card requires entity"))
                })
                .collect::<Result<Vec<_>>>()?;
            Some(self.symbols.rank(
                request,
                &keys,
                expanded_query,
                &neural.scores,
                self.assembler.descriptions_mut(),
            )?)
        } else {
            None
        };
        let local_order = if exact {
            (0..existing.len()).collect()
        } else if let Some(symbols) = &symbols {
            symbols.order.clone()
        } else {
            fused_reranker_order(&neural.scores, 0.5, 60.)?
        };
        let mut order = local_order.iter().map(|&i| existing[i]).collect::<Vec<_>>();
        if let Some(path) = requested_piece_path(request) {
            order.sort_by_key(|&i| PythonText::from(cards[i].unit.path.as_str()) != path);
        }
        let mut membership = order.clone();
        membership.sort_unstable();
        if membership != (0..cards.len().min(NATIVE_LIMIT)).collect::<Vec<_>>() {
            return Err(invalid("piece reranking changed native top10 membership"));
        }
        let ordered = order.iter().map(|&i| cards[i].clone()).collect::<Vec<_>>();
        let mut response = present_cards(&ordered, request, &self.catalog, profile_version)
            .map_err(|e| invalid(&e.to_string()))?;
        // Preserve the original lifecycle: diagnostics are added AFTER trimming.
        if request.explain() {
            for result in &mut response.results {
                let SearchResult::Piece(result) = result else {
                    return Err(invalid("piece presentation returned an owner"));
                };
                let entity = matches!(kind.as_str(), "class" | "symbol")
                    .then(|| result.source.entity.at(&result.source.path));
                let identity = unit(&kind, &result.source.path, entity.as_ref());
                let i = cards
                    .iter()
                    .position(|c| c.unit == identity)
                    .ok_or_else(|| invalid("presented piece identity differs"))?;
                let j = existing
                    .iter()
                    .position(|&n| n == i)
                    .ok_or_else(|| invalid("presented piece ranking differs"))?;
                let mut signals = json!({"native_piece_rank":i+1,"piece_rank":j+1,
                    "piece_score":ranked[j].score,"neural_score":neural.scores[j],"reranker":neural.details});
                if let Some(symbols) = &symbols {
                    signals["symbol_ranking"] = json!({"policy":SYMBOL_POLICY,
                        "code_view_used":symbols.code_view_used[j],"code_score":symbols.code_scores[j],
                        "mean_score":symbols.mean_scores[j],"source_operations":symbols.witnesses[j],
                        "additional_reranker":symbols.additional_inference});
                }
                result.signals = Some(signals);
            }
        }
        Ok(response)
    }
}
