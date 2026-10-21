//! Explicit prepared-data driver; expected numerical outputs are never inputs.
use ken_models::{
    ModelFileSource, NativeTransformerRuntime, TransformerBatch, TransformerBatchResult,
    TransformerDevice, TransformerDtype, TransformerModel, TransformerOutput, TransformerSession,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{error::Error, fs::OpenOptions, io::Read, path::PathBuf, sync::Arc};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    model: Value,
    runtime: Value,
    snapshot: PathBuf,
    private_parent: PathBuf,
    module: PathBuf,
    core_root: PathBuf,
    device: TransformerDevice,
    dtype: TransformerDtype,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    batch: TransformerBatch,
    output: TransformerOutput,
}

#[derive(Serialize)]
struct ResultRow {
    id: String,
    batch: TransformerBatchResult,
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 2 {
        return Err("usage: transformer_probe ABSOLUTE_REQUEST_JSON".into());
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
    let files = Arc::new(model.assets().verify_files(&ModelFileSource::new(
        &request.snapshot,
        &request.private_parent,
    )?)?);
    let mut session =
        TransformerSession::prepare(&model, files, runtime, request.device, request.dtype)?;
    let mut rows = Vec::new();
    for case in request.cases {
        rows.push(ResultRow {
            id: case.id,
            batch: session.run(&case.batch, &case.output)?,
        });
    }
    println!(
        "{}",
        serde_json::to_string(
            &serde_json::json!({"format":"ken-transformer-probe/1","preparation":session.trace(),"rows":rows})
        )?
    );
    Ok(())
}
