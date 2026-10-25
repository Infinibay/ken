mod symbol_views_support;
use ken_retrieval::{
    Result, RetrievalError,
    paired_reranker::{NeuralScores, PairedReranker},
    symbol_views::{complete_code_view, rank_symbol_views},
};
use ken_text::PythonText;
use serde::Deserialize;
use std::cell::RefCell;
use symbol_views_support::*;

struct Neural<'a> {
    input: &'a Input,
    calls: RefCell<Vec<Call>>,
    pairs: RefCell<usize>,
}
impl PairedReranker for Neural<'_> {
    fn pair_fits(&self, query: &PythonText, text: &PythonText) -> Result<bool> {
        self.calls.borrow_mut().push(Call {
            op: "pair_fits".into(),
            query: query.clone(),
            text: Some(text.clone()),
            texts: None,
        });
        let i = *self.pairs.borrow();
        *self.pairs.borrow_mut() += 1;
        if self.input.fail_pair == Some(i) {
            return Err(RetrievalError::Invalid("pair failed".into()));
        }
        Ok(self.input.accepted.get(i).copied().unwrap_or(true))
    }
    fn score(&self, query: &PythonText, texts: &[PythonText]) -> Result<NeuralScores> {
        self.calls.borrow_mut().push(Call {
            op: "score".into(),
            query: query.clone(),
            text: None,
            texts: Some(texts.to_vec()),
        });
        if self.input.fail_score {
            return Err(RetrievalError::Invalid("score failed".into()));
        }
        Ok(NeuralScores {
            scores: self.input.code_scores.iter().map(number).collect(),
            details: self.input.details.clone().unwrap(),
        })
    }
}
#[test]
fn frozen_whole_code_views_preserve_python_boundaries_and_text() {
    #[derive(Deserialize)]
    struct Projection {
        view: Option<PythonText>,
    }
    let corpus = corpus();
    assert_eq!(corpus.cases.len(), 61);
    for case in corpus.cases.iter().filter(|c| c.kind == "projection") {
        let actual = complete_code_view(&case.input.descriptions[0]);
        if let Some(expected) = &case.result {
            let expected: Projection = serde_json::from_str(expected.get()).unwrap();
            assert_eq!(actual.unwrap(), expected.view, "{}", case.id);
        } else {
            assert_eq!(
                actual.unwrap_err().to_string(),
                case.error.as_ref().unwrap()["message"].as_str().unwrap(),
                "{}",
                case.id
            );
        }
    }
}
#[test]
fn frozen_two_view_policy_preserves_calls_scores_fallback_and_stable_order() {
    for case in corpus().cases.iter().filter(|c| c.kind == "rank") {
        let neural = Neural {
            input: &case.input,
            calls: RefCell::default(),
            pairs: RefCell::new(0),
        };
        let scores = case
            .input
            .original_scores
            .iter()
            .map(number)
            .collect::<Vec<_>>();
        let actual = rank_symbol_views(
            case.input.query.as_ref().unwrap(),
            &case.input.descriptions,
            &scores,
            &neural,
        );
        assert_eq!(*neural.calls.borrow(), case.calls, "{} calls", case.id);
        if let Some(expected) = &case.result {
            let expected: serde_json::Value = serde_json::from_str(expected.get()).unwrap();
            let actual = actual.unwrap();
            assert_eq!(
                serde_json::to_value(&actual).unwrap(),
                {
                    let mut e = expected.clone();
                    e.as_object_mut().unwrap().remove("views");
                    e
                },
                "{}",
                case.id
            );
            exact_scores(&actual.code_scores, &expected["code_scores"]);
            exact_scores(&actual.mean_scores, &expected["mean_scores"]);
            let mut membership = actual.order;
            membership.sort_unstable();
            assert_eq!(membership, (0..scores.len()).collect::<Vec<_>>());
        } else {
            let error = actual.unwrap_err().to_string();
            if case.id.starts_with("rank-bad-model") {
                assert!(error.contains("one finite score"), "{error}");
            } else {
                assert_eq!(
                    error,
                    case.error.as_ref().unwrap()["message"].as_str().unwrap(),
                    "{}",
                    case.id
                );
            }
        }
    }
}
#[test]
fn invalid_registered_model_score_values_reject_before_ranking() {
    let corpus = corpus();
    let case = corpus.cases.iter().find(|c| c.id == "rank-single").unwrap();
    for invalid in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let neural = Neural {
            input: &case.input,
            calls: RefCell::default(),
            pairs: RefCell::new(0),
        };
        assert!(
            rank_symbol_views(&"x".into(), &case.input.descriptions, &[invalid], &neural).is_err()
        );
        assert!(neural.calls.borrow().is_empty());
    }
}
#[test]
fn separate_original_fusion_extension_protects_denominator_grouping() {
    let expected = corpus().fusion_grouping_extension;
    let order =
        ken_retrieval::reranker_fusion::fused_reranker_order(&[0., 1.], 0.5, 2_f64.powi(53))
            .unwrap();
    assert_eq!(serde_json::to_value(order).unwrap(), expected["result"]);
}
