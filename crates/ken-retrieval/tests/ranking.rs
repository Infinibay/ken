use ken_retrieval::{
    Result,
    query::{Candidate, CodeMatch, SearchRequest},
    ranking::{RelevanceJudge, candidate_document, rank_candidates},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use std::{cell::RefCell, collections::BTreeMap};
#[derive(Deserialize)]
struct Root {
    families: BTreeMap<String, Box<RawValue>>,
}
#[derive(Deserialize)]
struct Family {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Box<RawValue>,
    result: Option<Box<RawValue>>,
    error: Option<Value>,
    #[serde(default)]
    judge_calls: Vec<Call>,
}
#[derive(Deserialize, Clone, Debug, PartialEq)]
struct Call {
    query: PythonText,
    documents: Vec<PythonText>,
    purpose: String,
}
#[derive(Deserialize)]
struct Input {
    candidates: Vec<Candidate>,
    request: SearchRequest,
    judge: bool,
    rerank_limit: isize,
    rank_unit: String,
    scores: Option<Vec<Value>>,
}
struct Judge {
    scores: Option<Vec<Value>>,
    calls: RefCell<Vec<Call>>,
}
impl RelevanceJudge for Judge {
    fn score(
        &self,
        query: &PythonText,
        documents: &[PythonText],
        purpose: &str,
    ) -> Result<Vec<f64>> {
        self.calls.borrow_mut().push(Call {
            query: query.clone(),
            documents: documents.to_vec(),
            purpose: purpose.into(),
        });
        Ok(if let Some(scores) = &self.scores {
            scores
                .iter()
                .map(|x| match x.as_str() {
                    Some("nan") => f64::NAN,
                    Some("inf") => f64::INFINITY,
                    _ => x.as_f64().unwrap(),
                })
                .collect()
        } else {
            documents
                .iter()
                .map(|doc| {
                    if doc.to_utf8().unwrap().contains("remove_credentials") {
                        3.
                    } else {
                        -2.
                    }
                })
                .collect()
        })
    }
}
#[test]
fn documents_and_complete_ranked_evidence_match_the_original_without_mutating_proposals() {
    #[cfg(target_os = "macos")]
    let raw = include_str!("fixtures/search-selection-reference.json");
    #[cfg(target_os = "linux")]
    let raw = include_str!("fixtures/search-selection-reference-linux.json");
    let root: Root = serde_json::from_str(raw).unwrap();
    let family: Family = serde_json::from_str(root.families["ranking"].get()).unwrap();
    assert_eq!(family.cases.len(), 112);
    for case in family.cases {
        if case.kind == "document" {
            #[derive(Deserialize)]
            struct Document {
                candidate: Candidate,
                purpose: String,
            }
            let input: Document = serde_json::from_str(case.input.get()).unwrap();
            let expected: PythonText = serde_json::from_str(case.result.unwrap().get()).unwrap();
            assert_eq!(
                candidate_document(&input.candidate, &input.purpose).unwrap(),
                expected,
                "{}",
                case.id
            );
            continue;
        }
        let input: Input = serde_json::from_str(case.input.get()).unwrap();
        let before = input.candidates.clone();
        let judge = Judge {
            scores: input.scores,
            calls: RefCell::new(Vec::new()),
        };
        let actual = rank_candidates(
            &input.request,
            &input.candidates,
            if input.judge { Some(&judge) } else { None },
            input.rerank_limit,
            &input.rank_unit,
        );
        assert_eq!(before, input.candidates, "{} proposal mutation", case.id);
        if let Some(error) = case.error {
            assert_eq!(*judge.calls.borrow(), case.judge_calls, "{} calls", case.id);
            assert!(
                actual
                    .unwrap_err()
                    .to_string()
                    .contains(error["message"].as_str().unwrap()),
                "{}",
                case.id
            );
        } else {
            #[derive(Deserialize)]
            struct Output {
                matches: Vec<CodeMatch>,
                judge_calls: Vec<Call>,
                unchanged: bool,
            }
            let expected: Output = serde_json::from_str(case.result.unwrap().get()).unwrap();
            assert!(expected.unchanged);
            assert_eq!(
                *judge.calls.borrow(),
                expected.judge_calls,
                "{} calls",
                case.id
            );
            assert_eq!(
                actual.unwrap(),
                expected.matches,
                "{} complete ordered owner/evidence",
                case.id
            );
        }
    }
}
