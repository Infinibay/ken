//! Strict native text protocol; expectations and source mutation stay outside.
use ken_models::{
    FastEmbedCatalog, FastEmbedDeviceRequest, FastEmbedEncoder, FastEmbedInput, ModelError,
    ModelFileSource, NativeOnnxRuntime,
};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::{self, BufRead, Read, Write},
    path::PathBuf,
    time::Instant,
};
#[path = "support/observed_peak.rs"]
mod observed_peak;
mod support;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const FRAME_LIMIT: usize = 16 * 1024 * 1024;
struct Args {
    registry: PathBuf,
    sources: PathBuf,
    work: PathBuf,
    library: PathBuf,
    model: String,
}
fn parse_args(args: Vec<String>) -> Result<Args> {
    if args.len() != 10 {
        return Err("five explicit flag/value arguments required".into());
    }
    let mut fields = BTreeMap::new();
    for pair in args.chunks_exact(2) {
        if ![
            "--registry",
            "--sources",
            "--work",
            "--runtime-library",
            "--model",
        ]
        .contains(&pair[0].as_str())
            || fields.insert(pair[0].clone(), pair[1].clone()).is_some()
        {
            return Err("unknown or duplicate argument".into());
        }
    }
    let result = Args {
        registry: fields
            .remove("--registry")
            .ok_or("registry required")?
            .into(),
        sources: fields.remove("--sources").ok_or("sources required")?.into(),
        work: fields.remove("--work").ok_or("work required")?.into(),
        library: fields
            .remove("--runtime-library")
            .ok_or("runtime-library required")?
            .into(),
        model: fields.remove("--model").ok_or("model required")?,
    };
    if [
        &result.registry,
        &result.sources,
        &result.work,
        &result.library,
    ]
    .iter()
    .any(|path| !path.is_absolute())
        || result.model.is_empty()
    {
        return Err("absolute paths and nonempty model required".into());
    }
    Ok(result)
}
#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
enum Side {
    Query,
    Passage,
}
impl From<Side> for FastEmbedInput {
    fn from(side: Side) -> Self {
        match side {
            Side::Query => Self::Query,
            Side::Passage => Self::Passage,
        }
    }
}
#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Status {
        id: String,
    },
    Prepare {
        id: String,
    },
    Tokenize {
        id: String,
        side: Side,
        texts: Vec<String>,
    },
    Embed {
        id: String,
        side: Side,
        texts: Vec<String>,
    },
}
impl Request {
    fn id(&self) -> &str {
        match self {
            Self::Status { id }
            | Self::Prepare { id }
            | Self::Tokenize { id, .. }
            | Self::Embed { id, .. } => id,
        }
    }
    fn operation(&self) -> &str {
        match self {
            Self::Status { .. } => "status",
            Self::Prepare { .. } => "prepare",
            Self::Tokenize { .. } => "tokenize",
            Self::Embed { .. } => "embed",
        }
    }
}
fn parse_request(raw: &str, seen: &mut BTreeSet<String>) -> Result<Request> {
    let request: Request = serde_json::from_str(raw)?;
    if request.id().is_empty() || !seen.insert(request.id().into()) {
        return Err("distinct nonempty request IDs required".into());
    }
    Ok(request)
}
fn state(encoder: &FastEmbedEncoder) -> Result<Value> {
    Ok(
        json!({"model_loaded":encoder.is_prepared()?,"device":encoder.device()?,"dim":encoder.dim()}),
    )
}
fn failure(error: ModelError) -> Value {
    let kind = match &error {
        ModelError::Registration(_) => "registration",
        ModelError::Json(_) => "json",
        ModelError::Io { .. } => "io",
        ModelError::Artifact(_) => "artifact",
        ModelError::Tokenizer(_) => "tokenizer",
        ModelError::Weights(_) => "weights",
        ModelError::Inference(_) => "inference",
        ModelError::Runtime(_) => "runtime",
    };
    json!({"type":"ModelError","kind":kind,"message":error.to_string()})
}
fn execute(
    encoder: &FastEmbedEncoder,
    request: &Request,
) -> std::result::Result<Value, ModelError> {
    match request {
        Request::Status { .. } => Ok(json!({"prepared":encoder.is_prepared()?})),
        Request::Prepare { .. } => {
            encoder.prepare()?;
            Ok(json!({"prepared":encoder.is_prepared()?}))
        }
        Request::Tokenize { side, texts, .. } => {
            let texts: Vec<_> = texts.iter().map(String::as_str).collect();
            let tokens = encoder.tokenize(&texts, (*side).into())?;
            Ok(
                json!({"batches":tokens.iter().map(|batch|json!({"shape":batch.shape,"ids":batch.ids,"attention_mask":batch.attention_mask})).collect::<Vec<_>>()}),
            )
        }
        Request::Embed { side, texts, .. } => {
            let texts: Vec<_> = texts.iter().map(String::as_str).collect();
            let run = encoder.embed_details(&texts, (*side).into())?;
            let mut hex = String::new();
            for row in &run.vectors {
                for value in row {
                    for byte in value.to_le_bytes() {
                        use std::fmt::Write;
                        write!(&mut hex, "{byte:02x}").expect("write to String");
                    }
                }
            }
            Ok(
                json!({"shape":[run.vectors.len(),encoder.dim()],"vectors_f32le_hex":hex,"batches":run.batches}),
            )
        }
    }
}
fn sample(peaks: &mut observed_peak::ObservedPeak) -> Result<Value> {
    let sample = peaks.record(support::peak_rss()?)?;
    Ok(
        json!({"reported_hwm_bytes":sample.reported_hwm_bytes,"observed_peak_bytes":sample.observed_peak_bytes}),
    )
}
fn producer() -> Result<Value> {
    let files:BTreeMap<&str,String>=[
  ("crates/ken-models/src/assets.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/assets.rs")))),
  ("crates/ken-models/src/context_encoder.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/context_encoder.rs")))),
  ("crates/ken-models/src/context_model.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/context_model.rs")))),
  ("crates/ken-models/src/embedding_pool.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/embedding_pool.rs")))),
  ("crates/ken-models/src/fastembed_encoder.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/fastembed_encoder.rs")))),
  ("crates/ken-models/src/fastembed_model.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/fastembed_model.rs")))),
  ("crates/ken-models/src/fastembed_session.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/fastembed_session.rs")))),
  ("crates/ken-models/src/fastembed_tokens.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/fastembed_tokens.rs")))),
  ("crates/ken-models/src/file_assets.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/file_assets.rs")))),
  ("crates/ken-models/src/lib.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/lib.rs")))),
  ("crates/ken-models/src/model2vec.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/model2vec.rs")))),
  ("crates/ken-models/src/model_policy.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/model_policy.rs")))),
  ("crates/ken-models/src/native_onnx.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/native_onnx.rs")))),
  ("crates/ken-models/src/onnx_dependencies.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/onnx_dependencies.rs")))),
  ("crates/ken-models/src/onnx_providers.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/onnx_providers.rs")))),
  ("crates/ken-models/src/onnx_reranker.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/onnx_reranker.rs")))),
  ("crates/ken-models/src/onnx_wire.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/onnx_wire.rs")))),
  ("crates/ken-models/src/published_head.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/published_head.rs")))),
  ("crates/ken-models/src/python_unicode.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/python_unicode.rs")))),
  ("crates/ken-models/src/query_expansion.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/query_expansion.rs")))),
  ("crates/ken-models/src/query_policy.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/query_policy.rs")))),
  ("crates/ken-models/src/reranker_model.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/reranker_model.rs")))),
  ("crates/ken-models/src/reranker_preparation.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/reranker_preparation.rs")))),
  ("crates/ken-models/src/reranker_tokens.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/reranker_tokens.rs")))),
  ("crates/ken-models/src/static_table.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/static_table.rs")))),
  ("crates/ken-models/src/table_npz.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/table_npz.rs")))),
  ("crates/ken-models/src/term_cache.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/term_cache.rs")))),
  ("crates/ken-models/src/tokenization.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/tokenization.rs")))),
  ("crates/ken-models/src/translation_json.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/translation_json.rs")))),
  ("crates/ken-models/src/translation_model.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/translation_model.rs")))),
  ("crates/ken-models/src/translation_preparation.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/translation_preparation.rs")))),
  ("crates/ken-models/src/verified_file.rs",format!("{:x}",Sha256::digest(include_bytes!("../src/verified_file.rs")))),
  ("Cargo.toml",format!("{:x}",Sha256::digest(include_bytes!("../../../Cargo.toml")))),
  ("Cargo.lock",format!("{:x}",Sha256::digest(include_bytes!("../../../Cargo.lock")))),
  ("crates/ken-models/Cargo.toml",format!("{:x}",Sha256::digest(include_bytes!("../Cargo.toml")))),
  ("crates/ken-models/examples/fastembed_probe.rs",format!("{:x}",Sha256::digest(include_bytes!("fastembed_probe.rs")))),
  ("crates/ken-models/examples/support/mod.rs",format!("{:x}",Sha256::digest(include_bytes!("support/mod.rs")))),
  ("crates/ken-models/examples/support/observed_peak.rs",format!("{:x}",Sha256::digest(include_bytes!("support/observed_peak.rs")))),
  ("docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json",format!("{:x}",Sha256::digest(include_bytes!("../../../docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json")))),
 ].into_iter().collect();
    let hash = format!("{:x}", Sha256::digest(serde_json::to_vec(&files)?));
    Ok(
        json!({"engine":"rust","ken_models":env!("CARGO_PKG_VERSION"),"tokenizers":"0.22.2","ort":"2.0.0-rc.14","api":ort::sys::ORT_API_VERSION,"source_sha256":hash,"source_files":files.len()}),
    )
}
fn run() -> Result<()> {
    let args = parse_args(std::env::args().skip(1).collect())?;
    let catalog = FastEmbedCatalog::from_json(&fs::read_to_string(&args.registry)?)?;
    let model = catalog
        .model(&args.model)?
        .with_requested_name(&args.model)?;
    let source = args
        .sources
        .join(model.source_id().replace('/', "--"))
        .join(model.source_revision());
    let source = ModelFileSource::new(&source, &args.work)?;
    let runtime = NativeOnnxRuntime::from_json(
        include_str!(
            "../../../docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json"
        ),
        &args.library,
    )?;
    let started = Instant::now();
    let encoder = FastEmbedEncoder::new(
        model.clone(),
        source,
        runtime,
        FastEmbedDeviceRequest::from_inputs(Some("cpu"), None),
    )?;
    let constructor_ns = started.elapsed().as_nanos();
    let producer = producer()?;
    let mut peaks = observed_peak::ObservedPeak::default();
    let mut seen = BTreeSet::new();
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    let mut line = Vec::new();
    loop {
        line.clear();
        let count = input
            .by_ref()
            .take((FRAME_LIMIT + 1) as u64)
            .read_until(b'\n', &mut line)?;
        if count == 0 {
            break;
        }
        if count > FRAME_LIMIT {
            return Err("input frame exceeds bound".into());
        }
        let request = parse_request(std::str::from_utf8(&line)?, &mut seen)?;
        let before = state(&encoder)?;
        let before_peak = sample(&mut peaks)?;
        let started = Instant::now();
        let result = execute(&encoder, &request);
        let elapsed_ns = started.elapsed().as_nanos();
        let mut frame = json!({"format":"ken-fastembed-frame/1","id":request.id(),"operation":request.operation(),"model":model.name(),"producer":producer,"model_fingerprint":model.fingerprint(),"assets_fingerprint":model.assets().fingerprint(),"constructor_ns":constructor_ns,"before":before,"state":state(&encoder)?,"preparation":encoder.preparation()?,"elapsed_ns":elapsed_ns,"memory":{"before":before_peak,"after":sample(&mut peaks)?}});
        match result {
            Ok(result) => {
                frame["result"] = result;
            }
            Err(error) => {
                frame["error"] = failure(error);
            }
        }
        serde_json::to_writer(&mut output, &frame)?;
        output.write_all(b"\n")?;
        output.flush()?;
    }
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("fastembed_probe: {error}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use serde_json::json;
    use std::collections::BTreeSet;
    #[test]
    fn protocol_rejects_unknown_fields_types_operations_and_duplicate_ids() {
        for raw in [
            r#"{}"#,
            r#"{"id":"a","operation":"run"}"#,
            r#"{"id":"","operation":"status"}"#,
            r#"{"id":"a","operation":"status","expected":{}}"#,
            r#"{"id":"a","operation":"prepare","source_setup":true}"#,
            r#"{"id":"a","operation":"embed","side":"query","texts":[1]}"#,
            r#"{"id":"a","operation":"embed","side":"other","texts":[]}"#,
            r#"{"id":"a","operation":"status","id":"b"}"#,
            r#"{"id":"a","operation":"status","operation":"prepare"}"#,
        ] {
            assert!(
                super::parse_request(raw, &mut BTreeSet::new()).is_err(),
                "{raw}"
            );
        }
        let mut seen = BTreeSet::new();
        let raw =
            json!({"id":"a","operation":"embed","side":"query","texts":["é/設定","cafe\u{301}"]})
                .to_string();
        assert!(super::parse_request(&raw, &mut seen).is_ok());
        assert!(super::parse_request(&raw, &mut seen).is_err());
        for operation in ["status", "prepare", "tokenize", "embed"] {
            let mut value = json!({"id":"a","operation":operation});
            if operation == "tokenize" || operation == "embed" {
                value["side"] = json!("passage");
                value["texts"] = json!([]);
            }
            assert!(super::parse_request(&value.to_string(), &mut BTreeSet::new()).is_ok());
        }
    }
    #[test]
    fn command_line_requires_explicit_absolute_paths_and_exact_five_flags() {
        let args = [
            "--registry",
            "/missing/registry",
            "--sources",
            "/missing/sources",
            "--work",
            "/missing/work",
            "--runtime-library",
            "/missing/core",
            "--model",
            "BAAI/bge-base-en",
        ]
        .map(String::from)
        .to_vec();
        assert!(super::parse_args(args.clone()).is_ok());
        for index in [1, 3, 5, 7] {
            let mut bad = args.clone();
            bad[index] = "relative".into();
            assert!(super::parse_args(bad).is_err());
        }
        let mut bad = args.clone();
        bad.extend(["--model".into(), "other".into()]);
        assert!(super::parse_args(bad).is_err());
        let mut bad = args;
        bad.extend(["--expected".into(), "{}".into()]);
        assert!(super::parse_args(bad).is_err());
    }
}
