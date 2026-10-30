//! Frozen vocabulary shared by indexed lowering and domain checking.
use serde::Deserialize;
use std::{collections::BTreeMap, sync::OnceLock};
#[derive(Deserialize)]
pub(crate) struct Capabilities {
    pub kinds: BTreeMap<String, Vec<String>>,
    pub types: BTreeMap<String, String>,
    pub properties: BTreeMap<String, BTreeMap<String, String>>,
    pub relations: BTreeMap<String, (String, String, String)>,
    pub unary_relations: BTreeMap<String, (String, String)>,
    pub statement_relations: BTreeMap<String, String>,
    pub statement_unary: BTreeMap<String, (String, String)>,
    pub source_aliases: BTreeMap<String, String>,
    pub optional_roles: BTreeMap<String, String>,
}
pub(crate) fn vocabulary() -> &'static Capabilities {
    static DATA: OnceLock<Capabilities> = OnceLock::new();
    DATA.get_or_init(|| {
        serde_json::from_str(include_str!("../resources/capabilities.json"))
            .expect("frozen compiler vocabulary")
    })
}
pub(crate) fn kind_is(kind: &str, expected: &str) -> bool {
    let c = vocabulary();
    c.kinds
        .get(kind)
        .zip(c.kinds.get(expected))
        .is_some_and(|(a, b)| a.iter().all(|v| b.contains(v)))
}
pub(crate) fn overlap(a: &str, b: &str) -> bool {
    let c = vocabulary();
    c.kinds
        .get(a)
        .zip(c.kinds.get(b))
        .is_some_and(|(a, b)| a.iter().any(|v| b.contains(v)))
}
pub(crate) fn distinct_parameter(a: &str, b: &str) -> bool {
    matches!((a, b), ("param", "receiver") | ("receiver", "param"))
}
pub(crate) fn property_hint(name: &str) -> &'static str {
    match name {
        "parent" => {
            "Use where contains_direct($parent, $child) for an immediate child, or contains($parent, $child) for a descendant."
        }
        "value" => {
            "For syntax literals use kind: \"literal\"; text: \"True\"; (or text: \"None\"; in Python). For value flow use BODY with --backend indexed."
        }
        _ => "Inspect supported properties with ken kql2 --capabilities.",
    }
}
