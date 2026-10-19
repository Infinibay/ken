//! Actual native preparation and paired inference; inputs contain no expectations.
use ken_models::{
    ModelError, NativeOnnxRuntime, OnnxReranker, PreparedReranker, RerankOptions, RerankerModel,
};
use serde::Deserialize;
use serde_json::{Map, Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
    time::Instant,
};
mod support;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    registration: Box<RawValue>,
    source: Option<PathBuf>,
    cache: PathBuf,
    runtime_registration: Box<RawValue>,
    library: PathBuf,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    options: RerankOptions,
    calls: Vec<Call>,
    #[serde(default, rename = "untruncated_pair_tokens")]
    _untruncated_pair_tokens: Option<usize>,
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Call {
    Score { query: String, texts: Vec<String> },
    Tokens { query: String, texts: Vec<String> },
    PairFits { query: String, text: String },
}

fn artifact(bytes: &[u8]) -> Value {
    json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))})
}
fn prepared_artifacts(prepared: &PreparedReranker) -> Result<Value, ModelError> {
    let mut result = Map::new();
    result.insert("model.onnx".into(), artifact(prepared.graph()?));
    for name in ["tokenizer.json", "config.json", "tokenizer_config.json"] {
        result.insert(name.into(), artifact(prepared.artifact(name)?));
    }
    Ok(Value::Object(result))
}
fn source_artifacts(
    model: &RerankerModel,
    source: Option<&Path>,
) -> Result<Value, Box<dyn std::error::Error>> {
    let mut result = Map::new();
    if let Some(source) = source {
        let snapshot = model.source_assets().verify(source)?;
        let definition = serde_json::to_value(model.source_assets())?;
        let names = definition["artifacts"]
            .as_object()
            .ok_or("source artifact map missing")?;
        for name in names.keys() {
            result.insert(name.clone(), artifact(snapshot.artifact(name)?));
        }
        // Drop this independent source verification before the compiler's owned
        // snapshot, rather than retaining an extra backbone during inference.
    }
    Ok(Value::Object(result))
}

fn run() -> Result<Value, Box<dyn std::error::Error>> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    if request.cases.is_empty()
        || !request.cache.is_absolute()
        || request
            .source
            .as_ref()
            .is_some_and(|source| !source.is_absolute())
    {
        return Err("nonempty cases and explicit absolute cache/source paths required".into());
    }
    let started = Instant::now();
    let model = RerankerModel::from_json(request.registration.get())?;
    let runtime =
        NativeOnnxRuntime::from_json(request.runtime_registration.get(), &request.library)?;
    let source_artifacts = source_artifacts(&model, request.source.as_deref())?;
    let fresh_cache = match std::fs::symlink_metadata(&request.cache) {
        Ok(_) => false,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => true,
        Err(error) => return Err(error.into()),
    };
    let first = model.prepare(request.source.as_deref(), &request.cache)?;
    let artifacts = prepared_artifacts(&first)?;
    let reused = model.prepare(None, &request.cache)?;
    if artifacts != prepared_artifacts(&reused)? {
        return Err("reused cache artifacts differ".into());
    }
    drop(first);
    let prepared = Arc::new(reused);
    let prepare_ns = started.elapsed().as_nanos();
    let peak_after_prepare_bytes = support::peak_rss()?;
    let mut results = Vec::new();
    for case in request.cases {
        let started = Instant::now();
        let encoder = OnnxReranker::new(
            model.clone(),
            Some(prepared.clone()),
            None,
            request.cache.clone(),
            runtime.clone(),
            case.options,
        )?;
        let constructor_ns = started.elapsed().as_nanos();
        let peak_before_calls_bytes = support::peak_rss()?;
        let started = Instant::now();
        let mut calls = Vec::new();
        for call in case.calls {
            let result = match call {
                Call::Score { query, texts } => encoder
                    .score(
                        &query,
                        &texts.iter().map(String::as_str).collect::<Vec<_>>(),
                    )
                    .map(|value| json!(value)),
                Call::Tokens { query, texts } => encoder
                    .tokenize_pairs(
                        &query,
                        &texts.iter().map(String::as_str).collect::<Vec<_>>(),
                    )
                    .map(|value| json!(value)),
                Call::PairFits { query, text } => {
                    encoder.pair_fits(&query, &text).map(|value| json!(value))
                }
            };
            calls.push(match result {
                Ok(value) => value,
                Err(error) => json!({"error":{"type":"ModelError","message":error.to_string()}}),
            });
        }
        let calls_ns = started.elapsed().as_nanos();
        let policy = encoder.session_policy()?;
        let providers = policy
            .map(|policy| policy.providers.to_vec())
            .unwrap_or_default();
        results.push(json!({"id":case.id,"calls":calls,"constructor_ns":constructor_ns,"calls_ns":calls_ns,
            "peak_before_calls_bytes":peak_before_calls_bytes,"peak_after_calls_bytes":support::peak_rss()?,
            "session_loaded":encoder.is_prepared()?,"providers":providers,
            "cpu_arena":policy.map(|policy|policy.cpu_arena),"intra_threads":policy.map(|policy|policy.intra_threads),
            "inter_threads":policy.map(|policy|policy.inter_threads)}));
    }
    Ok(
        json!({"artifacts":artifacts,"preparation":{"fresh_cache":fresh_cache,"reused_without_source":true,
        "source_artifacts":source_artifacts,"artifacts":artifacts,"recipe_key":model.recipe_key()},
        "prepare_ns":prepare_ns,"peak_after_prepare_bytes":peak_after_prepare_bytes,"results":results,
        "runtime":{"engine":"rust","ken_models":env!("CARGO_PKG_VERSION"),"tokenizers":"0.22.2",
            "ort":"2.0.0-rc.14","device":"cpu","cpu_arena":true,"inter_threads":1,
            "native_core":runtime.loaded_identity()?}}),
    )
}
fn main() {
    match run().and_then(|value| Ok(serde_json::to_string(&value)?)) {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("ettin_probe: {error}");
            std::process::exit(1);
        }
    }
}
