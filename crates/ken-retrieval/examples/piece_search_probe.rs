//! Input-only complete symbol composition, with controlled leaves and actual Ettin.
#[path = "support/piece_search.rs"]
mod support;
use ken_models::{NativeOnnxRuntime, OnnxReranker, RerankerModel};
use ken_retrieval::paired_reranker::{OnnxPairedReranker, PairedReranker};
use ken_syntax::GrammarCatalog;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{io::Read, path::PathBuf, rc::Rc, sync::Arc};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    grammar_manifest: PathBuf,
    registration: Value,
    source: PathBuf,
    cache: PathBuf,
    runtime_registration: Value,
    library: PathBuf,
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
        return Err("piece search request exceeds8MiB".into());
    }
    let request: Request =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw)?)?;
    if request.cases.is_empty() || !request.source.is_absolute() || !request.cache.is_absolute() {
        return Err("nonempty cases and explicit source/cache required".into());
    }
    let grammars = Arc::new(GrammarCatalog::prepared(&request.grammar_manifest)?);
    let model = RerankerModel::from_json(&request.registration.to_string())?;
    let prepared = Arc::new(model.prepare(Some(&request.source), &request.cache)?);
    let runtime =
        NativeOnnxRuntime::from_json(&request.runtime_registration.to_string(), &request.library)?;
    let mut cases = Vec::new();
    for frame in request.cases {
        let inner: Option<Rc<dyn PairedReranker>> = if frame.input.model.kind == "ettin" {
            Some(Rc::new(OnnxPairedReranker(Arc::new(OnnxReranker::new(
                model.clone(),
                Some(prepared.clone()),
                None,
                request.cache.clone(),
                runtime.clone(),
                frame.input.model.options,
            )?))))
        } else {
            None
        };
        cases.push(json!({"id":frame.id,"observations":support::observe(frame.input,grammars.clone(),inner)?}));
    }
    Ok(
        json!({"format":"ken-piece-search-native/1","runtime":runtime.loaded_identity()?,"cases":cases}),
    )
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
