use super::scenario::{Mutation, Physical, Scenario};
use super::{Observation, ScenarioResult, finish_observation, invalid, raw};
use ken_retrieval::{
    EntityKey,
    piece_cards::{
        CARD_PROJECTION, PieceCard, build_card, build_piece_cards, canonical_card, card_text,
        validate_card,
    },
    query::CodeMatch,
    source_catalog::{PieceIdentity, SourceCatalog},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use std::sync::Arc;
#[derive(Deserialize)]
pub struct Input {
    pub catalog: Physical,
    pub matches: Vec<CodeMatch>,
    pub piece_kind: String,
    pub query: PythonText,
    pub primary: Option<Value>,
    #[serde(default)]
    pub supporting: Vec<EntityKey>,
    pub limit: Option<usize>,
    pub card_updates: Option<Value>,
    pub mutation: Option<Mutation>,
    pub check_disk: Option<bool>,
}
pub fn parse(text: &str, extra: &[&str]) -> super::Result<Input> {
    super::fields(
        text,
        &[
            "catalog",
            "matches",
            "piece_kind",
            "query",
            "primary",
            "supporting",
            "limit",
            "card_updates",
            "mutation",
            "check_disk",
        ],
        extra,
    )?;
    Ok(serde_json::from_str(text)?)
}
fn patch(value: &mut Value, updates: &Value) -> super::Result<()> {
    let object = updates
        .as_object()
        .ok_or_else(|| invalid("card patch must be an object"))?;
    let target = value
        .as_object_mut()
        .ok_or_else(|| invalid("card patch target must be an object"))?;
    if object.keys().any(|key| !target.contains_key(key)) {
        return Err(invalid("unknown card patch field"));
    }
    target.extend(object.clone());
    Ok(())
}
pub fn update(card: &mut PieceCard, updates: &Value) -> super::Result<()> {
    let object = updates
        .as_object()
        .ok_or_else(|| invalid("card updates must be an object"))?;
    if object
        .keys()
        .any(|k| !["card", "unit", "excerpts", "duplicate"].contains(&k.as_str()))
    {
        return Err(invalid("unknown card update group"));
    }
    let mut value = serde_json::to_value(&*card)?;
    if let Some(v) = updates.get("card") {
        patch(&mut value, v)?;
    }
    if let Some(v) = updates.get("unit") {
        patch(&mut value["unit"], v)?;
    }
    if let Some(excerpts) = updates.get("excerpts") {
        for (index, updates) in excerpts
            .as_object()
            .ok_or_else(|| invalid("excerpt patches must be an object"))?
        {
            let index = index
                .parse::<usize>()
                .map_err(|_| invalid("invalid excerpt patch index"))?;
            let target = value["excerpts"]
                .as_array_mut()
                .and_then(|a| a.get_mut(index))
                .ok_or_else(|| invalid("excerpt patch index outside card"))?;
            patch(target, updates)?;
        }
    }
    if updates.get("duplicate") == Some(&Value::Bool(true)) {
        let first = value["excerpts"]
            .as_array()
            .and_then(|a| a.first())
            .ok_or_else(|| invalid("cannot duplicate an empty card"))?
            .clone();
        value["excerpts"]
            .as_array_mut()
            .expect("card excerpts")
            .push(first);
    }
    *card = serde_json::from_value(value)?;
    Ok(())
}
pub fn build(input: Input) -> ScenarioResult<(Scenario, Arc<SourceCatalog>, Vec<PieceCard>, bool)> {
    let scenario = Scenario::new(&input.catalog)?;
    let catalog = scenario.catalog(input.catalog.owners)?;
    let mut cards = if let Some(primary) = input.primary {
        let primary = if let Some(path) = primary.as_str() {
            PieceIdentity::Path(path.into())
        } else {
            PieceIdentity::Entity(serde_json::from_value(primary)?)
        };
        vec![build_card(
            &primary,
            &input.piece_kind,
            &input.supporting,
            &input.query,
            &catalog,
        )?]
    } else {
        build_piece_cards(
            &input.matches,
            &input.piece_kind,
            &input.query,
            &catalog,
            input.limit.unwrap_or(20),
        )?
    };
    if let Some(updates) = input.card_updates {
        update(
            cards
                .first_mut()
                .ok_or_else(|| invalid("cannot patch an empty card list"))?,
            &updates,
        )?;
    }
    if let Some(mutation) = input.mutation {
        scenario.mutate(&mutation)?;
    }
    Ok((scenario, catalog, cards, input.check_disk.unwrap_or(true)))
}
pub fn run(text: &str) -> Observation {
    let outcome = (|| -> ScenarioResult<_> {
        let input = parse(text, &[])?;
        let (_scenario, catalog, cards, check_disk) = build(input)?;
        for card in &cards {
            validate_card(card, &catalog, check_disk)?;
        }
        let canonical: Vec<_> = cards.iter().map(canonical_card).collect();
        let characters: Vec<_> = canonical.iter().map(|s| s.chars().count()).collect();
        let texts: Vec<_> = cards.iter().map(card_text).collect();
        Ok(raw(
            &json!({"cards":cards,"texts":texts,"canonical":canonical,"characters":characters,"projection":CARD_PROJECTION}),
        )?)
    })();
    finish_observation(outcome, Observation::new())
}
