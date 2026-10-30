use serde::{Deserialize, Serialize};
use serde_json::Value;
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Operand {
    pub kind: String,
    pub r#ref: String,
    #[serde(default)]
    pub role: String,
}
impl Operand {
    pub(super) fn new(kind: &str, reference: impl Into<String>) -> Self {
        Self {
            kind: kind.into(),
            r#ref: reference.into(),
            role: String::new(),
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Instruction {
    pub id: String,
    pub opcode: String,
    pub operands: Vec<Operand>,
    pub result: Option<String>,
    pub source: Value,
    pub effects: Vec<String>,
    pub attrs: Value,
    pub regions: Vec<Region>,
    pub result_type: Value,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Region {
    pub id: String,
    pub kind: String,
    pub instructions: Vec<Instruction>,
    pub outputs: Vec<String>,
}
impl Region {
    pub(super) fn new(id: impl Into<String>, kind: &str) -> Self {
        Self {
            id: id.into(),
            kind: kind.into(),
            instructions: Vec::new(),
            outputs: Vec::new(),
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Place {
    pub name: String,
    #[serde(rename = "type")]
    pub data_type: Value,
    pub source_symbol: Option<String>,
    pub scope: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Function {
    pub id: String,
    pub name: String,
    pub language: String,
    pub parameters: Vec<String>,
    #[serde(with = "places")]
    pub places: Vec<(String, Place)>,
    pub body: Region,
    pub status: String,
    pub reasons: Vec<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Program {
    pub source_version: String,
    pub functions: Vec<Function>,
    pub schema: String,
}
mod places {
    use super::Place;
    use serde::{
        Deserializer, Serializer,
        de::{MapAccess, Visitor},
        ser::SerializeMap,
    };
    pub fn serialize<S: Serializer>(
        values: &[(String, Place)],
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
    ) -> Result<Vec<(String, Place)>, D::Error> {
        struct Ordered;
        impl<'de> Visitor<'de> for Ordered {
            type Value = Vec<(String, Place)>;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("an ordered place map")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
                let mut values: Self::Value = Vec::new();
                while let Some((key, value)) = map.next_entry::<String, Place>()? {
                    if let Some((_, old)) = values.iter_mut().find(|(k, _)| *k == key) {
                        *old = value;
                    } else {
                        values.push((key, value));
                    }
                }
                Ok(values)
            }
        }
        deserializer.deserialize_map(Ordered)
    }
}
