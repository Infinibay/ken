//! Reject ambiguous declaration objects without interpreting model semantics.
use serde::{
    Deserialize, Deserializer,
    de::{self, MapAccess, SeqAccess, Visitor},
};
use std::{collections::BTreeSet, fmt};
struct Distinct;
impl<'de> Deserialize<'de> for Distinct {
    fn deserialize<D: Deserializer<'de>>(input: D) -> Result<Self, D::Error> {
        struct Object;
        impl<'de> Visitor<'de> for Object {
            type Value = Distinct;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("unambiguous JSON declaration")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
                let mut names = BTreeSet::new();
                while let Some(name) = map.next_key::<String>()? {
                    if !names.insert(name) {
                        return Err(de::Error::custom("duplicate catalogue declaration field"));
                    }
                    map.next_value::<Distinct>()?;
                }
                Ok(Distinct)
            }
            fn visit_seq<S: SeqAccess<'de>>(self, mut seq: S) -> Result<Self::Value, S::Error> {
                while seq.next_element::<Distinct>()?.is_some() {}
                Ok(Distinct)
            }
            fn visit_bool<E: de::Error>(self, _: bool) -> Result<Self::Value, E> {
                Ok(Distinct)
            }
            fn visit_str<E: de::Error>(self, _: &str) -> Result<Self::Value, E> {
                Ok(Distinct)
            }
            fn visit_i64<E: de::Error>(self, _: i64) -> Result<Self::Value, E> {
                Ok(Distinct)
            }
            fn visit_u64<E: de::Error>(self, _: u64) -> Result<Self::Value, E> {
                Ok(Distinct)
            }
            fn visit_f64<E: de::Error>(self, _: f64) -> Result<Self::Value, E> {
                Ok(Distinct)
            }
            fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(Distinct)
            }
            fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(Distinct)
            }
        }
        input.deserialize_any(Object)
    }
}
pub(super) fn validate(raw: &str) -> Result<(), serde_json::Error> {
    let mut input = serde_json::Deserializer::from_str(raw);
    Distinct::deserialize(&mut input)?;
    input.end()
}
