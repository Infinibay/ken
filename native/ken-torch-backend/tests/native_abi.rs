//! The production ABI executes actual tiny Qwen data, never fixture arithmetic.
use ken_native_model_api::{
    BACKEND_TORCH, KenBuffer, KenBytes, MAX_PAYLOAD, TransformerArchitecture, TransformerBatch,
    TransformerDeviceRequest, TransformerDtype, TransformerOpenRequest, TransformerOutput,
    TransformerPooling, TransformerPrepared, TransformerRunRequest, TransformerRunResult,
    TransformerWeightLayout, api_table, checked_json,
};
use ken_torch_backend::ken_model_api_v1;
use std::path::Path;

#[test]
fn raw_tied_projection_matches_original_without_sigmoid_or_normalization() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/qwen");
    let original: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/qwen/original.json")).unwrap();
    let table = unsafe { api_table(ken_model_api_v1(), BACKEND_TORCH) }.unwrap();
    for case in original["cases"].as_array().unwrap() {
        if case["device"] == "mps" && !cfg!(target_os = "macos") {
            continue;
        }
        let device = if case["device"] == "mps" {
            assert!(tch::utils::has_mps());
            TransformerDeviceRequest::Mps
        } else {
            TransformerDeviceRequest::Cpu
        };
        let dtype = serde_json::from_value(case["dtype"].clone()).unwrap();
        let request = TransformerOpenRequest {
            schema: 1,
            snapshot: root.to_str().unwrap().into(),
            architecture: TransformerArchitecture::Qwen3,
            weight_files: vec!["model.safetensors".into()],
            weight_layout: TransformerWeightLayout::Unprefixed,
            dtype,
            device,
            pooling: TransformerPooling::Last,
            normalize_modules: 0,
        };
        let bytes = serde_json::to_vec(&request).unwrap();
        let mut handle = 0;
        let mut output = KenBuffer::EMPTY;
        assert_eq!(
            unsafe {
                table.open.unwrap()(KenBytes::new(&bytes).unwrap(), &mut handle, &mut output)
            },
            0
        );
        assert_eq!(unsafe { table.release.unwrap()(&mut output) }, 0);
        let request = TransformerRunRequest {
            schema: 1,
            batch: TransformerBatch {
                input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
                attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
            },
            output: TransformerOutput::YesMinusNo {
                true_id: 1,
                false_id: 6,
            },
        };
        let bytes = serde_json::to_vec(&request).unwrap();
        assert_eq!(
            unsafe { table.run.unwrap()(handle, KenBytes::new(&bytes).unwrap(), &mut output) },
            0,
            "raw head mode must execute"
        );
        let actual: TransformerRunResult = unsafe {
            checked_json(
                KenBytes {
                    ptr: output.ptr,
                    len: output.len,
                },
                MAX_PAYLOAD,
            )
        }
        .unwrap();
        actual.validate(2, 1).unwrap();
        let expected: Vec<f32> = serde_json::from_value(case["tied_scores"].clone()).unwrap();
        assert!(
            actual
                .values
                .iter()
                .zip(&expected)
                .all(|(a, b)| (a - b).abs() <= 1e-6),
            "raw logits {} {}",
            case["device"],
            case["dtype"]
        );
        assert_eq!(unsafe { table.release.unwrap()(&mut output) }, 0);
        assert_eq!(unsafe { table.close.unwrap()(handle) }, 0);
    }
}

#[test]
fn production_api_prepares_runs_rejects_bad_tokens_and_releases_real_results() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/qwen");
    let table = unsafe { api_table(ken_model_api_v1(), BACKEND_TORCH) }.unwrap();
    let request = TransformerOpenRequest {
        schema: 1,
        snapshot: root.to_str().unwrap().into(),
        architecture: TransformerArchitecture::Qwen3,
        weight_files: vec!["model.safetensors".into()],
        weight_layout: TransformerWeightLayout::Unprefixed,
        dtype: TransformerDtype::Float32,
        device: TransformerDeviceRequest::Cpu,
        pooling: TransformerPooling::Last,
        normalize_modules: 1,
    };
    let bytes = serde_json::to_vec(&request).unwrap();
    let mut handle = 0;
    let mut output = KenBuffer::EMPTY;
    assert_eq!(
        unsafe { table.open.unwrap()(KenBytes::new(&bytes).unwrap(), &mut handle, &mut output) },
        0
    );
    let prepared: TransformerPrepared = unsafe {
        checked_json(
            KenBytes {
                ptr: output.ptr,
                len: output.len,
            },
            MAX_PAYLOAD,
        )
    }
    .unwrap();
    assert_eq!(prepared.core_version, "2.9.0");
    assert_eq!(prepared.dimension, 4);
    assert_eq!(
        prepared.device,
        ken_native_model_api::TransformerDevice::Cpu
    );
    assert_eq!(prepared.dtype, TransformerDtype::Float32);
    assert_eq!(unsafe { table.release.unwrap()(&mut output) }, 0);
    let batch = TransformerBatch {
        input_ids: vec![vec![1, 3, 5, 0], vec![2, 4, 0, 0]],
        attention_mask: vec![vec![1, 1, 1, 0], vec![1, 1, 0, 0]],
    };
    let run = TransformerRunRequest {
        schema: 1,
        batch: batch.clone(),
        output: TransformerOutput::Sentence,
    };
    let bytes = serde_json::to_vec(&run).unwrap();
    assert_eq!(
        unsafe { table.run.unwrap()(handle, KenBytes::new(&bytes).unwrap(), &mut output) },
        0
    );
    let result: TransformerRunResult = unsafe {
        checked_json(
            KenBytes {
                ptr: output.ptr,
                len: output.len,
            },
            MAX_PAYLOAD,
        )
    }
    .unwrap();
    result.validate(2, 4).unwrap();
    let original: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/qwen/original.json")).unwrap();
    let case = original["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "padding" && c["device"] == "cpu" && c["dtype"] == "float32")
        .unwrap();
    let hidden: Vec<f32> = serde_json::from_value(case["values"].clone()).unwrap();
    for row in 0..2 {
        let last = batch.attention_mask[row]
            .iter()
            .rposition(|&v| v == 1)
            .unwrap();
        let offset = (row * 4 + last) * 4;
        let expected = &hidden[offset..offset + 4];
        let norm = expected.iter().map(|v| v * v).sum::<f32>().sqrt();
        assert!(
            result.values[row * 4..row * 4 + 4]
                .iter()
                .zip(expected)
                .all(|(a, b)| (a - b / norm).abs() <= 1e-6)
        );
    }
    let mut stale = output;
    assert_eq!(unsafe { table.release.unwrap()(&mut output) }, 0);
    assert_ne!(unsafe { table.release.unwrap()(&mut stale) }, 0);
    let mut invalid = run;
    invalid.batch.input_ids[0][0] = 8;
    let bytes = serde_json::to_vec(&invalid).unwrap();
    assert_ne!(
        unsafe { table.run.unwrap()(handle, KenBytes::new(&bytes).unwrap(), &mut output) },
        0
    );
    assert!(output.len <= ken_native_model_api::MAX_DIAGNOSTIC);
    assert_eq!(unsafe { table.release.unwrap()(&mut output) }, 0);
    assert_eq!(unsafe { table.close.unwrap()(handle) }, 0);
    assert_ne!(unsafe { table.close.unwrap()(handle) }, 0);
}
