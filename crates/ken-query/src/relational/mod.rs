//! Relational checking and immutable plans, independent of project execution.
mod comparisons;
mod ir;
mod lower;
mod regex_pattern;
mod scopes;
mod selectors;
mod source_checks;
mod terms;
pub use ir::{
    Edge as RelationalEdge, Node as RelationalNode, OrderedMap, PlanValue, QuotedTerm,
    RelationalQuery, Term,
};
pub use lower::{compile_relational, has_graph};
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub struct CompiledQuery {
    pub program: crate::Program,
    pub relational: Option<std::sync::Arc<RelationalQuery>>,
}
#[derive(serde::Deserialize)]
pub(crate) struct Vocabulary {
    pub kinds: std::collections::BTreeMap<String, String>,
    pub domains: std::collections::BTreeMap<String, String>,
    pub relations: std::collections::BTreeSet<String>,
    pub semantic_attrs: std::collections::BTreeMap<String, Vec<(String, String, String)>>,
}
pub(crate) fn vocabulary() -> &'static Vocabulary {
    static V: std::sync::OnceLock<Vocabulary> = std::sync::OnceLock::new();
    V.get_or_init(|| {
        serde_json::from_str(include_str!("../../resources/relational-capabilities.json"))
            .expect("frozen relational vocabulary")
    })
}

pub(crate) use terms::json_string;
