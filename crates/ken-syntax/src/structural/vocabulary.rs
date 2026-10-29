//! Original structural grammar vocabulary; broader parser registries are not equivalent.
use serde::Deserialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::OnceLock,
};
#[derive(Deserialize)]
pub(super) struct Vocabulary {
    pub types: BTreeSet<String>,
    pub functions: BTreeSet<String>,
    pub calls: BTreeSet<String>,
    pub assignments: BTreeSet<String>,
    pub members: BTreeSet<String>,
    pub loops: BTreeSet<String>,
    pub branches: BTreeSet<String>,
    pub operator_nodes: BTreeSet<String>,
    pub operators: BTreeSet<String>,
    pub file_declarations: BTreeSet<String>,
    pub spec_declarations: BTreeMap<String, String>,
}
pub(super) fn vocabulary() -> &'static Vocabulary {
    static VOCABULARY: OnceLock<Vocabulary> = OnceLock::new();
    VOCABULARY.get_or_init(|| {
        serde_json::from_str(include_str!("vocabulary.json"))
            .expect("frozen source-operation vocabulary")
    })
}
pub(super) fn fallback(native: &str) -> &'static str {
    [
        ("yield", "YIELD"),
        ("await", "AWAIT"),
        ("return", "RETURN"),
        ("import", "IMPORT"),
        ("export", "EXPORT"),
        ("use_declaration", "IMPORT"),
        ("type_parameter", "TYPE_PARAMETER"),
        ("match", "MATCH"),
        ("switch", "MATCH"),
        ("with_statement", "RESOURCE_SCOPE"),
        ("using_statement", "RESOURCE_SCOPE"),
        ("try", "TRY"),
        ("throw", "THROW"),
        ("raise", "THROW"),
        ("decorator", "DECORATOR"),
        ("splat", "SPREAD"),
        ("spread", "SPREAD"),
        ("rest_pattern", "VARIADIC"),
    ]
    .into_iter()
    .find_map(|(token, label)| native.contains(token).then_some(label))
    .unwrap_or("NATIVE")
}
pub(super) fn comparison(token: &str) -> bool {
    matches!(
        token,
        "<" | ">"
            | "<="
            | ">="
            | "=="
            | "!="
            | "==="
            | "!=="
            | "<=>"
            | "in"
            | "not in"
            | "is"
            | "is not"
    )
}
pub(super) fn short_circuit(token: &str) -> bool {
    matches!(
        token,
        "and" | "or" | "&&" | "||" | "??" | "&&=" | "||=" | "??="
    )
}
