use ken_mlx_backend::device;
#[test]
fn actual_mlx_core_reports_pinned_version_and_available_gpu() {
    assert_eq!(device::core_version().unwrap(), "0.32.3");
    assert!(device::gpu_available().unwrap());
}
#[test]
fn binding_compatibility_keeps_the_new_quantized_scale_default_explicit() {
    let ops = include_str!("../vendor/mlx-sys-0.6.0/src/mlx-c/mlx/c/ops.cpp");
    assert!(
        ops.contains(
            "std::nullopt, // MLX0.32.3 optional global_scale, preserve prior API default."
        )
    );
    let build = include_str!("../vendor/mlx-sys-0.6.0/build.rs");
    assert!(build.contains("KEN_MLX_CORE") && build.contains("MLX_C_USE_SYSTEM_MLX"));
}

use ken_mlx_backend::{qwen3::Qwen3, weights::MlxWeights};
use ken_native_model_api::{
    Qwen3Config, TransformerBatch, TransformerDtype, TransformerWeightLayout,
};
use mlx_rs::Dtype;
use std::path::Path;
#[test]
fn actual_two_layer_original_hidden_states_match_every_dtype_and_own_sources() {
    let source =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../ken-torch-backend/tests/fixtures/qwen");
    let original: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/qwen-original-mlx.json")).unwrap();
    for case in original["cases"].as_array().unwrap() {
        let config = Qwen3Config::from_json(
            &std::fs::read_to_string(source.join("config.json")).unwrap(),
            TransformerWeightLayout::Unprefixed,
        )
        .unwrap();
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("model.safetensors");
        std::fs::copy(source.join("model.safetensors"), &path).unwrap();
        let dtype = match case["dtype"].as_str().unwrap() {
            "float32" => TransformerDtype::Float32,
            "float16" => TransformerDtype::Float16,
            "bfloat16" => TransformerDtype::BFloat16,
            _ => unreachable!(),
        };
        let weights = MlxWeights::load(&config, &path, dtype).unwrap();
        std::fs::remove_file(path).unwrap();
        let graph = Qwen3::load(config, weights).unwrap();
        let batch = TransformerBatch {
            input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
            attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
        };
        let expected: Vec<Vec<Vec<f32>>> = serde_json::from_value(case["values"].clone()).unwrap();
        let expected: Vec<_> = expected.into_iter().flatten().flatten().collect();
        let output = graph
            .forward(&batch)
            .unwrap()
            .as_dtype(Dtype::Float32)
            .unwrap();
        output.eval().unwrap();
        let values = output.as_slice::<f32>().to_vec();
        let maximum = values
            .iter()
            .zip(&expected)
            .map(|(a, b)| (a - b).abs())
            .fold(0.0_f32, f32::max);
        assert_eq!(values.len(), expected.len());
        assert!(
            maximum <= 1e-5,
            "{} {} error {maximum}",
            case["name"],
            case["dtype"]
        );
        let again = graph
            .forward(&batch)
            .unwrap()
            .as_dtype(Dtype::Float32)
            .unwrap();
        again.eval().unwrap();
        assert_eq!(again.as_slice::<f32>(), values);
        let on_thread = std::thread::spawn(move || {
            let value = graph
                .forward(&batch)
                .unwrap()
                .as_dtype(Dtype::Float32)
                .unwrap();
            value.eval().unwrap();
            value.as_slice::<f32>().to_vec()
        })
        .join()
        .unwrap();
        assert_eq!(on_thread, values);
    }
}

#[test]
fn malformed_weights_layout_and_nonfinite_source_fail_with_healthy_controls() {
    let source =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../ken-torch-backend/tests/fixtures/qwen");
    let config = std::fs::read_to_string(source.join("config.json")).unwrap();
    let registration =
        Qwen3Config::from_json(&config, TransformerWeightLayout::Unprefixed).unwrap();
    let bytes = std::fs::read(source.join("model.safetensors")).unwrap();
    let length = u64::from_le_bytes(bytes[..8].try_into().unwrap()) as usize;
    let metadata: serde_json::Value = serde_json::from_slice(&bytes[8..8 + length]).unwrap();
    let data = &bytes[8 + length..];
    fn archive(header: &serde_json::Value, data: &[u8]) -> Vec<u8> {
        let mut encoded = serde_json::to_vec(header).unwrap();
        while !encoded.len().is_multiple_of(8) {
            encoded.push(b' ');
        }
        let mut bytes = (encoded.len() as u64).to_le_bytes().to_vec();
        bytes.extend(encoded);
        bytes.extend(data);
        bytes
    }
    let mut wrong_shape = metadata.clone();
    wrong_shape["embed_tokens.weight"]["shape"] = serde_json::json!([4, 8]);
    let mut wrong_name = metadata.clone();
    let value = wrong_name
        .as_object_mut()
        .unwrap()
        .remove("embed_tokens.weight")
        .unwrap();
    wrong_name["unexpected.weight"] = value;
    let mut wrong_type = metadata.clone();
    wrong_type["embed_tokens.weight"]["dtype"] = serde_json::json!("I32");
    let mut nan = data.to_vec();
    let offset = metadata["embed_tokens.weight"]["data_offsets"][0]
        .as_u64()
        .unwrap() as usize;
    nan[offset..offset + 4].copy_from_slice(&f32::NAN.to_le_bytes());
    let mut missing = metadata.clone();
    missing
        .as_object_mut()
        .unwrap()
        .remove("embed_tokens.weight");
    let invalid = [
        bytes[..7].to_vec(),
        archive(&wrong_shape, data),
        archive(&wrong_name, data),
        archive(&wrong_type, data),
        archive(&metadata, &nan),
        archive(&missing, data),
    ];
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("model.safetensors");
    for bad in invalid {
        std::fs::write(&path, bad).unwrap();
        assert!(MlxWeights::load(&registration, &path, TransformerDtype::Float32).is_err());
        std::fs::write(&path, &bytes).unwrap();
        assert!(MlxWeights::load(&registration, &path, TransformerDtype::Float32).is_ok());
    }
    assert!(
        MlxWeights::load(
            &Qwen3Config::from_json(&config, TransformerWeightLayout::ModelPrefix).unwrap(),
            &path,
            TransformerDtype::Float32
        )
        .is_err()
    );
    let mut prefixed = serde_json::Map::new();
    for (name, value) in metadata.as_object().unwrap() {
        prefixed.insert(
            if name == "__metadata__" {
                name.to_owned()
            } else {
                format!("model.{name}")
            },
            value.clone(),
        );
    }
    std::fs::write(&path, archive(&serde_json::Value::Object(prefixed), data)).unwrap();
    assert!(
        MlxWeights::load(
            &Qwen3Config::from_json(&config, TransformerWeightLayout::ModelPrefix).unwrap(),
            &path,
            TransformerDtype::BFloat16
        )
        .is_ok()
    );
}
