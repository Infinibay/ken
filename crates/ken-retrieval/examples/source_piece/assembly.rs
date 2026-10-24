use super::scenario::{Physical, Scenario};
use super::{Observation, ScenarioResult, finish_observation, invalid, raw};
use ken_retrieval::{
    EntityKey,
    description::{OwnerDescription, describe_owner},
    piece_candidates::{PieceAssembler, PieceCandidate},
    query::CodeMatch,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    catalog: Physical,
    matches: Vec<CodeMatch>,
    piece_kind: String,
    limit: usize,
    direct: Option<Direct>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Direct {
    kind: String,
    path: String,
    entity: Option<EntityKey>,
    members: Vec<usize>,
    #[serde(default)]
    overrides: BTreeMap<usize, Value>,
}
pub fn run(text: &str) -> Observation {
    let outcome = (|| -> ScenarioResult<_> {
        let input: Input = serde_json::from_str(text)?;
        let scenario = Scenario::new(&input.catalog)?;
        let catalog = scenario.catalog(input.catalog.owners)?;
        if let Some(direct) = input.direct {
            let mut members = direct
                .members
                .iter()
                .map(|i| {
                    catalog
                        .owners()
                        .get(*i)
                        .ok_or_else(|| invalid("source member index outside catalog"))
                        .and_then(|(_, p)| describe_owner(p))
                        .map(Arc::new)
                })
                .collect::<super::Result<Vec<_>>>()?;
            for (index, updates) in direct.overrides {
                let member = members
                    .get_mut(index)
                    .ok_or_else(|| invalid("source member override index outside catalog"))?;
                let mut value = serde_json::to_value(member.as_ref())?;
                let updates = updates
                    .as_object()
                    .ok_or_else(|| invalid("member override must be an object"))?;
                if updates.keys().any(|key| {
                    !value
                        .as_object()
                        .expect("owner description")
                        .contains_key(key)
                }) {
                    return Err(invalid("unknown member override field").into());
                }
                value
                    .as_object_mut()
                    .expect("owner description")
                    .extend(updates.clone());
                *member = Arc::new(serde_json::from_value::<OwnerDescription>(value)?);
            }
            let piece = PieceCandidate::new(
                direct.kind,
                direct.path,
                direct.entity,
                members,
                input.matches,
            )?;
            return Ok(raw(
                &json!({"piece":piece,"declaration":piece.declaration()}),
            )?);
        }
        let mut assembler = PieceAssembler::new(catalog);
        let before = input.matches.clone();
        let pieces = assembler.assemble(&input.matches, &input.piece_kind, input.limit)?;
        let again = assembler.assemble(&input.matches, &input.piece_kind, input.limit)?;
        let reused = pieces.iter().zip(&again).all(|(a, b)| {
            a.members()
                .iter()
                .zip(b.members())
                .all(|(a, b)| Arc::ptr_eq(a, b))
        });
        Ok(raw(
            &json!({"declarations":pieces.iter().map(|p|p.declaration()).collect::<Vec<_>>(),"pieces":pieces,"cache_size":assembler.cache_len(),"reused":reused,"unchanged":input.matches==before}),
        )?)
    })();
    finish_observation(outcome, Observation::new())
}
