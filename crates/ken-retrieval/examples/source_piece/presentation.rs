use super::cards;
use super::scenario::{Mutation, Physical, Scenario};
use super::{Observation, ScenarioResult, fields, finish_observation, invalid, raw};
use ken_retrieval::{
    presentation::{present, present_cards},
    query::{CodeMatch, SearchRequest},
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
#[derive(Deserialize)]
struct Input {
    operation: String,
    profile_version: String,
    request: SearchRequest,
    #[serde(default)]
    matches: Vec<CodeMatch>,
    files: Option<BTreeMap<String, Vec<u8>>>,
    mutation: Option<Mutation>,
}
#[derive(Serialize)]
struct Observed {
    response: ken_retrieval::presentation::SearchResponse,
    characters: usize,
}
pub fn run(text: &str) -> Observation {
    let outcome = (|| -> ScenarioResult<_> {
        let input: Input = serde_json::from_str(text)?;
        let (mut response, scenario) = match input.operation.as_str() {
            "cards" => {
                let plan = cards::parse(text, &["operation", "profile_version", "request"])?;
                let (scenario, catalog, cards, _) = cards::build(plan)?;
                (
                    present_cards(&cards, &input.request, &catalog, &input.profile_version)?,
                    scenario,
                )
            }
            "owners" => {
                fields(
                    text,
                    &[
                        "operation",
                        "profile_version",
                        "request",
                        "matches",
                        "files",
                        "mutation",
                    ],
                    &[],
                )?;
                let physical = Physical {
                    files: input
                        .files
                        .ok_or_else(|| invalid("presentation files required"))?,
                    owners: Vec::new(),
                    symlinks: Vec::new(),
                };
                let scenario = Scenario::new(&physical)?;
                if let Some(mutation) = input.mutation {
                    scenario.mutate(&mutation)?;
                }
                (
                    present(
                        &input.matches,
                        &scenario.source,
                        &input.request,
                        &input.profile_version,
                    )?,
                    scenario,
                )
            }
            _ => return Err(invalid("unknown source presentation operation").into()),
        };
        for warning in &mut response.warnings {
            *warning = scenario.normalize(warning);
        }
        let characters = response.python_characters();
        Ok(raw(&Observed {
            response,
            characters,
        })?)
    })();
    finish_observation(outcome, Observation::new())
}
