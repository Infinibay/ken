//! Ordered public documents and their compact text projection.
mod json;
mod text;
use serde::{
    Deserialize, Deserializer, Serialize, Serializer,
    de::{MapAccess, SeqAccess, Visitor},
    ser::{SerializeMap, SerializeSeq},
};
use serde_json::Number;
use std::fmt;
pub use text::render;

#[derive(Clone, Debug, PartialEq)]
pub enum Document {
    Null,
    Bool(bool),
    Number(Number),
    String(String),
    Array(Vec<Document>),
    Object(Vec<(String, Document)>),
}
impl Document {
    /// Preserve source field order, arbitrary JSON numbers and ordinary object keys.
    pub fn parse_json(raw: &str) -> Result<Self, serde_json::Error> {
        json::parse(raw)
    }
    pub fn object(fields: impl IntoIterator<Item = (impl Into<String>, Document)>) -> Self {
        Self::Object(fields.into_iter().map(|(k, v)| (k.into(), v)).collect())
    }
    pub fn get(&self, key: &str) -> &Self {
        static NULL: Document = Document::Null;
        match self {
            Self::Object(fields) => fields
                .iter()
                .find(|(k, _)| k == key)
                .map_or(&NULL, |(_, v)| v),
            _ => &NULL,
        }
    }
    pub fn string(&self) -> Option<&str> {
        if let Self::String(value) = self {
            Some(value)
        } else {
            None
        }
    }
    pub fn integer(&self) -> Option<i64> {
        if let Self::Number(value) = self {
            value.as_i64()
        } else {
            None
        }
    }
    pub fn array(&self) -> &[Self] {
        if let Self::Array(value) = self {
            value
        } else {
            &[]
        }
    }
    pub fn fields(&self) -> &[(String, Self)] {
        if let Self::Object(value) = self {
            value
        } else {
            &[]
        }
    }
    pub fn truthy(&self) -> bool {
        match self {
            Self::Null => false,
            Self::Bool(v) => *v,
            Self::Number(v) => v.as_f64() != Some(0.),
            Self::String(v) => !v.is_empty(),
            Self::Array(v) => !v.is_empty(),
            Self::Object(v) => !v.is_empty(),
        }
    }
    pub fn is_empty(&self) -> bool {
        matches!(self, Self::Null)
            || match self {
                Self::String(v) => v.is_empty(),
                Self::Array(v) => v.is_empty(),
                Self::Object(v) => v.is_empty(),
                _ => false,
            }
    }
    pub fn insert(&mut self, key: impl Into<String>, value: impl Into<Self>) {
        let Self::Object(fields) = self else {
            panic!("object fields required")
        };
        let key = key.into();
        let value = value.into();
        if let Some((_, old)) = fields.iter_mut().find(|(k, _)| k == &key) {
            *old = value;
        } else {
            fields.push((key, value));
        }
    }
}
impl From<&str> for Document {
    fn from(v: &str) -> Self {
        Self::String(v.into())
    }
}
impl From<String> for Document {
    fn from(v: String) -> Self {
        Self::String(v)
    }
}
impl From<bool> for Document {
    fn from(v: bool) -> Self {
        Self::Bool(v)
    }
}
impl From<i64> for Document {
    fn from(v: i64) -> Self {
        Self::Number(v.into())
    }
}
impl From<usize> for Document {
    fn from(v: usize) -> Self {
        Self::Number(v.into())
    }
}
impl From<f64> for Document {
    fn from(v: f64) -> Self {
        Number::from_f64(v).map_or(Self::Null, Self::Number)
    }
}
impl<T: Into<Document>> From<Option<T>> for Document {
    fn from(v: Option<T>) -> Self {
        v.map_or(Self::Null, Into::into)
    }
}
impl<T: Into<Document>> From<Vec<T>> for Document {
    fn from(v: Vec<T>) -> Self {
        Self::Array(v.into_iter().map(Into::into).collect())
    }
}
impl Serialize for Document {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Null => s.serialize_none(),
            Self::Bool(v) => s.serialize_bool(*v),
            Self::Number(v) => v.serialize(s),
            Self::String(v) => s.serialize_str(v),
            Self::Array(v) => {
                let mut seq = s.serialize_seq(Some(v.len()))?;
                for x in v {
                    seq.serialize_element(x)?;
                }
                seq.end()
            }
            Self::Object(v) => {
                let mut map = s.serialize_map(Some(v.len()))?;
                for (k, x) in v {
                    map.serialize_entry(k, x)?;
                }
                map.end()
            }
        }
    }
}
impl<'de> Deserialize<'de> for Document {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct Ordered;
        impl<'de> Visitor<'de> for Ordered {
            type Value = Document;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("ordered public JSON data")
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Document, E> {
                Ok(Document::Null)
            }
            fn visit_none<E: serde::de::Error>(self) -> Result<Document, E> {
                Ok(Document::Null)
            }
            fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Document, E> {
                Ok(v.into())
            }
            fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Document, E> {
                Ok(v.into())
            }
            fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Document, E> {
                Ok(Document::Number(v.into()))
            }
            fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Document, E> {
                Ok(v.into())
            }
            fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Document, E> {
                Ok(v.into())
            }
            fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Document, E> {
                Ok(v.into())
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Document, A::Error> {
                let mut v = Vec::new();
                while let Some(x) = a.next_element()? {
                    v.push(x);
                }
                Ok(Document::Array(v))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut a: A) -> Result<Document, A::Error> {
                let mut v: Vec<(String, Document)> = Vec::new();
                while let Some((k, x)) = a.next_entry()? {
                    if v.iter().any(|(old, _)| old == &k) {
                        return Err(serde::de::Error::custom("duplicate public document field"));
                    }
                    v.push((k, x));
                }
                Ok(Document::Object(v))
            }
        }
        d.deserialize_any(Ordered)
    }
}
