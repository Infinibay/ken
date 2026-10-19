//! Actual NPZ inference adapter. It receives no expected outputs.
use ken_models::StaticTableEncoder;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{io::Read, path::PathBuf, time::Instant};
mod support;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    artifact: PathBuf,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    calls: Vec<Call>,
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "lowercase", deny_unknown_fields)]
enum Call {
    Tokens { text: String },
    Count { text: String },
    Query { text: String },
    Passages { texts: Vec<String> },
    Queries { texts: Vec<String> },
}

fn run() -> Result<Value, Box<dyn std::error::Error>> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    if request.cases.is_empty() {
        return Err("nonempty table cases required".into());
    }
    let preparing = Instant::now();
    let bytes = std::fs::read(request.artifact)?;
    let artifact = json!({"sha256":format!("{:x}",Sha256::digest(&bytes)),"bytes":bytes.len()});
    let prepare_ns = preparing.elapsed().as_nanos();
    let mut results = Vec::new();
    let mut dimension = 0;
    let mut meta = Value::Null;
    for case in request.cases {
        let start = Instant::now();
        let encoder = StaticTableEncoder::from_npz(&bytes)?;
        let load_ns = start.elapsed().as_nanos();
        let peak_after_load_bytes = support::peak_rss()?;
        dimension = encoder.dim();
        meta = encoder.meta().clone();
        let started = Instant::now();
        let mut calls = Vec::new();
        for call in case.calls {
            calls.push(match call {
                Call::Tokens { text } => json!(encoder.tokenize(&text)?),
                Call::Count { text } => json!(encoder.token_count(&text)?),
                Call::Query { text } => json!(encoder.embed_query(&text)?),
                Call::Passages { texts } => json!(
                    encoder
                        .embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?
                ),
                Call::Queries { texts } => json!(
                    encoder.embed_queries(&texts.iter().map(String::as_str).collect::<Vec<_>>())?
                ),
            });
        }
        results.push(json!({"id":case.id,"calls":calls,"load_ns":load_ns,
            "inference_ns":started.elapsed().as_nanos(),"peak_after_load_bytes":peak_after_load_bytes,
            "peak_after_inference_bytes":support::peak_rss()?}));
    }
    Ok(
        json!({"artifact":artifact,"dimension":dimension,"meta":meta,"prepare_ns":prepare_ns,
        "results":results,"runtime":{"engine":"rust","ken_models":env!("CARGO_PKG_VERSION"),
        "tokenizers":"0.22.2","npyz":"0.9.1","zip":"6.0.0","ndarray":"0.17.1","device":"cpu",
        "target_os":std::env::consts::OS,"target_arch":std::env::consts::ARCH}}),
    )
}

fn main() {
    match run().and_then(|v| Ok(serde_json::to_string(&v)?)) {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("table_probe: {error}");
            std::process::exit(1);
        }
    }
}
