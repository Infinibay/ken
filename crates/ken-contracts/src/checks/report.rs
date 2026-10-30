//! Explicitly fallible JSON conveniences over the canonical lossless reports.
use super::{CheckObservation, Observation, Receipt, Result};
use serde_json::Value;
pub fn locations(value: &Value) -> Result<Vec<Value>> {
    let raw = serde_json::value::to_raw_value(value)?;
    super::raw_report::locations(&raw)?
        .iter()
        .map(|v| Ok(serde_json::from_str(v.get())?))
        .collect()
}
pub fn query_view(result: &Value, full: bool) -> Result<Value> {
    super::query_report(&Observation::from_json(result)?, full)?.to_json()
}
pub fn observation_view(value: &Value) -> Result<Value> {
    let item: CheckObservation = serde_json::from_str(&value.to_string())?;
    super::observation_report(&item)?.to_json()
}
pub fn run_view(value: &Value, full: bool) -> Result<Value> {
    super::receipt_report(&Receipt::from_json(value)?, full)?.to_json()
}
pub fn compare(before: &Value, after: &Value) -> Result<Value> {
    Ok(super::compare_receipts(
        &Receipt::from_json(before)?,
        &Receipt::from_json(after)?,
    ))
}
