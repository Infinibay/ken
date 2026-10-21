//! Public relevance policy driver; expected scores are never inputs.
use ken_models::{
    JudgeTokens, ModelError, ModelFileSource, NativeTransformerRuntime, RelevanceJudge,
    TransformerDeviceRequest, TransformerDtype, TransformerModel, TransformerSettings,
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
    device: TransformerDeviceRequest,
    dtype: Option<TransformerDtype>,
    batch_size: Option<usize>,
    sequence_length: Option<usize>,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    query: String,
    documents: Vec<String>,
    purpose: String,
    sequence_length: usize,
}
fn kind(error: &ModelError) -> &'static str {
    match error {
        ModelError::RelevanceEmptyDocuments => "IndexError",
        ModelError::RelevanceBudget | ModelError::RelevanceNonfinite | ModelError::Tokenizer(_) => {
            "ValueError"
        }
        _ => "RuntimeError",
    }
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 2 {
        return Err("usage: relevance_probe ABSOLUTE_REQUEST_JSON".into());
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
    let source = ModelFileSource::new(&request.snapshot, &request.private_parent)?;
    let runtime = NativeTransformerRuntime::from_json(
        &request.runtime.to_string(),
        &request.module,
        &request.core_root,
    )?;
    let settings = TransformerSettings {
        dtype: request.dtype,
        batch_size: request.batch_size,
        sequence_length: request.sequence_length,
    };
    let tokens = JudgeTokens::load(&model, &source)?;
    let judge = RelevanceJudge::new(model, source, runtime, settings, request.device)?;
    let initial = judge.preparation()?;
    let mut rows = Vec::new();
    for case in request.cases {
        judge.set_sequence_length(case.sequence_length)?;
        let documents: Vec<_> = case.documents.iter().map(String::as_str).collect();
        let lexical = tokens.prepare(
            &case.query,
            &documents,
            &case.purpose,
            case.sequence_length,
            request.batch_size.unwrap_or(16),
        );
        let scores = judge.score(&case.query, &documents, &case.purpose);
        let mut row = json!({"id":case.id,"preparation":judge.preparation()?});
        match lexical {
            Ok(prepared) => {
                row["feeds"] = serde_json::to_value(prepared.batches)?;
                row["projection_ids"] = json!(prepared.projection_ids);
                row["remaining"] = json!(prepared.remaining);
                row["query_ids"] = json!(prepared.query_ids);
            }
            Err(error) => row["lexical_error"] = json!(error.original_kind()),
        }
        match scores {
            Ok(scores) => {
                row["scores"] = json!(scores);
                row["passed_original_call"] = json!(true);
            }
            Err(error) => {
                row["passed_original_call"] = json!(false);
                row["exception"] = json!(kind(&error));
                row["message"] = json!(error.to_string());
            }
        }
        rows.push(row);
    }
    println!(
        "{}",
        json!({"format":"ken-relevance-probe/1","initial_preparation":initial,"preparation":judge.preparation()?,"rows":rows})
    );
    Ok(())
}
