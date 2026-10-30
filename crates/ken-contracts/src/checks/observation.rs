//! Opaque result values and detached admission facts. Serde owns JSON parsing;
//! rows/evidence never pass through Rust's Unicode-scalar JSON Value model.
use super::{Result, invalid};
use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use serde_json::{Value, value::RawValue};
use std::collections::BTreeMap;
pub(super) type Fields = BTreeMap<String, Box<RawValue>>;
pub(super) fn fields(raw: &RawValue) -> Result<Fields> {
    Ok(serde_json::from_str(raw.get())?)
}
pub(super) fn decode<T: serde::de::DeserializeOwned>(raw: &RawValue) -> Result<T> {
    Ok(serde_json::from_str(raw.get())?)
}
pub(super) fn raw<T: Serialize + ?Sized>(value: &T) -> Result<Box<RawValue>> {
    Ok(serde_json::value::to_raw_value(value)?)
}
pub(super) fn take<T: serde::de::DeserializeOwned>(fields: &mut Fields, key: &str) -> Result<T> {
    decode(
        &fields
            .remove(key)
            .ok_or_else(|| invalid(format!("missing receipt field: {key}")))?,
    )
}
pub(super) fn optional<T: serde::de::DeserializeOwned>(
    fields: &mut Fields,
    key: &str,
) -> Result<Option<T>> {
    fields.remove(key).map(|v| decode(&v)).transpose()
}
pub(super) fn truth(raw: &RawValue) -> bool {
    let text = raw.get().trim();
    match text.as_bytes().first() {
        Some(b'n' | b'f') => false,
        Some(b't') => true,
        Some(b'"') => text != "\"\"",
        Some(b'[') => decode::<Vec<Box<RawValue>>>(raw).is_ok_and(|v| !v.is_empty()),
        Some(b'{') => fields(raw).is_ok_and(|v| !v.is_empty()),
        _ => text.parse::<f64>().is_ok_and(|v| v != 0.),
    }
}
#[derive(Clone, Debug, Default)]
pub struct Admission {
    pub complete: Option<bool>,
    pub coverage_complete: Option<bool>,
    pub results_truncated: Option<bool>,
    pub unknown_candidates: Option<u64>,
    pub row_count: Option<usize>,
    pub has_reason: bool,
}
impl Admission {
    pub fn determinate(&self) -> bool {
        self.complete == Some(true)
            && self.coverage_complete == Some(true)
            && self.results_truncated == Some(false)
            && self.unknown_candidates == Some(0)
            && self.row_count.is_some()
            && !self.has_reason
    }
}
#[derive(Clone, Debug)]
pub struct Observation {
    fields: Fields,
    admission: Admission,
}
impl Observation {
    pub fn parse(json: &str) -> Result<Self> {
        let fields: Fields = serde_json::from_str(json)?;
        let mut result = Self {
            fields,
            admission: Admission::default(),
        };
        result.refresh();
        Ok(result)
    }
    pub fn from_json(value: &Value) -> Result<Self> {
        Self::parse(&serde_json::to_string(value)?)
    }
    pub fn unknown(reason: impl Into<String>) -> Self {
        Self::from_json(&serde_json::json!({"rows":[],"complete":false,"coverage_complete":false,"unknown_candidates":0,"reason":reason.into()})).expect("fixed unknown result")
    }
    fn refresh(&mut self) {
        let value = |key: &str| self.fields.get(key).map(Box::as_ref);
        self.admission = Admission {
            complete: value("complete").and_then(|v| decode(v).ok()),
            coverage_complete: value("coverage_complete").and_then(|v| decode(v).ok()),
            results_truncated: value("results_truncated").and_then(|v| decode(v).ok()),
            unknown_candidates: value("unknown_candidates").and_then(|v| decode(v).ok()),
            row_count: value("rows")
                .and_then(|v| decode::<Vec<Box<RawValue>>>(v).ok())
                .map(|v| v.len()),
            has_reason: value("reason").is_some_and(truth),
        };
    }
    pub fn admission(&self) -> &Admission {
        &self.admission
    }
    pub fn row_count(&self) -> Option<usize> {
        self.admission.row_count
    }
    pub fn field(&self, key: &str) -> Option<&RawValue> {
        self.fields.get(key).map(Box::as_ref)
    }
    pub fn metadata(&self, key: &str) -> Result<Option<Value>> {
        self.field(key).map(decode).transpose()
    }
    pub fn set<T: Serialize + ?Sized>(&mut self, key: &str, value: &T) -> Result<()> {
        self.fields.insert(key.into(), raw(value)?);
        self.refresh();
        Ok(())
    }
    pub fn invalidate(&mut self, reason: &str) {
        self.set("complete", &false).expect("boolean metadata");
        self.set("reason", reason).expect("reason metadata");
    }
    pub fn to_json(&self) -> Result<Value> {
        Ok(serde_json::from_str(&serde_json::to_string(self)?)?)
    }
}
impl Serialize for Observation {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        self.fields.serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Observation {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        let value = Box::<RawValue>::deserialize(deserializer)?;
        Self::parse(value.get()).map_err(D::Error::custom)
    }
}
pub fn judgment_observation(result: &Observation, expectation: &str) -> String {
    if !result.admission.determinate() {
        return "unknown".into();
    }
    if (result.row_count().unwrap_or(0) > 0) == (expectation == "some_match") {
        "pass"
    } else {
        "fail"
    }
    .into()
}
#[derive(Clone, Debug, Serialize)]
pub struct CheckObservation {
    pub rule: String,
    pub description: String,
    pub revision: String,
    pub path: String,
    pub query: String,
    pub libraries: BTreeMap<String, String>,
    pub expectation: String,
    pub status: String,
    pub engine: String,
    pub result: Observation,
    #[serde(flatten)]
    pub extra: Fields,
}
impl<'de> Deserialize<'de> for CheckObservation {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        let value = Box::<RawValue>::deserialize(deserializer)?;
        let parse = || -> Result<Self> {
            let mut f = fields(&value)?;
            Ok(Self {
                rule: take(&mut f, "rule")?,
                description: take(&mut f, "description")?,
                revision: optional(&mut f, "revision")?.unwrap_or_default(),
                path: take(&mut f, "path")?,
                query: optional(&mut f, "query")?.unwrap_or_default(),
                libraries: optional(&mut f, "libraries")?.unwrap_or_default(),
                expectation: take(&mut f, "expectation")?,
                status: take(&mut f, "status")?,
                engine: optional(&mut f, "engine")?.unwrap_or_default(),
                result: take(&mut f, "result")?,
                extra: f,
            })
        };
        parse().map_err(D::Error::custom)
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct Receipt {
    pub version: u32,
    pub run_id: String,
    pub created_at: String,
    pub scope: String,
    pub selection: String,
    pub status: String,
    pub checks: Vec<CheckObservation>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selection_evidence: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comparison: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub skipped_rules: Option<Vec<Value>>,
    #[serde(flatten)]
    pub extra: Fields,
}
impl Receipt {
    pub fn parse(json: &str) -> Result<Self> {
        let result: Self = serde_json::from_str(json)?;
        if result.version != 1 {
            return Err(invalid("unsupported check record"));
        }
        Ok(result)
    }
    pub fn from_json(value: &Value) -> Result<Self> {
        Self::parse(&serde_json::to_string(value)?)
    }
    pub fn to_json(&self) -> Result<Value> {
        RawReport::new(self)?.to_json()
    }
}
impl<'de> Deserialize<'de> for Receipt {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        let value = Box::<RawValue>::deserialize(deserializer)?;
        let parse = || -> Result<Self> {
            let mut f = fields(&value)?;
            let version = take(&mut f, "version")?;
            if version != 1 {
                return Err(invalid("unsupported check record"));
            }
            Ok(Self {
                version,
                run_id: take(&mut f, "run_id")?,
                created_at: take(&mut f, "created_at")?,
                scope: take(&mut f, "scope")?,
                selection: take(&mut f, "selection")?,
                status: take(&mut f, "status")?,
                checks: take(&mut f, "checks")?,
                selection_evidence: optional(&mut f, "selection_evidence")?,
                comparison: optional(&mut f, "comparison")?,
                skipped_rules: optional(&mut f, "skipped_rules")?,
                extra: f,
            })
        };
        parse().map_err(D::Error::custom)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BatchObservation {
    pub results: BTreeMap<String, Observation>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub snapshot: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub engine: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selection: Option<Value>,
}
impl BatchObservation {
    pub fn to_json(&self) -> Result<Value> {
        RawReport::new(self)?.to_json()
    }
}
#[derive(Clone, Debug, Serialize)]
#[serde(transparent)]
pub struct RawReport(Box<RawValue>);
impl RawReport {
    pub fn new<T: Serialize + ?Sized>(value: &T) -> Result<Self> {
        Ok(Self(raw(value)?))
    }
    pub fn parse(json: &str) -> Result<Self> {
        Ok(Self(RawValue::from_string(json.into())?))
    }
    pub fn json(&self) -> &str {
        self.0.get()
    }
    pub fn to_json(&self) -> Result<Value> {
        Ok(serde_json::from_str(self.json())?)
    }
}
