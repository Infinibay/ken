//! Native packaged resources and authored graph rules share one compilation policy.
mod compilation;
mod library;
mod publication;
mod rules;
pub use library::RuleLibrary;
pub use rules::SavedRule;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::BTreeMap;
#[derive(Clone, Copy, Debug, Serialize)]
pub struct CatalogSource {
    pub path: &'static str,
    pub text: &'static str,
}
include!(concat!(env!("OUT_DIR"), "/catalog_sources.rs"));
#[derive(Debug, thiserror::Error)]
pub enum CatalogError {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Toml(#[from] toml::de::Error),
    #[error(transparent)]
    TomlSerialization(#[from] toml::ser::Error),
    #[error(transparent)]
    Parse(#[from] ken_query::ParseError),
    #[error(transparent)]
    Execution(#[from] ken_query::execution::ExecutionError),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
}
pub type Result<T> = std::result::Result<T, CatalogError>;
fn invalid(message: impl Into<String>) -> CatalogError {
    CatalogError::Invalid(message.into())
}
#[derive(Clone)]
pub struct Catalog {
    libraries: BTreeMap<String, String>,
    rules: Vec<SavedRule>,
    patterns: Vec<Value>,
}
impl Catalog {
    pub fn sources(&self) -> &'static [CatalogSource] {
        SOURCES
    }
    pub fn libraries(&self) -> &BTreeMap<String, String> {
        &self.libraries
    }
    pub fn rules(&self) -> &[SavedRule] {
        &self.rules
    }
    pub fn pattern_catalog(&self) -> &[Value] {
        &self.patterns
    }
    pub fn packaged() -> Result<Self> {
        if SOURCES.is_empty() {
            return Err(invalid("packaged catalog resources are missing"));
        }
        let mut libraries = BTreeMap::new();
        let mut gof = vec![];
        let mut modern = vec![];
        let mut patterns = vec![];
        for source in SOURCES {
            let data: toml::Value = toml::from_str(source.text)?;
            let data = serde_json::to_value(data)?;
            for entry in std::iter::once(&data)
                .chain(data["variants"].as_array().into_iter().flatten())
                .chain(data["operations"].as_array().into_iter().flatten())
            {
                if let Some(query) = entry["query"]
                    .as_str()
                    .filter(|q| q.trim_start().starts_with("language \"kql/2\""))
                {
                    let tree = ken_query::parse(query, source.path, Default::default())?;
                    libraries.insert(tree.module, query.into());
                }
            }
            if source.path.starts_with("patterns/") {
                let variants = data["variants"].as_array().cloned().unwrap_or_default();
                let mut pattern = json!({
                    "id":data["id"],"name":data["name"],"category":data["category"],
                    "description":data["description"],"query":data["query"].as_str().unwrap_or("").trim(),
                    "query_language":data["query_language"].as_str().unwrap_or("kenql/1"),
                    "executable_variants":variants.iter().filter(|v|v["status"]=="ready").map(|v|v["id"].clone()).collect::<Vec<_>>(),
                    "planned_variants":variants.iter().filter(|v|v["status"]!="ready").map(|v|v["id"].clone()).collect::<Vec<_>>(),
                    "caveat":data["caveat"].as_str().unwrap_or("Structural evidence requires review of intent and runtime behavior."),
                    "variants":variants,"operations":data["operations"].as_array().cloned().unwrap_or_default(),"source":source.path
                });
                if data["legacy_query"]
                    .as_str()
                    .is_some_and(|query| !query.is_empty())
                {
                    pattern["legacy_id"] =
                        json!(format!("legacy.gof.{}", data["id"].as_str().unwrap_or("")));
                }
                patterns.push(pattern);
                let mut selected = serde_json::Map::new();
                for field in [
                    "id",
                    "query",
                    "name",
                    "description",
                    "caveat",
                    "variants",
                    "operations",
                    "query_language",
                ] {
                    if let Some(value) = data.get(field) {
                        selected.insert(field.into(), value.clone());
                    }
                }
                selected.insert("tags".into(), json!(["design", data["category"]]));
                selected.insert("collections".into(), json!(["gof"]));
                selected.insert("source".into(), json!(source.path));
                gof.push(serde_json::from_value(Value::Object(selected))?);
            } else {
                let mut rule: SavedRule = serde_json::from_value(data)?;
                rule.source = source.path.into();
                modern.push(rule);
            }
        }
        let bugs: Vec<SavedRule> =
            serde_json::from_str(include_str!("../../../resources/bugs.json"))?;
        let rules = gof.into_iter().chain(bugs).chain(modern).collect();
        Ok(Self {
            libraries,
            rules,
            patterns,
        })
    }
}
