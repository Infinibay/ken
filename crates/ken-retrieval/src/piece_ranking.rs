//! Coordinate requested-piece features and forest order without losing proposals.
use crate::{
    Result, RetrievalError,
    intent::{requested_piece_kind, requested_piece_path},
    numeric_ranker::NumericRanker,
    piece_candidates::PieceCandidate,
    piece_features::{piece_feature_names, piece_features},
    query::SearchRequest,
    stemming::WordStemmer,
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use std::{cmp::Ordering, rc::Rc, sync::Arc};

#[derive(Clone, Debug)]
pub struct PieceMatch {
    pub piece: PieceCandidate,
    pub score: f64,
    /// Identity of a proposal, including repeated proposals for the same piece.
    pub proposal_index: usize,
}

#[derive(Clone)]
pub struct PieceReranker {
    model: Arc<NumericRanker>,
    encoder: Rc<dyn WordEncoder>,
    stemmer: Arc<dyn WordStemmer>,
}
impl PieceReranker {
    pub fn new(
        model: Arc<NumericRanker>,
        encoder: Rc<dyn WordEncoder>,
        stemmer: Arc<dyn WordStemmer>,
    ) -> Result<Self> {
        if model.features() != piece_feature_names() {
            return Err(RetrievalError::Invalid(
                "piece model uses an incompatible feature schema".into(),
            ));
        }
        Ok(Self {
            model,
            encoder,
            stemmer,
        })
    }
    pub fn rank(
        &self,
        request: &SearchRequest,
        pieces: &[PieceCandidate],
        expanded: Option<&PythonText>,
    ) -> Result<Vec<PieceMatch>> {
        if requested_piece_kind(request) == "symbol" {
            return Ok(pieces
                .iter()
                .enumerate()
                .map(|(proposal_index, piece)| PieceMatch {
                    score: piece.matches()[0].score,
                    piece: piece.clone(),
                    proposal_index,
                })
                .collect());
        }
        let features = piece_features(
            request,
            pieces,
            self.encoder.as_ref(),
            self.stemmer.as_ref(),
            expanded,
        )?;
        let scores = self.model.predict(&features.values)?;
        let named_path = requested_piece_path(request).and_then(|p| p.to_utf8());
        let exact = |piece: &PieceCandidate| {
            piece
                .matches()
                .iter()
                .map(|m| *m.signals.get("exact").unwrap_or(&0.))
                .reduce(|a, b| if b > a { b } else { a })
                .expect("nonempty admitted support")
        };
        let mut ranked: Vec<_> = pieces
            .iter()
            .zip(scores)
            .enumerate()
            .map(|(proposal_index, (piece, score))| PieceMatch {
                piece: piece.clone(),
                score,
                proposal_index,
            })
            .collect();
        ranked.sort_by(|a, b| {
            let named = |m: &PieceMatch| named_path.as_deref() == Some(m.piece.path());
            named(b)
                .cmp(&named(a))
                .then_with(|| {
                    exact(&b.piece)
                        .partial_cmp(&exact(&a.piece))
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| b.score.partial_cmp(&a.score).unwrap_or(Ordering::Equal))
        });
        Ok(ranked)
    }
}
