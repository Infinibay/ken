//! Input-only explicit preference policy and catalog identity observations.
#[path = "support/symbol_preferences.rs"]
mod support;
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::Read;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    cases: Vec<Frame>,
    catalogs: Vec<support::Physical>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Frame {
    id: String,
    kind: String,
    input: support::Input,
}
fn run() -> support::ProbeResult<Value> {
    let mut raw = String::new();
    std::io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_string(&mut raw)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err("preference request exceeds8MiB".into());
    }
    let request: Request =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw)?)?;
    if request.cases.is_empty() || request.catalogs.is_empty() {
        return Err("nonempty preference cases and catalogs required".into());
    }
    let cases = request
        .cases
        .into_iter()
        .map(|c| Ok(json!({"id":c.id,"result":support::observe(&c.kind,&c.input)?})))
        .collect::<support::ProbeResult<Vec<_>>>()?;
    let catalogs = request
        .catalogs
        .into_iter()
        .map(support::classify)
        .collect::<support::ProbeResult<Vec<_>>>()?;
    Ok(json!({"format":"ken-symbol-preferences-native/1","cases":cases,"catalogs":catalogs}))
}
fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}
