//! Validation adapter for the real encoder; no expected outputs enter this process.
use ken_models::{Model2VecEncoder, ModelAssets};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, io::Read, path::PathBuf, time::Instant};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    registration: Value,
    snapshot: PathBuf,
    legacy_runtime: BTreeMap<String, String>,
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
    Tokens {
        text: String,
        max_length: Option<usize>,
    },
    Count {
        text: String,
    },
    Query {
        text: String,
    },
    Passages {
        texts: Vec<String>,
    },
}

fn run() -> Result<Value, Box<dyn std::error::Error>> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    let legacy: BTreeMap<String, String> = [
        ("numpy", "2.4.4"),
        ("model2vec", "0.9.0"),
        ("tokenizers", "0.22.2"),
        ("safetensors", "0.8.0"),
    ]
    .into_iter()
    .map(|(k, v)| (k.into(), v.into()))
    .collect();
    if request.legacy_runtime != legacy {
        return Err("unverified legacy runtime identity".into());
    }
    let assets = ModelAssets::from_json(&request.registration.to_string())?;
    let preparation = Instant::now();
    let verified = assets.verify(&request.snapshot)?;
    let prepare_ns = preparation.elapsed().as_nanos();
    let mut results = Vec::new();
    let mut identity = None;
    let mut dimension = None;
    for case in request.cases {
        let started = Instant::now();
        let encoder = Model2VecEncoder::load(&verified)?;
        let load_ns = started.elapsed().as_nanos();
        dimension = Some(encoder.dim());
        let declaration = serde_json::to_value(&assets)?;
        identity = Some(
            json!({"model_id":declaration["model_id"], "hf_revision":declaration["revision"],
            "artifacts":declaration["artifacts"], "dtype":encoder.weight_dtype(), "dimension":encoder.dim(),
            // Preserved space metadata; effective native libraries are reported separately below.
            "runtime":request.legacy_runtime, "pooling":"model2vec-native-mean-L2-v1", "sequence_length":512,
            "tokenizer_policy":"no-padding-no-hidden-truncation-v1", "multiprocessing":false,
            "batch_size":1024, "device":"cpu"}),
        );
        let inference = Instant::now();
        let mut calls = Vec::new();
        for call in case.calls {
            calls.push(match call {
                Call::Tokens { text, max_length } => json!(encoder.token_ids(&text, max_length)?),
                Call::Count { text } => json!(encoder.token_ids(&text, None)?.len()),
                Call::Query { text } => json!(encoder.embed_query(&text)?),
                Call::Passages { texts } => json!(encoder.embed_passages(&texts)?),
            });
        }
        results.push(json!({"id":case.id, "calls":calls, "load_ns":load_ns, "inference_ns":inference.elapsed().as_nanos()}));
    }
    if results.is_empty() {
        return Err("nonempty model cases required".into());
    }
    Ok(
        json!({"assets_fingerprint":assets.fingerprint(), "compatible_identity":identity,
        "dimension":dimension, "prepare_ns":prepare_ns, "results":results,
        "runtime":{"engine":"rust", "ken_models":env!("CARGO_PKG_VERSION"), "device":"cpu",
            "tokenizers":"0.22.2", "safetensors":"0.8.0", "half":"2.7.1",
            "target_os":std::env::consts::OS, "target_arch":std::env::consts::ARCH}}),
    )
}

fn main() {
    match run().and_then(|value| Ok(serde_json::to_string(&value)?)) {
        Ok(output) => println!("{output}"),
        Err(error) => {
            eprintln!("model_probe: {error}");
            std::process::exit(1);
        }
    }
}
