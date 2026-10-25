//! Input-only Java/JavaScript/TypeScript source-operation observations.
#[path = "support/syntax_witnesses.rs"]
mod support;
use ken_syntax::GrammarCatalog;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{io::Read, path::PathBuf, sync::Arc};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    grammar_manifest: PathBuf,
    cases: Vec<Frame>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Frame {
    id: String,
    input: support::Physical,
}
fn run() -> support::ProbeResult<Value> {
    let mut raw = String::new();
    std::io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_string(&mut raw)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err("syntax request exceeds8MiB".into());
    }
    let request: Request =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw)?)?;
    if request.cases.is_empty() {
        return Err("nonempty syntax cases required".into());
    }
    let grammars = Arc::new(GrammarCatalog::prepared(&request.grammar_manifest)?);
    let cases = request
        .cases
        .into_iter()
        .map(|c| Ok(json!({"id":c.id,"result":support::observe(c.input,grammars.clone())?})))
        .collect::<support::ProbeResult<Vec<_>>>()?;
    Ok(json!({"format":"ken-syntax-witnesses-native/1","cases":cases}))
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
