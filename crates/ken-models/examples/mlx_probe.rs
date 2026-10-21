//! Public text API driver. No expected output or failure controls are inputs.
use ken_models::{
    MLXEncoder, ModelFileSource, NativeTransformerRuntime, TransformerDtype, TransformerModel,
    TransformerSettings, TransformerTokens,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{error::Error, fs::OpenOptions, io::Read, path::PathBuf};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    model: Value,
    runtime: Value,
    snapshot: PathBuf,
    private_parent: PathBuf,
    module: PathBuf,
    core_root: PathBuf,
    dtype: Option<TransformerDtype>,
    sequence_length: Option<usize>,
    batch_size: Option<usize>,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    side: Side,
    texts: Vec<String>,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Side {
    Query,
    Passage,
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 2 {
        return Err("usage: mlx_probe ABSOLUTE_REQUEST_JSON".into());
    }
    let path = PathBuf::from(&args[1]);
    if !path.is_absolute() {
        return Err("explicit absolute request path required".into());
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY);
    }
    let file = options.open(path)?;
    let limit = ken_native_model_api::MAX_PAYLOAD;
    if !file.metadata()?.is_file() || file.metadata()?.len() > limit as u64 {
        return Err("bounded regular request file required".into());
    }
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err("request exceeds byte bound".into());
    }
    let request: Request = serde_json::from_slice(&bytes)?;
    let model = TransformerModel::from_json(&request.model.to_string())?;
    let runtime = NativeTransformerRuntime::from_json(
        &request.runtime.to_string(),
        &request.module,
        &request.core_root,
    )?;
    let source = ModelFileSource::new(&request.snapshot, &request.private_parent)?;
    let settings = TransformerSettings {
        dtype: request.dtype,
        sequence_length: request.sequence_length,
        batch_size: request.batch_size,
    };
    let encoder = MLXEncoder::new(model.clone(), source.clone(), runtime, settings.clone())?;
    let initial = encoder.preparation()?;
    let empty = encoder.embed_passages(&[])?;
    let after_empty = encoder.preparation()?;
    let tokens = TransformerTokens::for_mlx(&model, &source, &settings)?;
    let mut rows = Vec::new();
    for case in request.cases {
        let texts: Vec<_> = case.texts.iter().map(String::as_str).collect();
        let counts: Vec<_> = texts
            .iter()
            .map(|text| encoder.token_count(text))
            .collect::<Result<_, _>>()?;
        let prepared = match case.side {
            Side::Query => tokens.queries(&texts),
            Side::Passage => tokens.passages(&texts),
        }?;
        let vectors = match case.side {
            Side::Query => encoder.embed_queries(&texts),
            Side::Passage => encoder.embed_passages(&texts),
        }?;
        rows.push(json!({"id":case.id,"counts":counts,"feeds":prepared.batches(),"order":prepared.original_indices(),"vectors":vectors,"preparation":encoder.preparation()?}));
    }
    println!(
        "{}",
        json!({"format":"ken-mlx-probe/1","initial_preparation":initial,"empty_vectors":empty,"after_empty_preparation":after_empty,"dimension":encoder.dim()?,"preparation":encoder.preparation()?,"rows":rows})
    );
    Ok(())
}
