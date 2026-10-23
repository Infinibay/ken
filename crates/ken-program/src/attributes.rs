//! Python-compatible scalar coercion at the structural attribute boundary.
use crate::{Attributes, ProgramError};
use serde_json::Value;
pub(crate) fn get(attrs: &Attributes, key: &str) -> Result<Option<Value>, ProgramError> {
    attrs
        .get(key)
        .map(|v| serde_json::from_str(v.get()).map_err(ProgramError::from))
        .transpose()
}
pub(crate) fn text(attrs: &Attributes, key: &str, default: &str) -> Result<String, ProgramError> {
    Ok(get(attrs, key)?.map_or_else(|| default.into(), |v| spelling(&v)))
}
pub(crate) fn truth(attrs: &Attributes, key: &str) -> Result<bool, ProgramError> {
    Ok(get(attrs, key)?.is_some_and(|v| truth_value(&v)))
}
pub(crate) fn truth_value(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
        Value::Number(v) => v.as_f64() != Some(0.0),
    }
}
pub(crate) fn integer(attrs: &Attributes, key: &str, default: i64) -> Result<i64, ProgramError> {
    match get(attrs, key)? {
        None => Ok(default),
        Some(Value::Number(n)) => n
            .as_i64()
            .ok_or(ProgramError::Invalid("invalid integer attribute")),
        _ => Err(ProgramError::Invalid("invalid integer attribute")),
    }
}
pub(crate) fn tokens(attrs: &Attributes) -> Result<Vec<String>, ProgramError> {
    match get(attrs, "tokens")? {
        None => Ok(Vec::new()),
        Some(Value::Array(v)) => Ok(v.iter().map(spelling).collect()),
        Some(Value::String(v)) => Ok(v.chars().map(|c| c.to_string()).collect()),
        Some(Value::Object(v)) => Ok(v.keys().cloned().collect()),
        _ => Err(ProgramError::Invalid("tokens must be iterable")),
    }
}
fn spelling(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(v) => {
            if *v {
                "True".into()
            } else {
                "False".into()
            }
        }
        Value::String(v) => v.clone(),
        Value::Number(v) => v.to_string(),
        Value::Array(v) => format!("[{}]", v.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(v) => format!(
            "{{{}}}",
            v.iter()
                .map(|(k, v)| format!("{}: {}", repr(&Value::String(k.clone())), repr(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}
fn repr(v: &Value) -> String {
    if let Value::String(v) = v {
        let escaped = v
            .replace('\\', "\\\\")
            .replace('\'', "\\'")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
            .replace('\t', "\\t");
        format!("'{escaped}'")
    } else {
        spelling(v)
    }
}
