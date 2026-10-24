use super::scenario::{Mutation, Physical, Scenario};
use super::{Observation, ScenarioResult, finish_observation, invalid, raw};
use ken_retrieval::{
    Result,
    evidence::{
        EvidenceOptions, complete_evidence, complete_owned_context, entity_extent, refine_evidence,
        source_bounds, verified_lines,
    },
    query::{CodeMatch, SearchRequest},
    ranking::RelevanceJudge,
    source_evidence::refine_source_evidence,
    stemming::WordStemmer,
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    files: BTreeMap<String, Vec<u8>>,
    matches: Vec<CodeMatch>,
    request: SearchRequest,
    operation: String,
    options: EvidenceOptions,
    judge: JudgeOptions,
    expanded_query: PythonText,
    stems: BTreeMap<String, PythonText>,
    mutation: Option<Mutation>,
    implementation: Option<bool>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct JudgeOptions {
    mode: String,
    #[serde(default)]
    needles: Vec<PythonText>,
}
#[derive(Clone, Serialize)]
#[serde(tag = "operation", rename_all = "lowercase")]
enum Call {
    Judge {
        query: PythonText,
        documents: Vec<PythonText>,
        purpose: String,
    },
    Stem {
        words: Vec<PythonText>,
    },
}
type Calls = Arc<Mutex<Vec<Call>>>;
struct Judge<'a> {
    options: &'a JudgeOptions,
    calls: Calls,
}
impl RelevanceJudge for Judge<'_> {
    fn score(
        &self,
        query: &PythonText,
        documents: &[PythonText],
        purpose: &str,
    ) -> Result<Vec<f64>> {
        self.calls
            .lock()
            .expect("case-local calls")
            .push(Call::Judge {
                query: query.clone(),
                documents: documents.to_vec(),
                purpose: purpose.into(),
            });
        Ok(match self.options.mode.as_str() {
            "contains" => documents
                .iter()
                .map(|doc| {
                    if self.options.needles.iter().all(|word| {
                        word.is_empty()
                            || doc
                                .codepoints()
                                .windows(word.codepoints().len())
                                .any(|part| part == word.codepoints())
                    }) {
                        3.
                    } else {
                        -1.
                    }
                })
                .collect(),
            "ties" => vec![0.; documents.len()],
            "negative" => (0..documents.len()).map(|i| -((i + 1) as f64)).collect(),
            "wrong-size" => vec![0.; documents.len() + 1],
            "nan" => vec![f64::NAN; documents.len()],
            "inf" => vec![f64::INFINITY; documents.len()],
            _ => return Err(invalid("unknown scripted judge")),
        })
    }
}
struct Stem<'a> {
    replacements: &'a BTreeMap<String, PythonText>,
    calls: Calls,
}
impl WordStemmer for Stem<'_> {
    fn stem(&self, word: &PythonText) -> Result<PythonText> {
        Ok(word
            .to_utf8()
            .and_then(|s| self.replacements.get(&s).cloned())
            .unwrap_or_else(|| word.clone()))
    }
    fn stem_words(&self, words: &[PythonText]) -> Result<Vec<PythonText>> {
        self.calls
            .lock()
            .expect("case-local calls")
            .push(Call::Stem {
                words: words.to_vec(),
            });
        words.iter().map(|word| self.stem(word)).collect()
    }
}
#[derive(Serialize)]
struct Observed {
    value: Box<serde_json::value::RawValue>,
    calls: Vec<Call>,
    unchanged: bool,
}
pub fn run(text: &str) -> Observation {
    let calls: Calls = Default::default();
    let mut extra = Observation::new();
    let outcome = (|| -> ScenarioResult<_> {
        let input: Input = serde_json::from_str(text)?;
        let physical = Physical {
            files: input.files,
            owners: Vec::new(),
            symlinks: Vec::new(),
        };
        let scenario = Scenario::new(&physical)?;
        if let Some(mutation) = &input.mutation {
            scenario.mutate(mutation)?;
        }
        let before = input.matches.clone();
        let owner = input
            .matches
            .first()
            .ok_or_else(|| invalid("source observation requires an owner"))?;
        let value = match input.operation.as_str() {
            "verified" => raw(&verified_lines(&scenario.source, owner)?)?,
            "extent" => raw(&entity_extent(owner)?)?,
            "bounds" => {
                let bytes = physical
                    .files
                    .get(&owner.entity.path)
                    .ok_or_else(|| invalid("bounds source missing"))?;
                let text = std::str::from_utf8(bytes)
                    .map_err(|_| invalid("bounds source must be UTF8"))?;
                raw(&source_bounds(
                    owner,
                    owner
                        .evidence
                        .first()
                        .ok_or_else(|| invalid("bounds evidence required"))?,
                    ken_text::unicode::splitlines(text).len(),
                    input.implementation.unwrap_or(true),
                )?)?
            }
            "complete-owner" => raw(&complete_owned_context(owner, &scenario.source)?)?,
            "complete" => raw(&complete_evidence(
                &input.matches,
                &scenario.source,
                &input.request,
            )?)?,
            "refine" => raw(&refine_evidence(
                &input.matches,
                &scenario.source,
                &input.request,
                &Judge {
                    options: &input.judge,
                    calls: calls.clone(),
                },
                &input.options,
            )?)?,
            "lexical" => raw(&refine_source_evidence(
                &input.matches,
                &scenario.source,
                &input.request,
                &input.expanded_query,
                &Stem {
                    replacements: &input.stems,
                    calls: calls.clone(),
                },
            )?)?,
            _ => return Err(invalid("unknown source evidence operation").into()),
        };
        Ok(raw(&Observed {
            value,
            calls: calls.lock().expect("case-local calls").clone(),
            unchanged: input.matches == before,
        })?)
    })();
    if outcome.is_err() {
        extra.insert(
            "calls".into(),
            raw(&*calls.lock().expect("case-local calls")).expect("observed calls"),
        );
    }
    finish_observation(outcome, extra)
}
