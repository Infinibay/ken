//! Diagnostic JSON keeps IEEE categories explicit instead of replacing them with null.
use serde::{Deserialize, Deserializer, Serializer};
use serde_json::{Value, json};
pub(crate) fn value(number: f64) -> Value {
    if number.is_finite() {
        json!(number)
    } else {
        json!({"$float": if number.is_nan() {"nan"} else if number.is_sign_positive() {"inf"} else {"-inf"}})
    }
}
pub(crate) fn read(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .or_else(|| match value.get("$float")?.as_str()? {
            "nan" => Some(f64::NAN),
            "inf" => Some(f64::INFINITY),
            "-inf" => Some(f64::NEG_INFINITY),
            _ => None,
        })
}
pub(crate) fn serialize<S: Serializer>(number: &f64, serializer: S) -> Result<S::Ok, S::Error> {
    serde::Serialize::serialize(&value(*number), serializer)
}
pub(crate) fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<f64, D::Error> {
    read(&Value::deserialize(deserializer)?)
        .ok_or_else(|| serde::de::Error::custom("expected a number or IEEE diagnostic tag"))
}
