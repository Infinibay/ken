#[path = "support/fixture_json.rs"]
mod fixture_json;
use ken_models::{ContextEncoder, ContextInput, ContextModel, ModelAssets, NativeOnnxRuntime};
use serde_json::Value;
use std::{fs, path::PathBuf, sync::Arc};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "support/oracle_profiles.rs"]
mod profiles;

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/context")
}
fn runtime() -> NativeOnnxRuntime {
    NativeOnnxRuntime::from_json(
        include_str!("../resources/onnx-runtime-libraries.json"),
        &PathBuf::from(
            std::env::var_os("KEN_ORT_LIBRARY").expect("prepare KEN_ORT_LIBRARY for context tests"),
        ),
    )
    .unwrap()
}
fn fixture() -> ContextEncoder {
    let root = fixtures().join("valid");
    let model = ContextModel::from_json(&fs::read_to_string(root.join("definition.json")).unwrap())
        .unwrap();
    let snapshot = Arc::new(
        model
            .assets()
            .verify(&root.join("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
            .unwrap(),
    );
    ContextEncoder::new(model, snapshot, runtime()).unwrap()
}

fn vector(want: &Value, got: &[f32], tolerances: &Value) {
    let want = want.as_array().unwrap();
    assert_eq!(want.len(), got.len());
    let zero = want.iter().all(|x| x.as_f64().unwrap() == 0.);
    let (mut dot, mut norm_a, mut norm_b) = (0_f64, 0_f64, 0_f64);
    for (a, b) in want.iter().zip(got) {
        let a = a.as_f64().unwrap();
        let b = *b as f64;
        assert!(b.is_finite());
        if zero {
            assert_eq!(b, 0.);
        } else {
            assert!(
                (a - b).abs()
                    <= tolerances["atol"].as_f64().unwrap()
                        + tolerances["rtol"].as_f64().unwrap() * a.abs(),
                "wanted{a} got{b}"
            );
        }
        dot += a * b;
        norm_a += a * a;
        norm_b += b * b;
    }
    if !zero {
        assert!(dot / (norm_a * norm_b).sqrt() >= tolerances["cosine_min"].as_f64().unwrap());
    }
}

fn history(encoder: &ContextEncoder, case: &Value, result: &Value, tolerances: &Value) {
    assert_eq!(
        case["calls"].as_array().unwrap().len(),
        result["calls"].as_array().unwrap().len()
    );
    if case["prepare"].as_bool().unwrap() {
        encoder.prepare().unwrap();
    }
    for (call, expected) in case["calls"]
        .as_array()
        .unwrap()
        .iter()
        .zip(result["calls"].as_array().unwrap())
    {
        match call["op"].as_str().unwrap() {
            "tokens" => {
                let kind = match call["kind"].as_str().unwrap() {
                    "query" => ContextInput::Query,
                    "passage" => ContextInput::Passage,
                    _ => panic!("invalid fixture kind"),
                };
                assert_eq!(
                    serde_json::to_value(
                        encoder
                            .tokenize(call["text"].as_str().unwrap(), kind)
                            .unwrap()
                    )
                    .unwrap(),
                    *expected
                );
            }
            "query" => vector(
                expected,
                &encoder.embed_query(call["text"].as_str().unwrap()).unwrap(),
                tolerances,
            ),
            "passages" => {
                let texts: Vec<_> = call["texts"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|t| t.as_str().unwrap())
                    .collect();
                let got = encoder.embed_passages(&texts).unwrap();
                let wanted = expected.as_array().unwrap();
                assert_eq!(got.len(), wanted.len());
                for (a, b) in wanted.iter().zip(got) {
                    vector(a, &b, tolerances);
                }
            }
            _ => panic!("unknown fixture operation"),
        }
    }
}

#[test]
fn frozen_fixture_preserves_prefix_specials_raw_output_and_serialized_policy_override() {
    let oracle: Value =
        serde_json::from_slice(&fs::read(fixtures().join("valid/oracle.json")).unwrap()).unwrap();
    let model = ContextModel::from_json(
        &fs::read_to_string(fixtures().join("valid/definition.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(
        model.compatible_identity(),
        serde_json::json!({"spec":oracle["spec"],"spec_key":oracle["spec_key"],"tokenizer_revision":oracle["tokenizer_revision"]})
    );
    for (case, result) in oracle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(oracle["results"].as_array().unwrap())
    {
        let encoder = fixture();
        assert_eq!(encoder.dim(), 768);
        history(&encoder, case, result, &oracle["tolerances"]);
    }
    let vector = fixture().embed_query("red").unwrap();
    assert_eq!(&vector[..2], &[12., 4.]);
}

#[test]
fn malformed_graphs_and_outputs_return_errors_including_hidden_extra_rows() {
    let manifest: Value =
        serde_json::from_slice(&fs::read(fixtures().join("manifest.json")).unwrap()).unwrap();
    for row in manifest["invalid"].as_array().unwrap() {
        let model = ContextModel::from_json(
            &fs::read_to_string(fixtures().join(row["definition"].as_str().unwrap())).unwrap(),
        )
        .unwrap();
        let snapshot = Arc::new(
            model
                .assets()
                .verify(&fixtures().join(row["snapshot"].as_str().unwrap()))
                .unwrap(),
        );
        let encoder = ContextEncoder::new(model, snapshot, runtime()).unwrap();
        assert!(encoder.embed_query("red").is_err(), "{}", row["id"]);
    }
}

#[test]
fn empty_passages_need_no_runtime_and_results_are_independent_under_concurrency() {
    let root = fixtures().join("valid");
    let model = ContextModel::from_json(&fs::read_to_string(root.join("definition.json")).unwrap())
        .unwrap();
    let snapshot = Arc::new(
        model
            .assets()
            .verify(&root.join("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
            .unwrap(),
    );
    let missing = NativeOnnxRuntime::from_json(
        include_str!("../resources/onnx-runtime-libraries.json"),
        &std::env::temp_dir().join("absent-ken-context-core"),
    )
    .unwrap();
    let encoder = ContextEncoder::new(model, snapshot, missing).unwrap();
    assert!(encoder.embed_passages(&[]).unwrap().is_empty());
    assert!(encoder.embed_query("red").is_err());
    let encoder = Arc::new(fixture());
    let mut rows = encoder.embed_passages(&["red", "red"]).unwrap();
    rows[0].fill(99.);
    assert_eq!(rows[1], encoder.embed_passages(&["red"]).unwrap()[0]);
    let inputs = [
        ("red", [12., 4.]),
        ("red red", [14., 5.]),
        ("mystery", [10., 4.]),
        ("", [10., 3.]),
    ];
    let threads: Vec<_> = (0..8)
        .map(|index| {
            let encoder = Arc::clone(&encoder);
            let (text, expected) = inputs[index % inputs.len()];
            std::thread::spawn(move || {
                let vector = encoder.embed_query(text).unwrap();
                assert_eq!(&vector[..2], &expected);
                assert!(vector[2..].iter().all(|v| *v == 0.));
            })
        })
        .collect();
    for thread in threads {
        thread.join().unwrap();
    }
}

#[test]
fn snapshot_must_accredit_the_context_models_exact_artifacts() {
    let root = fixtures().join("valid");
    let definition = fs::read_to_string(root.join("definition.json")).unwrap();
    let model = ContextModel::from_json(&definition).unwrap();
    let other = ModelAssets::from_json(
        &fs::read_to_string(fixtures().join("extra-row/definition.json")).unwrap(),
    )
    .unwrap();
    let snapshot = Arc::new(
        other
            .verify(&fixtures().join("extra-row/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
            .unwrap(),
    );
    assert!(ContextEncoder::new(model, snapshot, runtime()).is_err());
}

#[test]
fn first_query_is_lazy_and_missing_runtime_is_an_error_in_clean_processes() {
    for scenario in ["valid", "missing"] {
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "lazy_context_child", "--nocapture"])
            .env("KEN_CONTEXT_LAZY_CASE", scenario)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{scenario}: {}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }
}

#[test]
fn lazy_context_child() {
    let Ok(scenario) = std::env::var("KEN_CONTEXT_LAZY_CASE") else {
        return;
    };
    if scenario == "valid" {
        let encoder = fixture();
        assert!(!encoder.is_prepared().unwrap());
        assert_eq!(&encoder.embed_query("red").unwrap()[..2], &[12., 4.]);
        assert!(encoder.is_prepared().unwrap());
    } else {
        let root = fixtures().join("valid");
        let model =
            ContextModel::from_json(&fs::read_to_string(root.join("definition.json")).unwrap())
                .unwrap();
        let snapshot = Arc::new(
            model
                .assets()
                .verify(&root.join("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
                .unwrap(),
        );
        let missing = NativeOnnxRuntime::from_json(
            include_str!("../resources/onnx-runtime-libraries.json"),
            &std::env::temp_dir().join("absent-ken-cold-context-core"),
        )
        .unwrap();
        let encoder = ContextEncoder::new(model, snapshot, missing).unwrap();
        assert!(encoder.embed_passages(&[]).unwrap().is_empty());
        assert!(!encoder.is_prepared().unwrap());
        assert!(encoder.embed_query("red").is_err());
    }
}

fn original_for_host(os: &str, arch: &str) -> Value {
    let (system, machine) = match (os, arch) {
        ("linux", "x86_64") => ("Linux", "x86_64"),
        ("linux", "aarch64") => ("Linux", "aarch64"),
        ("macos", "aarch64") => ("Darwin", "arm64"),
        _ => panic!("prepare a separate original oracle for this OS/architecture"),
    };
    let original: Value = if (os, arch) == ("linux", "x86_64") {
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            let reference =
                profiles::registered("context", &profiles::context_descriptor(), &repo())
                    .expect("registered original for actual contextual execution profile");
            assert_eq!(reference.encoding, "json");
            serde_json::from_slice(&reference.bytes).unwrap()
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            serde_json::from_slice(
                &fs::read(fixtures().join("linux-x86_64-original.json")).unwrap(),
            )
            .unwrap()
        }
    } else {
        let document: Value = serde_json::from_slice(&fixture_json::decode(include_bytes!(
            "fixtures/portable/context-reference.json.gz"
        )))
        .unwrap();
        document["platforms"][format!("{system}/{machine}")].clone()
    };
    assert_eq!(original["platform"], system, "crossed original OS");
    assert_eq!(
        original["architecture"], machine,
        "crossed original architecture"
    );
    original
}

#[test]
fn registered_context_matches_all_twenty_local_frozen_histories() {
    let oracle = original_for_host(std::env::consts::OS, std::env::consts::ARCH);
    let native = runtime();
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        let actual = native.load().unwrap();
        let descriptor = profiles::context_descriptor();
        assert_eq!(descriptor["native_core_sha256"], actual.sha256);
        assert_eq!(descriptor["onnxruntime"], actual.version);
    }
    let definition =
        fs::read_to_string(repo().join("src/ken/embedder/data/code-context-int8.json")).unwrap();
    let model = ContextModel::from_json(&definition).unwrap();
    assert_eq!(
        model.compatible_identity(),
        serde_json::json!({"spec":oracle["spec"],"spec_key":oracle["spec_key"],"tokenizer_revision":oracle["tokenizer_revision"]})
    );
    let snapshot = Arc::new(
        model
            .assets()
            .verify(&PathBuf::from(
                std::env::var_os("KEN_CONTEXT_SNAPSHOT")
                    .expect("prepare KEN_CONTEXT_SNAPSHOT for real context parity"),
            ))
            .unwrap(),
    );
    for (case, result) in oracle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(oracle["results"].as_array().unwrap())
    {
        let encoder =
            ContextEncoder::new(model.clone(), Arc::clone(&snapshot), native.clone()).unwrap();
        history(&encoder, case, result, &oracle["tolerances"]);
    }
}

#[test]
fn original_selection_keeps_each_host_and_rejects_crossed_or_unknown_targets() {
    use sha2::{Digest, Sha256};
    let mut cases = None;
    for (os, arch, system, machine) in [
        ("linux", "x86_64", "Linux", "x86_64"),
        ("linux", "aarch64", "Linux", "aarch64"),
        ("macos", "aarch64", "Darwin", "arm64"),
    ] {
        let original = original_for_host(os, arch);
        assert_eq!(original["platform"], system);
        assert_eq!(original["architecture"], machine);
        assert_eq!(original["cases"].as_array().unwrap().len(), 20);
        assert_eq!(original["results"].as_array().unwrap().len(), 20);
        if let Some(expected) = &cases {
            assert_eq!(&original["cases"], expected);
        }
        cases = Some(original["cases"].clone());
    }
    for (os, arch) in [
        ("linux", "arm64"),
        ("macos", "x86_64"),
        ("windows", "x86_64"),
    ] {
        assert!(std::panic::catch_unwind(|| original_for_host(os, arch)).is_err());
    }
    let fixture = fs::read(fixtures().join("linux-x86_64-original.json")).unwrap();
    assert_eq!(
        format!("{:x}", Sha256::digest(fixture)),
        "b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733"
    );
}
