use super::{Calls, raw};
use ken_retrieval::{
    Result,
    query::{Candidate, SearchRequest},
    ranking::{RelevanceJudge, candidate_document, rank_candidates},
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::{Value, value::RawValue};
#[derive(Deserialize)]
struct Input {
    candidates: Vec<Candidate>,
    request: SearchRequest,
    judge: bool,
    rerank_limit: isize,
    rank_unit: String,
    scores: Option<Vec<Value>>,
}
struct Judge<'a> {
    scores: Option<Vec<Value>>,
    calls: &'a Calls,
}
impl RelevanceJudge for Judge<'_> {
    fn score(
        &self,
        query: &PythonText,
        documents: &[PythonText],
        purpose: &str,
    ) -> Result<Vec<f64>> {
        #[derive(Serialize)]
        struct Call<'a> {
            query: &'a PythonText,
            documents: &'a [PythonText],
            purpose: &'a str,
        }
        self.calls.push(&Call {
            query,
            documents,
            purpose,
        })?;
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
            let word: Vec<_> = "remove_credentials".chars().map(u32::from).collect();
            documents
                .iter()
                .map(|d| {
                    if d.codepoints().windows(word.len()).any(|w| w == word) {
                        3.
                    } else {
                        -2.
                    }
                })
                .collect()
        })
    }
}
pub(super) fn run(input: &str, kind: &str, calls: &Calls) -> Result<Box<RawValue>> {
    if kind == "document" {
        #[derive(Deserialize)]
        struct Document {
            candidate: Candidate,
            purpose: String,
        }
        let i: Document = serde_json::from_str(input)?;
        return raw(&candidate_document(&i.candidate, &i.purpose)?);
    }
    let i: Input = serde_json::from_str(input)?;
    let before = i.candidates.clone();
    let judge = Judge {
        scores: i.scores,
        calls,
    };
    let matches = rank_candidates(
        &i.request,
        &i.candidates,
        if i.judge { Some(&judge) } else { None },
        i.rerank_limit,
        &i.rank_unit,
    )?;
    #[derive(Serialize)]
    struct Output {
        matches: Vec<ken_retrieval::query::CodeMatch>,
        judge_calls: Vec<Box<RawValue>>,
        unchanged: bool,
    }
    raw(&Output {
        matches,
        judge_calls: calls.values(),
        unchanged: before == i.candidates,
    })
}
