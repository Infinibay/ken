//! Native source preparation histories without expected answers or Python.
#[path = "support/context_preparation.rs"]
mod support;
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::Read;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    cases: Vec<Frame>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Frame {
    id: String,
    input: support::Input,
}
fn run() -> support::ProbeResult<Value> {
    let mut raw = String::new();
    std::io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_string(&mut raw)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err("preparation request exceeds8MiB".into());
    }
    let request: Request =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw)?)?;
    if request.cases.is_empty() {
        return Err("nonempty preparation cases required".into());
    }
    let cases = request
        .cases
        .into_iter()
        .map(|frame| Ok(json!({"id":frame.id,"events":support::observe(frame.input)?})))
        .collect::<support::ProbeResult<Vec<_>>>()?;
    Ok(json!({"format":"ken-context-preparation-native/1","cases":cases}))
}
fn main() {
    match run() {
        Ok(v) => println!("{v}"),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1)
        }
    }
}
