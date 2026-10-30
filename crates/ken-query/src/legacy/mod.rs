//! The line-oriented legacy graph language, independent of KQL2 compilation.
//!
//! Parsing preserves legacy shlex term semantics: quotes group tokens but do
//! not turn `$role`, `@unit`, `_` or alternatives into literal endpoints.
mod parser;
mod selectors;
pub use selectors::parse_query;
mod runtime;
pub use parser::parse_pattern;
pub use runtime::execute;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// A lossless nonnegative cardinality, serialized as a JSON integer. Keeping
/// its decimal spelling avoids imposing machine-word limits on authored counts.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Count(String);
impl Count {
    pub fn from_decimal(value: &str) -> Option<Self> {
        let value = parser::decimal(value)?;
        let value = value.trim_start_matches('0');
        Some(Self(if value.is_empty() {
            "0".into()
        } else {
            value.into()
        }))
    }
}
impl From<u64> for Count {
    fn from(value: u64) -> Self {
        Self(value.to_string())
    }
}
impl std::fmt::Display for Count {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}
impl Serialize for Count {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        use serde::ser::Error;
        serde_json::value::RawValue::from_string(self.0.clone())
            .map_err(S::Error::custom)?
            .serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Count {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        use serde::de::Error;
        let raw = Box::<serde_json::value::RawValue>::deserialize(deserializer)?;
        Self::from_decimal(raw.get())
            .ok_or_else(|| D::Error::custom("count must be a nonnegative integer"))
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Clause {
    pub mode: String,
    pub subject: String,
    pub relation: String,
    pub object: String,
    pub attrs: Vec<(String, String, String)>,
    pub minimum: usize,
    pub maximum: usize,
    pub count_op: String,
    pub count: Count,
    pub distinct: String,
    pub r#where: Vec<Clause>,
    pub capability: String,
}
#[derive(Clone, Debug, PartialEq)]
pub struct Pattern {
    pub name: String,
    pub clauses: Vec<Clause>,
    pub different: Vec<(String, String)>,
    pub capabilities: BTreeSet<String>,
    pub variants: BTreeMap<String, Vec<Clause>>,
    /// Insertion order affects stable result ordering and budget prefixes.
    pub variant_order: Vec<String>,
}
// JSON maps preserve the authored variant order even when a Pattern crosses
// a host boundary. BTreeMap alone would change tied matches and budget prefixes.
impl Serialize for Pattern {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        use serde::ser::{SerializeMap, SerializeStruct};
        struct Ordered<'a>(&'a Pattern);
        impl Serialize for Ordered<'_> {
            fn serialize<S: serde::Serializer>(
                &self,
                serializer: S,
            ) -> std::result::Result<S::Ok, S::Error> {
                let mut map = serializer.serialize_map(Some(self.0.variants.len()))?;
                for name in self.0.ordered_variants() {
                    map.serialize_entry(name, &self.0.variants[name])?;
                }
                map.end()
            }
        }
        let mut state = serializer.serialize_struct("Pattern", 5)?;
        state.serialize_field("name", &self.name)?;
        state.serialize_field("clauses", &self.clauses)?;
        state.serialize_field("different", &self.different)?;
        state.serialize_field("capabilities", &self.capabilities)?;
        state.serialize_field("variants", &Ordered(self))?;
        state.end()
    }
}
impl<'de> Deserialize<'de> for Pattern {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        struct Ordered(Vec<(String, Vec<Clause>)>);
        impl<'de> Deserialize<'de> for Ordered {
            fn deserialize<D: serde::Deserializer<'de>>(
                deserializer: D,
            ) -> std::result::Result<Self, D::Error> {
                struct Visitor;
                impl<'de> serde::de::Visitor<'de> for Visitor {
                    type Value = Ordered;
                    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                        f.write_str("legacy variants map")
                    }
                    fn visit_map<M: serde::de::MapAccess<'de>>(
                        self,
                        mut map: M,
                    ) -> std::result::Result<Ordered, M::Error> {
                        let mut values = vec![];
                        while let Some(value) = map.next_entry()? {
                            values.push(value);
                        }
                        Ok(Ordered(values))
                    }
                }
                deserializer.deserialize_map(Visitor)
            }
        }
        #[derive(Deserialize)]
        struct Fields {
            name: String,
            clauses: Vec<Clause>,
            different: Vec<(String, String)>,
            capabilities: BTreeSet<String>,
            variants: Ordered,
        }
        let fields = Fields::deserialize(deserializer)?;
        let variant_order = fields
            .variants
            .0
            .iter()
            .map(|(name, _)| name.clone())
            .collect();
        Ok(Self {
            name: fields.name,
            clauses: fields.clauses,
            different: fields.different,
            capabilities: fields.capabilities,
            variants: fields.variants.0.into_iter().collect(),
            variant_order,
        })
    }
}
impl Pattern {
    fn ordered_variants(&self) -> Vec<&String> {
        let mut result = vec![];
        for name in &self.variant_order {
            if self.variants.contains_key(name) && !result.contains(&name) {
                result.push(name);
            }
        }
        for name in self.variants.keys() {
            if !result.contains(&name) {
                result.push(name);
            }
        }
        result
    }
}
impl Default for Pattern {
    fn default() -> Self {
        Self {
            name: "query".into(),
            clauses: vec![],
            different: vec![],
            capabilities: BTreeSet::new(),
            variants: BTreeMap::new(),
            variant_order: vec![],
        }
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LegacyFact {
    pub subject: String,
    pub relation: String,
    pub object: String,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LegacyMatch {
    pub pattern: String,
    pub variant: String,
    pub bindings: BTreeMap<String, String>,
    pub status: String,
    pub unknown: Vec<String>,
    pub optional_hits: usize,
    pub optional_total: usize,
    pub evidence_score: f64,
    pub evidence: Vec<String>,
    pub facts: Vec<LegacyFact>,
}
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct LegacyStats {
    pub rows_examined: u64,
    pub states: u64,
    pub path_edges: u64,
    pub relations: BTreeMap<String, u64>,
    pub elapsed_ms: f64,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LegacyOutcome {
    pub matches: Vec<LegacyMatch>,
    pub complete: bool,
    pub unknown: Vec<String>,
    pub stats: LegacyStats,
}
pub(super) fn variable(term: &str) -> bool {
    term.starts_with('$') || term == "@unit"
}
