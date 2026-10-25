//! Input-only native runtime loading, without model weights or Python dispatch.
use ken_models::{NativeOnnxRuntime, NativeTransformerRuntime};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    io::{self, Read},
    path::PathBuf,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    format: String,
    onnx: Onnx,
    torch: Torch,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Onnx {
    registration: Value,
    library: PathBuf,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Torch {
    registration: Value,
    module: PathBuf,
    core_root: PathBuf,
}
fn parse(raw: &[u8]) -> Result<Request, Box<dyn std::error::Error>> {
    let request: Request = serde_json::from_slice(raw)?;
    if request.format != "ken-native-cpu-core-request/1" {
        return Err("unsupported native core request".into());
    }
    Ok(request)
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut raw = Vec::new();
    io::stdin().take(1024 * 1024 + 1).read_to_end(&mut raw)?;
    if raw.len() > 1024 * 1024 {
        return Err("native core request exceeds1MiB".into());
    }
    let request = parse(&raw)?;
    let onnx = NativeOnnxRuntime::from_json(
        &serde_json::to_string(&request.onnx.registration)?,
        &request.onnx.library,
    )?
    .load()?;
    let torch = NativeTransformerRuntime::from_json(
        &serde_json::to_string(&request.torch.registration)?,
        &request.torch.module,
        &request.torch.core_root,
    )?
    .load()?;
    println!(
        "{}",
        json!({"format":"ken-native-cpu-core-observation/1","os":std::env::consts::OS,"arch":std::env::consts::ARCH,"onnx":onnx,"torch":torch})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn input_only_transport_rejects_expected_answers_and_unversioned_requests() {
        let valid = json!({"format":"ken-native-cpu-core-request/1","onnx":{"registration":{},"library":"/core"},"torch":{"registration":{},"module":"/module","core_root":"/torch"}});
        assert!(parse(&serde_json::to_vec(&valid).unwrap()).is_ok());
        for part in ["root", "onnx", "torch"] {
            let mut value = valid.clone();
            let object = if part == "root" {
                &mut value
            } else {
                &mut value[part]
            };
            object["expected"] = json!({"passed":true});
            assert!(parse(&serde_json::to_vec(&value).unwrap()).is_err());
        }
        let mut value = valid;
        value["format"] = json!("future/2");
        assert!(parse(&serde_json::to_vec(&value).unwrap()).is_err());
    }
}
