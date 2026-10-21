//! Actual two-layer original numerical fixtures and fallible native ownership.
use ken_native_model_api::{
    TransformerBatch, TransformerDevice, TransformerDtype, TransformerWeightLayout,
};
use ken_torch_backend::{CoreConfig, qwen3::Qwen3, weights::TorchWeights};
use serde_json::Value;
use std::path::{Path, PathBuf};
use tch::{Kind, Tensor};
fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/qwen")
        .join(name)
}
fn config(layout: TransformerWeightLayout) -> CoreConfig {
    CoreConfig::from_json(
        &std::fs::read_to_string(fixture("config.json")).unwrap(),
        layout,
    )
    .unwrap()
}
fn dtype(name: &str) -> TransformerDtype {
    match name {
        "float32" => TransformerDtype::Float32,
        "float16" => TransformerDtype::Float16,
        "bfloat16" => TransformerDtype::BFloat16,
        _ => panic!("fixture dtype"),
    }
}
#[test]
fn two_distinguishable_layers_match_original_for_every_cpu_precision_and_repeat() {
    tch::set_num_threads(2);
    let original: Value =
        serde_json::from_str(include_str!("fixtures/qwen/original.json")).unwrap();
    assert_eq!(original["torch"], "2.9.0");
    assert_eq!(original["transformers"], "4.57.6");
    let cfg = config(TransformerWeightLayout::Unprefixed);
    for case in original["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["device"] == "cpu")
    {
        let weights = TorchWeights::load(
            &cfg,
            &fixture("model.safetensors"),
            TransformerDevice::Cpu,
            dtype(case["dtype"].as_str().unwrap()),
        )
        .unwrap();
        let core = Qwen3::load(cfg.clone(), weights).unwrap();
        let batch = TransformerBatch {
            input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
            attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
        };
        let result = core.forward(&batch).unwrap();
        let repeated = core.forward(&batch).unwrap();
        assert!(result.equal(&repeated), "request must not retain KV state");
        assert_eq!(serde_json::to_value(result.size()).unwrap(), case["shape"]);
        let values: Vec<f32> = Vec::try_from(&result.to_kind(Kind::Float).reshape([-1])).unwrap();
        let expected: Vec<f32> = serde_json::from_value(case["values"].clone()).unwrap();
        let error = values
            .iter()
            .zip(&expected)
            .map(|(a, b)| (a - b).abs())
            .fold(0.0_f32, f32::max);
        assert!(
            error <= 1e-6,
            "{} {} error={error}",
            case["name"],
            case["dtype"]
        );
        assert!(
            core.forward(&TransformerBatch {
                input_ids: vec![vec![8]],
                attention_mask: vec![vec![1]]
            })
            .is_err()
        );
    }
}
#[test]
fn weights_require_exact_shapes_finite_data_and_explicit_layout_before_publication() {
    let cfg = config(TransformerWeightLayout::Unprefixed);
    let prefixed = config(TransformerWeightLayout::ModelPrefix);
    assert!(
        TorchWeights::load(
            &cfg,
            &fixture("prefixed.safetensors"),
            TransformerDevice::Cpu,
            TransformerDtype::Float32
        )
        .is_err()
    );
    TorchWeights::load(
        &prefixed,
        &fixture("prefixed.safetensors"),
        TransformerDevice::Cpu,
        TransformerDtype::Float32,
    )
    .unwrap();
    let original = Tensor::read_safetensors(fixture("model.safetensors")).unwrap();
    let temp = tempfile::tempdir().unwrap();
    for change in ["missing", "shape", "nonfinite", "unexpected"] {
        let mut weights: Vec<_> = original
            .iter()
            .map(|(name, tensor)| (name.clone(), tensor.shallow_clone()))
            .collect();
        match change {
            "missing" => {
                weights.pop();
            }
            "shape" => {
                weights[0].1 = Tensor::zeros([1], (Kind::Float, tch::Device::Cpu));
            }
            "nonfinite" => {
                weights[0].1 = Tensor::full(
                    weights[0].1.size(),
                    f64::NAN,
                    (Kind::Float, tch::Device::Cpu),
                );
            }
            "unexpected" => {
                weights.push((
                    "surprise.weight".into(),
                    Tensor::zeros([1], (Kind::Float, tch::Device::Cpu)),
                ));
            }
            _ => unreachable!(),
        }
        let path = temp.path().join(format!("{change}.safetensors"));
        Tensor::write_safetensors(&weights, &path).unwrap();
        assert!(
            TorchWeights::load(
                &cfg,
                &path,
                TransformerDevice::Cpu,
                TransformerDtype::Float32
            )
            .is_err(),
            "{change}"
        );
    }
    let source = temp.path().join("owned.safetensors");
    std::fs::copy(fixture("model.safetensors"), &source).unwrap();
    let weights = TorchWeights::load(
        &cfg,
        &source,
        TransformerDevice::Cpu,
        TransformerDtype::Float32,
    )
    .unwrap();
    std::fs::remove_file(source).unwrap();
    let core = Qwen3::load(cfg, weights).unwrap();
    assert!(
        core.forward(&TransformerBatch {
            input_ids: vec![vec![1, 2]],
            attention_mask: vec![vec![1, 1]]
        })
        .is_ok()
    );
}

#[test]
fn executing_core_reports_its_actual_version() {
    assert_eq!(ken_torch_backend::device::core_version().unwrap(), "2.9.0");
}

#[test]
fn duplicate_or_truncated_parameter_archives_are_errors() {
    let cfg = config(TransformerWeightLayout::Unprefixed);
    let original = std::fs::read(fixture("model.safetensors")).unwrap();
    let length = u64::from_le_bytes(original[..8].try_into().unwrap()) as usize;
    let header = std::str::from_utf8(&original[8..8 + length])
        .unwrap()
        .trim();
    let map: Value = serde_json::from_str(header).unwrap();
    let (name, value) = map
        .as_object()
        .unwrap()
        .iter()
        .find(|(name, _)| name.as_str() != "__metadata__")
        .unwrap();
    let mut duplicate = format!(
        "{{{}:{},{}",
        serde_json::to_string(name).unwrap(),
        value,
        header.strip_prefix('{').unwrap()
    );
    while duplicate.len() % 8 != 0 {
        duplicate.push(' ');
    }
    let mut archive = (duplicate.len() as u64).to_le_bytes().to_vec();
    archive.extend(duplicate.as_bytes());
    archive.extend(&original[8 + length..]);
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("duplicate.safetensors");
    std::fs::write(&path, &archive).unwrap();
    assert!(
        TorchWeights::load(
            &cfg,
            &path,
            TransformerDevice::Cpu,
            TransformerDtype::Float32
        )
        .is_err(),
        "duplicate header names must not collapse in a JSON map"
    );
    std::fs::write(&path, &original[..original.len() - 1]).unwrap();
    assert!(
        TorchWeights::load(
            &cfg,
            &path,
            TransformerDevice::Cpu,
            TransformerDtype::Float32
        )
        .is_err()
    );
}

#[cfg(target_os = "macos")]
#[test]
fn actual_mps_preserves_cpu_rope_pow_variance_and_original_memory_controls() {
    use ken_torch_backend::device;
    assert!(
        tch::utils::has_mps(),
        "this macOS acceptance requires actual MPS"
    );
    let stats = device::prepare_mps().unwrap();
    assert!(stats.recommended_bytes > 0);
    assert!(
        (stats.high_watermark_bytes as f64 / stats.recommended_bytes as f64 - 0.7).abs() < 1e-6
    );
    let original: Value =
        serde_json::from_str(include_str!("fixtures/qwen/original.json")).unwrap();
    for case in original["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["device"] == "mps")
    {
        let cfg = config(TransformerWeightLayout::Unprefixed);
        let weights = TorchWeights::load(
            &cfg,
            &fixture("model.safetensors"),
            TransformerDevice::Mps,
            dtype(case["dtype"].as_str().unwrap()),
        )
        .unwrap();
        let core = Qwen3::load(cfg, weights).unwrap();
        let batch = TransformerBatch {
            input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
            attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
        };
        let output = core.forward(&batch).unwrap();
        assert_eq!(output.device(), tch::Device::Mps);
        let values: Vec<f32> = Vec::try_from(
            &output
                .to_kind(Kind::Float)
                .to_device(tch::Device::Cpu)
                .reshape([-1]),
        )
        .unwrap();
        let expected: Vec<f32> = serde_json::from_value(case["values"].clone()).unwrap();
        let error = values
            .iter()
            .zip(&expected)
            .map(|(a, b)| (a - b).abs())
            .fold(0.0_f32, f32::max);
        assert!(
            error <= 1e-6,
            "{} {} actual MPS error={error}",
            case["name"],
            case["dtype"]
        );
        drop(output);
        drop(core);
        device::empty_mps_cache().unwrap();
    }
}
