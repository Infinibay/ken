//! Isolated Task4 caller contract; acceptance stays blocked on Task3 full proof.
//! Catches wrong XLM-R positions/masks/pooling, malformed weights and borrowed ZIP data.
use ken_native_model_api::{
    BACKEND_TORCH, KenBuffer, KenBytes, KenModelApiV1, MAX_PAYLOAD, TransformerArchitecture,
    TransformerBatch, TransformerDeviceRequest, TransformerOpenRequest, TransformerOutput,
    TransformerPooling, TransformerPrepared, TransformerRunRequest, TransformerRunResult,
    TransformerWeightLayout, api_table, checked_bytes,
};
use ken_torch_backend::ken_model_api_v1;
use serde_json::Value;
use std::path::{Path, PathBuf};

fn api() -> KenModelApiV1 {
    // SAFETY: the statically linked backend table lives for this test process.
    unsafe { api_table(ken_model_api_v1(), BACKEND_TORCH) }.unwrap()
}

fn take_output(buffer: &mut KenBuffer) -> Vec<u8> {
    // SAFETY: the live backend returned this owned buffer, which is read before release.
    let bytes = unsafe {
        checked_bytes(
            KenBytes {
                ptr: buffer.ptr,
                len: buffer.len,
            },
            MAX_PAYLOAD,
        )
    }
    .unwrap()
    .to_vec();
    assert_eq!(unsafe { api().release.unwrap()(buffer) }, 0);
    bytes
}

struct Session(u64);
impl Session {
    fn open(request: &TransformerOpenRequest) -> Result<Self, String> {
        let bytes = serde_json::to_vec(request).unwrap();
        let mut handle = 0;
        let mut buffer = KenBuffer::EMPTY;
        let status = unsafe {
            api().open.unwrap()(KenBytes::new(&bytes).unwrap(), &mut handle, &mut buffer)
        };
        let output = take_output(&mut buffer);
        if status != 0 {
            assert_eq!(handle, 0, "failed preparation must publish no model");
            return Err(String::from_utf8(output).unwrap());
        }
        let prepared: TransformerPrepared = serde_json::from_slice(&output).unwrap();
        assert_eq!(prepared.dimension, 8);
        assert_eq!(prepared.dtype, request.dtype);
        assert_eq!(prepared.core_version, "2.9.0");
        let expected = match request.device {
            TransformerDeviceRequest::Cpu => ken_native_model_api::TransformerDevice::Cpu,
            TransformerDeviceRequest::Mps => ken_native_model_api::TransformerDevice::Mps,
            _ => unreachable!("fixture uses explicit devices"),
        };
        assert_eq!(
            prepared.device, expected,
            "prepared identity must describe the actual owned tensors"
        );
        Ok(Self(handle))
    }
    fn sentence(&self, case: &Value) -> TransformerRunResult {
        let request = TransformerRunRequest {
            schema: 1,
            batch: TransformerBatch {
                input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
                attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
            },
            output: TransformerOutput::Sentence,
        };
        let bytes = serde_json::to_vec(&request).unwrap();
        let mut buffer = KenBuffer::EMPTY;
        let status =
            unsafe { api().run.unwrap()(self.0, KenBytes::new(&bytes).unwrap(), &mut buffer) };
        let output = take_output(&mut buffer);
        assert_eq!(status, 0, "{}", String::from_utf8_lossy(&output));
        let result: TransformerRunResult = serde_json::from_slice(&output).unwrap();
        result.validate(2, 8).unwrap();
        result
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        // The test owner closes every successfully prepared native model.
        let _ = unsafe { api().close.unwrap()(self.0) };
    }
}
fn fixture() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/xlmr")
}
fn original() -> Value {
    serde_json::from_slice(&std::fs::read(fixture().join("original.json")).unwrap()).unwrap()
}
fn request(root: &Path, case: &Value, pooling: TransformerPooling) -> TransformerOpenRequest {
    TransformerOpenRequest {
        schema: 1,
        snapshot: root.to_str().unwrap().into(),
        architecture: TransformerArchitecture::XlmRoberta,
        weight_files: vec!["pytorch_model.bin".into()],
        weight_layout: TransformerWeightLayout::Unprefixed,
        dtype: serde_json::from_value(case["dtype"].clone()).unwrap(),
        device: if case["device"] == "mps" {
            TransformerDeviceRequest::Mps
        } else {
            TransformerDeviceRequest::Cpu
        },
        pooling,
        normalize_modules: 1,
    }
}
fn assert_vectors(result: &TransformerRunResult, case: &Value, name: &str) {
    let expected: Vec<f32> =
        serde_json::from_value(case["sentence_vectors"][name].clone()).unwrap();
    assert_eq!(result.values.len(), expected.len());
    let maximum = result
        .values
        .iter()
        .zip(&expected)
        .map(|(&a, &b)| (a - b).abs())
        .fold(0.0_f32, f32::max);
    assert!(
        maximum <= 1e-6,
        "{} {} {} {name}: {maximum}",
        case["device"],
        case["dtype"],
        case["name"]
    );
}

#[test]
fn xlm_roberta_original_padding_and_literal_pad_positions_match_all_pooling_modes() {
    let data = original();
    for case in data["cases"].as_array().unwrap() {
        if case["device"] == "mps" && !cfg!(target_os = "macos") {
            continue;
        }
        if case["device"] == "mps" {
            assert!(tch::utils::has_mps());
        }
        for (name, pooling) in [
            ("cls", TransformerPooling::Cls),
            ("mean", TransformerPooling::Mean),
            ("last", TransformerPooling::Last),
        ] {
            let session = Session::open(&request(&fixture(), case, pooling))
                .expect("production XLM-R ZIP preparation must execute");
            assert_vectors(&session.sentence(case), case, name);
        }
    }
}

#[test]
fn xlm_roberta_keeps_owned_tensors_after_archive_and_config_are_removed() {
    let data = original();
    let case = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["device"] == "cpu" && case["dtype"] == "float32")
        .unwrap();
    let temp = tempfile::tempdir().unwrap();
    for name in ["config.json", "pytorch_model.bin"] {
        std::fs::copy(fixture().join(name), temp.path().join(name)).unwrap();
    }
    let session = Session::open(&request(temp.path(), case, TransformerPooling::Last)).unwrap();
    for name in ["config.json", "pytorch_model.bin"] {
        std::fs::remove_file(temp.path().join(name)).unwrap();
    }
    let first = session.sentence(case);
    assert_vectors(&first, case, "last");
    assert_eq!(
        first.values,
        session.sentence(case).values,
        "forward must retain no request KV state"
    );
}

#[test]
fn xlm_roberta_rejects_malformed_archives_and_invalid_declared_parameters() {
    let data = original();
    let case = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["device"] == "cpu" && case["dtype"] == "float32")
        .unwrap();
    let temp = tempfile::tempdir().unwrap();
    std::fs::copy(
        fixture().join("config.json"),
        temp.path().join("config.json"),
    )
    .unwrap();
    for name in [
        "missing.bin",
        "wrong-shape.bin",
        "nonfinite.bin",
        "unexpected.bin",
        "nonfloat.bin",
        "duplicate-entry.bin",
        "bad-name.bin",
        "truncated.bin",
        "missing-pooler.bin",
        "wrong-pooler.bin",
        "unexpected-pooler.bin",
        "nonfinite-pooler.bin",
    ] {
        std::fs::copy(
            fixture().join("pytorch_model.bin"),
            temp.path().join("pytorch_model.bin"),
        )
        .unwrap();
        let valid = Session::open(&request(temp.path(), case, TransformerPooling::Cls)).unwrap();
        assert_vectors(&valid.sentence(case), case, "cls");
        drop(valid);
        std::fs::copy(
            fixture().join("invalid").join(name),
            temp.path().join("pytorch_model.bin"),
        )
        .unwrap();
        assert!(
            Session::open(&request(temp.path(), case, TransformerPooling::Cls)).is_err(),
            "accepted invalid original archive {name}"
        );
    }
}

#[test]
fn xlm_roberta_hidden_states_match_original_before_pooling() {
    use ken_torch_backend::{
        xlm_roberta::{XlmRoberta, XlmRobertaConfig},
        xlm_roberta_weights::XlmRobertaWeights,
    };
    let data = original();
    for case in data["cases"].as_array().unwrap() {
        if case["device"] == "mps" && !cfg!(target_os = "macos") {
            continue;
        }
        let open = request(&fixture(), case, TransformerPooling::Cls);
        let device = if case["device"] == "mps" {
            ken_native_model_api::TransformerDevice::Mps
        } else {
            ken_native_model_api::TransformerDevice::Cpu
        };
        let config = XlmRobertaConfig::from_json(
            &std::fs::read_to_string(fixture().join("config.json")).unwrap(),
            open.weight_layout,
        )
        .unwrap();
        let weights = XlmRobertaWeights::load(
            &config,
            &fixture().join("pytorch_model.bin"),
            device,
            open.dtype,
        )
        .unwrap();
        let network = XlmRoberta::load(config, weights).unwrap();
        let batch = TransformerBatch {
            input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
            attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
        };
        let hidden = network
            .forward(&batch)
            .unwrap()
            .to_device(tch::Device::Cpu)
            .to_kind(tch::Kind::Float);
        let shape: Vec<i64> = serde_json::from_value(case["shape"].clone()).unwrap();
        assert_eq!(hidden.size(), shape);
        let actual: Vec<f32> = Vec::try_from(hidden.reshape([-1])).unwrap();
        let expected: Vec<f32> = serde_json::from_value(case["values"].clone()).unwrap();
        let maximum = actual
            .iter()
            .zip(expected)
            .map(|(&a, b)| (a - b).abs())
            .fold(0.0_f32, f32::max);
        assert!(
            maximum <= 1e-6,
            "{} {} {} hidden: {maximum}",
            case["name"],
            case["device"],
            case["dtype"]
        );
    }
}

#[test]
fn xlm_roberta_requires_the_declared_prefix_and_has_no_judge_head() {
    let data = original();
    let case = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["device"] == "cpu" && c["dtype"] == "float32")
        .unwrap();
    let temp = tempfile::tempdir().unwrap();
    std::fs::copy(
        fixture().join("config.json"),
        temp.path().join("config.json"),
    )
    .unwrap();
    std::fs::copy(
        fixture().join("model-prefix.bin"),
        temp.path().join("pytorch_model.bin"),
    )
    .unwrap();
    let mut open = request(temp.path(), case, TransformerPooling::Cls);
    assert!(
        Session::open(&open).is_err(),
        "a prefixed archive requires an explicit matching layout"
    );
    open.weight_layout = TransformerWeightLayout::ModelPrefix;
    let session = Session::open(&open).unwrap();
    assert_vectors(&session.sentence(case), case, "cls");
    let batch = TransformerBatch {
        input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
        attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
    };
    let bytes = serde_json::to_vec(&TransformerRunRequest {
        schema: 1,
        batch,
        output: TransformerOutput::YesMinusNo {
            true_id: 2,
            false_id: 3,
        },
    })
    .unwrap();
    let mut buffer = KenBuffer::EMPTY;
    let status =
        unsafe { api().run.unwrap()(session.0, KenBytes::new(&bytes).unwrap(), &mut buffer) };
    let error = take_output(&mut buffer);
    assert_ne!(status, 0);
    assert!(
        String::from_utf8(error)
            .unwrap()
            .contains("no declared yes/no head")
    );
    assert_vectors(&session.sentence(case), case, "cls");
}
