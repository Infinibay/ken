//! Decode ordered presentation data without treating serde's number protocol as data.
use super::Document;
use serde::{
    Deserialize, Deserializer,
    de::{Error, MapAccess, Visitor},
};
use serde_json::value::RawValue;
struct Fields(Vec<(String, Box<RawValue>)>);
impl<'de> Deserialize<'de> for Fields {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Ordered;
        impl<'de> Visitor<'de> for Ordered {
            type Value = Fields;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("distinct ordered document fields")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Fields, A::Error> {
                let mut fields = Vec::new();
                while let Some((key, value)) = map.next_entry::<String, Box<RawValue>>()? {
                    if fields.iter().any(|(prior, _)| prior == &key) {
                        return Err(A::Error::custom("duplicate public document field"));
                    }
                    fields.push((key, value));
                }
                Ok(Fields(fields))
            }
        }
        deserializer.deserialize_map(Ordered)
    }
}
pub(super) fn parse(raw: &str) -> Result<Document, serde_json::Error> {
    fn node(raw: &RawValue, depth: usize) -> Result<Document, serde_json::Error> {
        if depth > 128 {
            return Err(serde_json::Error::custom(
                "public document nesting budget exhausted",
            ));
        }
        let text = raw.get().trim_start();
        Ok(match text.as_bytes().first() {
            Some(b'{') => Document::Object(
                serde_json::from_str::<Fields>(text)?
                    .0
                    .into_iter()
                    .map(|(key, value)| Ok((key, node(&value, depth + 1)?)))
                    .collect::<Result<_, serde_json::Error>>()?,
            ),
            Some(b'[') => Document::Array(
                serde_json::from_str::<Vec<Box<RawValue>>>(text)?
                    .iter()
                    .map(|value| node(value, depth + 1))
                    .collect::<Result<_, _>>()?,
            ),
            Some(b'"') => Document::String(serde_json::from_str(text)?),
            Some(b'n') => Document::Null,
            Some(b't' | b'f') => Document::Bool(serde_json::from_str(text)?),
            _ => Document::Number(serde_json::from_str(text)?),
        })
    }
    let validated: &RawValue = serde_json::from_str(raw)?;
    node(validated, 0)
}
