//! Receipt witnesses stay in their immutable owner; knowledge receives freshness.
use ken_checks_application::ChecksApplication;
use ken_contracts::checks::{Receipt, Store};
use ken_knowledge::{Result, records::CheckObservation};
use serde_json::{Value, json};
use std::{collections::BTreeSet, path::Path, time::Duration};
pub(super) fn run_ids(value: &Value) -> Vec<String> {
    fn visit(value: &Value, ids: &mut BTreeSet<String>) {
        match value {
            Value::Object(map) => {
                if let Some(runs) = map.get("check_runs").and_then(Value::as_array) {
                    for id in runs.iter().filter_map(Value::as_str) {
                        ids.insert(id.into());
                    }
                }
                for value in map.values() {
                    visit(value, ids);
                }
            }
            Value::Array(values) => {
                for value in values {
                    visit(value, ids);
                }
            }
            _ => {}
        }
    }
    let mut ids = BTreeSet::new();
    visit(value, &mut ids);
    ids.into_iter().collect()
}
fn observation(id: &str, receipt: Option<Receipt>, validity: Value) -> CheckObservation {
    let (status, rules) = receipt
        .map(|receipt| {
            (
                receipt.status,
                receipt.checks.into_iter().map(|c| c.rule).collect(),
            )
        })
        .unwrap_or_else(|| ("unknown".into(), vec![]));
    CheckObservation {
        receipt_path: format!(".ken/checks/runs/{id}.json"),
        run_id: id.into(),
        status,
        rules,
        observations: validity["checks"].clone(),
        validity,
    }
}
pub(super) fn observations(
    root: &Path,
    application: std::result::Result<Option<&ChecksApplication>, String>,
    ids: &[String],
) -> Vec<CheckObservation> {
    if ids.is_empty() {
        return vec![];
    }
    let store = Store::new(root);
    ids.iter().map(|id|{
  let receipt=store.as_ref().map_err(ToString::to_string).and_then(|store|store.read_receipt(id).map_err(|e|e.to_string()));
  let live=match &application{Err(reason)=>Err(reason.clone()),Ok(None)=>Err("check freshness unavailable; checks application was not supplied".into()),Ok(Some(application))=>application.freshness(id,Duration::from_secs(2)).map_err(|e|e.to_string())};
  let validity=match live{Ok(value)=>value,Err(reason)=>json!({"state":"unknown","issues":[format!("check freshness unavailable: {reason}")],"checks":[]})};
  observation(id,receipt.ok(),validity)
 }).collect()
}
pub(super) fn attach(
    application: Option<&ChecksApplication>,
    run: &str,
    justification: Option<&Value>,
) -> Result<Value> {
    application
        .ok_or_else(|| super::error("check freshness unavailable; rerun ken_check"))?
        .justification(run, justification)
        .map_err(super::error)
}
