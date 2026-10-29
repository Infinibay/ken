use super::{Result, StructuralError};
use rusqlite::types::{Value, ValueRef};
use serde::{Serialize, Serializer};
use serde_json::value::RawValue;
/// Integers retain decimal text so values beyond SQLite's i64 are lossless.
#[derive(Clone, Debug, PartialEq)]
pub enum Scalar {
    String(String),
    Int(String),
    Float(f64),
    Bool(bool),
    Null,
}
impl Serialize for Scalar {
    fn serialize<S: Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        match self {
            Self::String(v) => s.serialize_str(v),
            Self::Int(v) => RawValue::from_string(v.clone())
                .map_err(serde::ser::Error::custom)?
                .serialize(s),
            Self::Float(v) => s.serialize_f64(*v),
            Self::Bool(v) => s.serialize_bool(*v),
            Self::Null => s.serialize_none(),
        }
    }
}
impl Scalar {
    pub fn from_raw(raw: &RawValue) -> Result<Option<Self>> {
        let s = raw.get().trim();
        Ok(match s.as_bytes().first() {
            Some(b'"') => Some(Self::String(serde_json::from_str(s)?)),
            Some(b't') => Some(Self::Bool(true)),
            Some(b'f') => Some(Self::Bool(false)),
            Some(b'n') => Some(Self::Null),
            Some(b'-' | b'0'..=b'9') => {
                if s.contains(['.', 'e', 'E']) {
                    let value: f64 = s
                        .parse()
                        .map_err(|_| StructuralError::Invalid("unsupported scalar"))?;
                    if !value.is_finite() {
                        None
                    } else {
                        Some(Self::Float(value))
                    }
                } else {
                    Some(Self::Int(s.into()))
                }
            }
            _ => None,
        })
    }
    pub(super) fn database(&self) -> (&'static str, Value) {
        match self {
            Self::String(v) => ("String", Value::Text(v.clone())),
            Self::Int(v) => (
                "Int",
                v.parse::<i64>()
                    .map_or_else(|_| Value::Text(v.clone()), Value::Integer),
            ),
            Self::Float(v) if *v == 0.0 && v.is_sign_negative() => {
                ("Float", Value::Text("-0.0".into()))
            }
            Self::Float(v) => ("Float", Value::Real(*v)),
            Self::Bool(v) => ("Bool", Value::Integer(i64::from(*v))),
            Self::Null => ("Null", Value::Null),
        }
    }
    pub(super) fn decode(tag: &str, v: ValueRef<'_>) -> Result<Self> {
        let text = || -> Result<String> {
            Ok(match v {
                ValueRef::Text(s) => std::str::from_utf8(s)
                    .map_err(|_| StructuralError::Invalid("invalid scalar text"))?
                    .into(),
                ValueRef::Integer(n) => n.to_string(),
                ValueRef::Real(n) => n.to_string(),
                _ => return Err(StructuralError::Invalid("invalid scalar storage")),
            })
        };
        Ok(match tag {
            "String" => Self::String(text()?),
            "Int" => Self::Int(text()?),
            "Float" => Self::Float(
                text()?
                    .parse()
                    .map_err(|_| StructuralError::Invalid("invalid float property"))?,
            ),
            "Bool" => Self::Bool(match v {
                ValueRef::Integer(n) => n != 0,
                ValueRef::Real(n) => n != 0.,
                ValueRef::Text(s) => !s.is_empty(),
                _ => false,
            }),
            "Null" => Self::Null,
            _ => return Err(StructuralError::Invalid("unsupported scalar tag")),
        })
    }
}
pub(super) fn truthy(raw: &RawValue) -> bool {
    match serde_json::from_str::<serde_json::Value>(raw.get()) {
        Ok(v) => match v {
            serde_json::Value::Null => false,
            serde_json::Value::Bool(b) => b,
            serde_json::Value::Number(n) => n.as_f64() != Some(0.),
            serde_json::Value::String(s) => !s.is_empty(),
            serde_json::Value::Array(v) => !v.is_empty(),
            serde_json::Value::Object(v) => !v.is_empty(),
        },
        Err(_) => true,
    }
}
