//! Actual native contextual inference. Receives inputs, never expected outputs.
use ken_models::{ContextEncoder, ContextInput, ContextModel, NativeOnnxRuntime};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{io::Read, path::PathBuf, sync::Arc, time::Instant};
mod support;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    registration: Value,
    snapshot: PathBuf,
    runtime_registration: Value,
    library: PathBuf,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    prepare: bool,
    calls: Vec<Call>,
    #[serde(default, rename = "untruncated_tokens")]
    _untruncated_tokens: Option<usize>,
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "lowercase", deny_unknown_fields)]
enum Call {
    Tokens { kind: ContextInput, text: String },
    Query { text: String },
    Passages { texts: Vec<String> },
}

fn run() -> Result<Value, Box<dyn std::error::Error>> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    if request.cases.is_empty() {
        return Err("nonempty contextual cases required".into());
    }
    let preparing = Instant::now();
    let model = ContextModel::from_json(&request.registration.to_string())?;
    let snapshot = Arc::new(model.assets().verify(&request.snapshot)?);
    let runtime =
        NativeOnnxRuntime::from_json(&request.runtime_registration.to_string(), &request.library)?;
    let mut artifacts = serde_json::Map::new();
    for name in ["onnx/model.onnx", "tokenizer.json"] {
        let bytes = snapshot.artifact(name)?;
        artifacts.insert(
            name.into(),
            json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))}),
        );
    }
    let prepare_ns = preparing.elapsed().as_nanos();
    let mut results = Vec::new();
    for case in request.cases {
        let started = Instant::now();
        let encoder = ContextEncoder::new(model.clone(), Arc::clone(&snapshot), runtime.clone())?;
        if case.prepare {
            encoder.prepare()?;
        }
        let load_ns = started.elapsed().as_nanos();
        let peak_after_load_bytes = support::peak_rss()?;
        let started = Instant::now();
        let mut calls = Vec::new();
        for call in case.calls {
            calls.push(match call {
                Call::Tokens { kind, text } => json!(encoder.tokenize(&text, kind)?),
                Call::Query { text } => json!(encoder.embed_query(&text)?),
                Call::Passages { texts } => json!(
                    encoder
                        .embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?
                ),
            });
        }
        let session_loaded = encoder.is_prepared()?;
        let providers: Vec<&str> = if session_loaded {
            vec!["CPUExecutionProvider"]
        } else {
            vec![]
        };
        results.push(json!({"id":case.id,"calls":calls,"load_ns":load_ns,
            "inference_ns":started.elapsed().as_nanos(),"peak_after_load_bytes":peak_after_load_bytes,
            "peak_after_inference_bytes":support::peak_rss()?,"session_loaded":session_loaded,"providers":providers}));
    }
    Ok(
        json!({"dimension":768,"artifacts":artifacts,"compatible_identity":model.compatible_identity(),
        "prepare_ns":prepare_ns,"results":results,"runtime":{
            "engine":"rust","ken_models":env!("CARGO_PKG_VERSION"),"tokenizers":"0.22.2",
            "ort":"2.0.0-rc.14","device":"cpu","intra_threads":2,"inter_threads":1,
            "native_core":runtime.loaded_identity()?}}),
    )
}
fn main() {
    match run().and_then(|value| Ok(serde_json::to_string(&value)?)) {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("context_probe: {error}");
            std::process::exit(1);
        }
    }
}
