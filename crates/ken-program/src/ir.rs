//! Ordered, versioned input records; uninterpreted attributes stay lossless.
use crate::ProgramError;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use std::collections::{BTreeMap, BTreeSet};
pub type Attributes = BTreeMap<String, Box<RawValue>>;
pub const IR_VERSION: &str = "1.88.0";
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Entity {
    pub id: String,
    pub kind: String,
    pub name: String,
    pub path: String,
    pub line: i64,
    pub end_line: i64,
    #[serde(default)]
    pub attrs: Attributes,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Operation {
    pub id: String,
    pub kind: String,
    pub native_kind: String,
    #[serde(deserialize_with = "crate::nullable")]
    pub parent: Option<String>,
    pub role: String,
    pub start: i64,
    pub end: i64,
    pub line: i64,
    pub owner: String,
    #[serde(default)]
    pub attrs: Attributes,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Fact {
    pub subject: String,
    pub relation: String,
    pub object: String,
    #[serde(default)]
    pub attrs: Attributes,
    #[serde(default)]
    pub evidence: Vec<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StructuralIr {
    pub path: String,
    pub language: String,
    #[serde(with = "ordered_entities")]
    pub entities: Vec<(String, Entity)>,
    pub operations: Vec<Operation>,
    pub facts: Vec<Fact>,
    pub capabilities: BTreeSet<String>,
    pub diagnostics: Vec<String>,
    pub version: String,
    #[serde(default)]
    pub relations: BTreeSet<String>,
    #[serde(default = "source_view")]
    pub view: String,
}
fn source_view() -> String {
    "source".into()
}
impl StructuralIr {
    pub fn from_json(data: &str) -> Result<Self, ProgramError> {
        let result: Self = serde_json::from_str(data)?;
        if result.version != IR_VERSION {
            return Err(ProgramError::Invalid("incompatible IR version"));
        }
        Ok(result)
    }
}
mod ordered_entities {
    use super::Entity;
    use serde::{
        Deserializer, Serializer,
        de::{MapAccess, Visitor},
        ser::SerializeMap,
    };
    pub fn serialize<S: Serializer>(
        values: &[(String, Entity)],
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(values.len()))?;
        for (key, value) in values {
            map.serialize_entry(key, value)?;
        }
        map.end()
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Vec<(String, Entity)>, D::Error> {
        struct Ordered;
        impl<'de> Visitor<'de> for Ordered {
            type Value = Vec<(String, Entity)>;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("ordered entity object")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
                let mut values: Self::Value = Vec::new();
                let mut positions = std::collections::BTreeMap::<String, usize>::new();
                while let Some((key, value)) = map.next_entry::<String, Entity>()? {
                    if let Some(&position) = positions.get(&key) {
                        values[position].1 = value;
                    } else {
                        positions.insert(key.clone(), values.len());
                        values.push((key, value));
                    }
                }
                Ok(values)
            }
        }
        deserializer.deserialize_map(Ordered)
    }
}
