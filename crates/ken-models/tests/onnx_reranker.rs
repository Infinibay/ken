use ken_models::{NativeOnnxRuntime, OnnxReranker, RerankOptions, RerankerModel};
use serde_json::{Value, json};
use std::{fs, path::PathBuf, sync::Arc};

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/ettin")
}
fn manifest() -> Value {
    serde_json::from_slice(&fs::read(root().join("manifest.json")).unwrap()).unwrap()
}
fn runtime() -> NativeOnnxRuntime {
    NativeOnnxRuntime::from_json(
        include_str!("../resources/onnx-runtime-libraries.json"),
        &PathBuf::from(
            std::env::var_os("KEN_ORT_LIBRARY").expect("prepare KEN_ORT_LIBRARY for Ettin tests"),
        ),
    )
    .unwrap()
}
fn fixture(row: &Value, options: RerankOptions) -> OnnxReranker {
    let model = RerankerModel::from_json(&row["definition"].to_string()).unwrap();
    let prepared = Arc::new(
        model
            .verify_prepared(&root().join(row["prepared"].as_str().unwrap()))
            .unwrap(),
    );
    OnnxReranker::new(
        model,
        Some(prepared),
        None,
        root().join("unused-cache"),
        runtime(),
        options,
    )
    .unwrap()
}

fn changed_policy(changes: &[(&str, Value)]) -> OnnxReranker {
    use sha2::{Digest, Sha256};
    let data = manifest();
    let row = &data["pair"];
    let mut definition = row["definition"].clone();
    let temp = tempfile::tempdir().unwrap();
    for name in [
        "model.onnx",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ] {
        let mut bytes =
            fs::read(root().join(row["prepared"].as_str().unwrap()).join(name)).unwrap();
        if let Some((_, change)) = changes.iter().find(|(changed, _)| *changed == name) {
            bytes = serde_json::to_vec(change).unwrap();
        }
        fs::write(temp.path().join(name), &bytes).unwrap();
        if name != "model.onnx" {
            definition["source"]["artifacts"][name] =
                json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(&bytes))});
        }
    }
    let model = RerankerModel::from_json(&definition.to_string()).unwrap();
    let prepared = Arc::new(model.verify_prepared(temp.path()).unwrap());
    OnnxReranker::new(
        model,
        Some(prepared),
        None,
        temp.path().join("unused"),
        runtime(),
        RerankOptions::default(),
    )
    .unwrap()
}

#[test]
fn invalid_model_limits_and_padding_types_cannot_silently_select_a_policy() {
    for limit in [
        json!(true),
        json!(0),
        json!(-1),
        json!(1.5),
        json!("1024"),
        json!(1023),
    ] {
        for (file, config) in [
            (
                "config.json",
                json!({"pad_token_id":7,"max_position_embeddings":limit}),
            ),
            (
                "tokenizer_config.json",
                json!({"pad_token":"[PAD]","model_max_length":limit}),
            ),
        ] {
            assert!(
                changed_policy(&[(file, config)])
                    .score("x", &["y"])
                    .is_err()
            );
        }
    }
    for id in [
        json!(true),
        json!(-1),
        json!(7.0),
        json!("7"),
        json!(4294967303_u64),
    ] {
        assert!(
            changed_policy(&[("config.json", json!({"pad_token_id":id}))])
                .score("x", &["y"])
                .is_err()
        );
    }
    for config in [
        json!({"padding_side":null,"pad_token":"[PAD]"}),
        json!({"pad_token":{"content":false}}),
        json!({"pad_token":"missing"}),
    ] {
        assert!(
            changed_policy(&[("tokenizer_config.json", config)])
                .score("x", &["y"])
                .is_err()
        );
    }
}

#[test]
fn explicit_pair_policy_overrides_serialized_padding_truncation_and_accepts_content_token() {
    let row = &manifest()["pair"];
    let mut tokenizer: Value = serde_json::from_slice(
        &fs::read(
            root()
                .join(row["prepared"].as_str().unwrap())
                .join("tokenizer.json"),
        )
        .unwrap(),
    )
    .unwrap();
    tokenizer["truncation"] =
        json!({"max_length":8,"stride":2,"strategy":"LongestFirst","direction":"Left"});
    tokenizer["padding"] = json!({"strategy":{"Fixed":20},"direction":"Left","pad_to_multiple_of":null,"pad_id":0,"pad_type_id":99,"pad_token":"[UNK]"});
    let scorer = changed_policy(&[
        ("tokenizer.json", tokenizer),
        (
            "config.json",
            json!({"pad_token_id":7,"max_position_embeddings":null}),
        ),
        (
            "tokenizer_config.json",
            json!({"pad_token":{"content":"[PAD]"},"model_max_length":1024}),
        ),
    ]);
    let tokens = scorer.tokenize_pairs("x", &["y", "x x x"]).unwrap();
    assert_eq!(tokens[0].ids, [8, 1, 9, 2, 9, 7, 7]);
    assert_eq!(
        scorer.score("x", &["y", "x x x"]).unwrap().scores,
        [29., 30.]
    );
}

#[test]
fn non_f32_output_is_an_explicit_integrity_error() {
    assert!(
        fixture(&manifest()["non_f32"], RerankOptions::default())
            .score("x", &["y"])
            .is_err()
    );
}

#[test]
fn first_lazy_score_initializes_native_api_in_a_cold_process() {
    if std::env::var_os("KEN_ETTIN_COLD_CHILD").is_none() {
        let result = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "first_lazy_score_initializes_native_api_in_a_cold_process",
                "--nocapture",
            ])
            .env("KEN_ETTIN_COLD_CHILD", "1")
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{} {}",
            String::from_utf8_lossy(&result.stdout),
            String::from_utf8_lossy(&result.stderr)
        );
        assert!(String::from_utf8_lossy(&result.stdout).contains("cold first score29"));
        return;
    }
    assert_eq!(
        fixture(&manifest()["pair"], RerankOptions::default())
            .score("x", &["y"])
            .unwrap()
            .scores,
        [29.]
    );
    println!("cold first score29");
}

#[test]
fn raw_pair_scores_preserve_order_padding_and_remainder_batches() {
    for batch in [1, 3, 10] {
        let scorer = fixture(
            &manifest()["pair"],
            RerankOptions::new(batch, 4, 1024).unwrap(),
        );
        assert!(!scorer.is_prepared().unwrap());
        let tokens = scorer
            .tokenize_pairs("x", &["y", "x x x", "x", "y y"])
            .unwrap();
        assert_eq!(tokens[0].ids, [8, 1, 9, 2, 9, 7, 7]);
        assert_eq!(tokens[0].attention_mask, [1, 1, 1, 1, 1, 0, 0]);
        let result = scorer.score("x", &["y", "x x x", "x", "y y"]).unwrap();
        assert_eq!(result.scores, [29., 30., 28., 31.]);
        assert_eq!(result.details.pair_tokens, [5, 7, 5, 6]);
        assert_eq!(result.details.pad_id, Some(7));
        assert_eq!(result.details.truncated_documents, 0);
        assert!(result.details.token_ms.is_finite() && result.details.token_ms >= 0.);
        assert!(result.details.inference_ms.is_finite() && result.details.inference_ms >= 0.);
        assert!(scorer.is_prepared().unwrap());
    }
}

#[test]
fn session_policy_is_available_only_after_successful_cpu_load() {
    let scorer = fixture(&manifest()["pair"], RerankOptions::new(3, 2, 512).unwrap());
    assert!(scorer.session_policy().unwrap().is_none());
    assert!(scorer.score("x", &[]).unwrap().scores.is_empty());
    assert!(scorer.session_policy().unwrap().is_none());
    assert_eq!(scorer.score("x", &["y"]).unwrap().scores, [29.]);
    let policy = scorer.session_policy().unwrap().unwrap();
    assert_eq!(policy.providers, ["CPUExecutionProvider"]);
    assert!(policy.cpu_arena);
    assert_eq!(policy.intra_threads, 2);
    assert_eq!(policy.inter_threads, 1);
}

#[test]
fn empty_pool_and_top11_do_not_load_and_model_failure_precedes_query_guard() {
    let model = RerankerModel::from_json(&manifest()["pair"]["definition"].to_string()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let missing = NativeOnnxRuntime::from_json(
        include_str!("../resources/onnx-runtime-libraries.json"),
        &temp.path().join("absent-core"),
    )
    .unwrap();
    let scorer = OnnxReranker::new(
        model,
        None,
        None,
        temp.path().join("absent-model"),
        missing,
        RerankOptions::default(),
    )
    .unwrap();
    assert_eq!(
        serde_json::to_value(scorer.score("x", &[]).unwrap()).unwrap(),
        json!({"scores":[],"details":{"token_ms":0.,"inference_ms":0.,"truncated_documents":0,"pair_tokens":[]}})
    );
    let err = scorer.score("x", &["x"; 11]).unwrap_err().to_string();
    assert!(err.contains("top10"), "{err}");
    assert!(!scorer.is_prepared().unwrap());
    let err = scorer
        .score(&"x".repeat(65537), &["y"])
        .unwrap_err()
        .to_string();
    assert!(
        !err.contains("query is too long"),
        "load must fail first: {err}"
    );
    assert!(scorer.pair_fits("x", "y").is_err());
    assert!(!scorer.is_prepared().unwrap());
    assert!(!temp.path().join("absent-model").exists());
}

#[test]
fn options_reject_zero_nonintegers_and_thread_budget_wraparound() {
    for args in [
        (0, 4, 1024),
        (1, 0, 1024),
        (1, 4, 0),
        (1, 1_usize << 32, 1024),
    ] {
        assert!(RerankOptions::new(args.0, args.1, args.2).is_err());
    }
    for input in [
        r#"{"batch_size":true}"#,
        r#"{"intra_op_threads":-1}"#,
        r#"{"max_tokens":1.5}"#,
    ] {
        assert!(serde_json::from_str::<RerankOptions>(input).is_err());
    }
    let model = RerankerModel::from_json(&manifest()["pair"]["definition"].to_string()).unwrap();
    let invalid = RerankOptions {
        batch_size: 0,
        ..RerankOptions::default()
    };
    assert!(
        OnnxReranker::new(model, None, None, root().join("unused"), runtime(), invalid).is_err()
    );
}

#[test]
fn only_document_truncates_and_unicode_character_guard_is_not_byte_count() {
    let scorer = fixture(&manifest()["pair"], RerankOptions::new(3, 4, 512).unwrap());
    let text = "x ".repeat(2000);
    assert!(!scorer.pair_fits("x", &text).unwrap());
    let result = scorer.score("x", &[&text]).unwrap();
    assert_eq!(result.scores, [535.]);
    assert_eq!(result.details.pair_tokens, [512]);
    assert_eq!(result.details.truncated_documents, 1);
    assert!(scorer.pair_fits("x", "y").unwrap());
    let tokens = scorer.tokenize_pairs("x", &[&text]).unwrap();
    assert_eq!(&tokens[0].ids[..3], &[8, 1, 9]);
    assert!(tokens[0].overflowing);
    // The frozen WordLevel fixture maps this one whitespace-free query to UNK.
    let chars = "é".repeat(65536);
    assert!(scorer.score(&chars, &["y"]).is_ok());
    assert!(
        scorer
            .score(&(chars + "é"), &["y"])
            .unwrap_err()
            .to_string()
            .contains("query is too long")
    );
    assert!(scorer.score(&"x ".repeat(509), &["y"]).is_err());
    assert!(scorer.score(&"x ".repeat(508), &["y"]).is_ok());
}

#[test]
fn positive_budgets_smaller_than_special_tokens_return_errors_without_panicking() {
    for budget in [1, 2, 3, 4] {
        let scorer = fixture(
            &manifest()["pair"],
            RerankOptions::new(1, 4, budget).unwrap(),
        );
        let result =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| scorer.score("x", &["y"])));
        assert!(result.is_ok(), "token budget{budget} panicked");
        assert!(
            result
                .unwrap()
                .unwrap_err()
                .to_string()
                .contains("query is too long")
        );
        assert!(!scorer.pair_fits("x", "y").unwrap());
        assert!(scorer.tokenize_pairs("x", &[]).unwrap().is_empty());
        if budget < 3 {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                scorer.tokenize_pairs("x", &["y"])
            }));
            assert!(result.is_ok(), "paired special budget{budget} panicked");
            assert!(result.unwrap().is_err());
        }
    }
}

#[test]
fn malformed_published_policy_and_nonfinite_or_wrong_count_outputs_fail() {
    let data = manifest();
    for (name, row) in data["invalid"].as_object().unwrap() {
        if row["kind"] != "pair" {
            continue;
        }
        let scorer = fixture(row, RerankOptions::default());
        assert!(scorer.score("x", &["y"]).is_err(), "{name}");
    }
}

#[test]
fn prepared_model_provenance_and_owned_bytes_survive_path_changes() {
    let data = manifest();
    let model = RerankerModel::from_json(&data["pair"]["definition"].to_string()).unwrap();
    let other =
        RerankerModel::from_json(&data["invalid"]["nan-output"]["definition"].to_string()).unwrap();
    let foreign = Arc::new(
        other
            .verify_prepared(
                &root().join(data["invalid"]["nan-output"]["prepared"].as_str().unwrap()),
            )
            .unwrap(),
    );
    assert!(
        OnnxReranker::new(
            model.clone(),
            Some(foreign),
            None,
            root().join("unused"),
            runtime(),
            RerankOptions::default()
        )
        .is_err()
    );
    let temp = tempfile::tempdir().unwrap();
    let original = root().join(data["pair"]["prepared"].as_str().unwrap());
    for entry in fs::read_dir(original).unwrap() {
        let entry = entry.unwrap();
        fs::copy(entry.path(), temp.path().join(entry.file_name())).unwrap();
    }
    let prepared = Arc::new(model.verify_prepared(temp.path()).unwrap());
    fs::remove_file(temp.path().join("model.onnx")).unwrap();
    fs::write(temp.path().join("tokenizer.json"), b"corrupt").unwrap();
    let scorer = OnnxReranker::new(
        model,
        Some(prepared),
        None,
        temp.path().join("absent"),
        runtime(),
        RerankOptions::default(),
    )
    .unwrap();
    assert_eq!(scorer.score("x", &["y"]).unwrap().scores, [29.]);
}

#[test]
fn concurrent_first_use_and_owned_results_do_not_cross_queries() {
    let scorer = Arc::new(fixture(
        &manifest()["pair"],
        RerankOptions::new(3, 4, 1024).unwrap(),
    ));
    let barrier = Arc::new(std::sync::Barrier::new(4));
    let workers: Vec<_> = (0..4)
        .map(|i| {
            let scorer = scorer.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                if i % 2 == 0 {
                    assert_eq!(
                        scorer.score("x", &["y", "x x x"]).unwrap().scores,
                        [29., 30.]
                    );
                } else {
                    assert_eq!(scorer.score("y", &["y"]).unwrap().scores, [30.]);
                }
            })
        })
        .collect();
    for worker in workers {
        worker.join().unwrap();
    }
    let mut first = scorer.score("x", &["y"]).unwrap();
    first.scores[0] = 0.;
    assert_eq!(scorer.score("x", &["y"]).unwrap().scores, [29.]);
}

#[test]
fn native_head_prepares_lazily_without_python_built_cache() {
    let data = manifest();
    let row = &data["head"];
    let model = RerankerModel::from_json(&row["definition"].to_string()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join("rust-head");
    let scorer = OnnxReranker::new(
        model,
        None,
        Some(root().join(row["source"].as_str().unwrap())),
        cache.clone(),
        runtime(),
        RerankOptions::default(),
    )
    .unwrap();
    assert!(scorer.score("x", &[]).unwrap().scores.is_empty());
    assert!(!cache.exists());
    scorer.prepare().unwrap();
    assert!(cache.join("model.onnx").exists());
    let score = scorer.score("x", &["y"]).unwrap().scores[0];
    assert!(
        (f64::from(score) - 0.9822524189949036).abs() < 4e-6,
        "{score}"
    );
}

fn original_for_host(os: &str, arch: &str) -> Value {
    use sha2::{Digest, Sha256};
    let (system, machine) = match (os, arch) {
        ("linux", "x86_64") => ("Linux", "x86_64"),
        ("linux", "aarch64") => ("Linux", "aarch64"),
        ("macos", "aarch64") => ("Darwin", "arm64"),
        _ => panic!("prepare a separate Ettin original for this OS/architecture"),
    };
    let (path, digest) = if (os, arch) == ("linux", "x86_64") {
        (
            root().join("linux-x86_64-original.json"),
            "ec1a7477107da440828fd0f46ab2c6d9be45a5d64c7c516306797aa2636e20ce",
        )
    } else {
        (
            repo().join("docs/validation/rust-migration-2026-10-19/m2-ettin/reference.json"),
            "ddbd13c1e29d8a4f689b58cb9041aa0fcea4745618f065423ddf7dbe4cf7824b",
        )
    };
    let bytes = fs::read(path).unwrap();
    assert_eq!(format!("{:x}", Sha256::digest(&bytes)), digest);
    let document: Value = serde_json::from_slice(&bytes).unwrap();
    let original = if (os, arch) == ("linux", "x86_64") {
        document
    } else {
        document["platforms"][format!("{system}/{machine}")].clone()
    };
    assert_eq!(original["platform"], system, "crossed Ettin original OS");
    assert_eq!(
        original["architecture"], machine,
        "crossed Ettin original architecture"
    );
    original
}

#[test]
fn original_selection_keeps_each_host_and_rejects_crossed_targets() {
    let mut previous: Option<Value> = None;
    for (os, arch, system, machine) in [
        ("linux", "x86_64", "Linux", "x86_64"),
        ("linux", "aarch64", "Linux", "aarch64"),
        ("macos", "aarch64", "Darwin", "arm64"),
    ] {
        let original = original_for_host(os, arch);
        assert_eq!(original["platform"], system);
        assert_eq!(original["architecture"], machine);
        assert_eq!(original["cases"].as_array().unwrap().len(), 23);
        assert_eq!(original["results"].as_array().unwrap().len(), 23);
        if let Some(expected) = &previous {
            for field in [
                "cases",
                "definition",
                "source_artifacts",
                "artifacts",
                "tolerances",
            ] {
                assert_eq!(original[field], expected[field], "{field}");
            }
        }
        previous = Some(original);
    }
    for (os, arch) in [
        ("linux", "arm64"),
        ("macos", "x86_64"),
        ("windows", "x86_64"),
        ("freebsd", "aarch64"),
    ] {
        assert!(std::panic::catch_unwind(|| original_for_host(os, arch)).is_err());
    }
}

#[test]
fn registered_ettin_matches_all23_frozen_platform_histories() {
    let oracle = original_for_host(std::env::consts::OS, std::env::consts::ARCH);
    let model = RerankerModel::from_json(&oracle["definition"].to_string()).unwrap();
    let source = PathBuf::from(
        std::env::var_os("KEN_ETTIN_SOURCE")
            .expect("prepare KEN_ETTIN_SOURCE for actual Ettin tests"),
    );
    let temp = tempfile::tempdir().unwrap();
    let prepared = Arc::new(
        model
            .prepare(Some(&source), &temp.path().join("native-real-ettin"))
            .unwrap(),
    );
    assert_eq!(oracle["cases"].as_array().unwrap().len(), 23);
    for (case, want) in oracle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(oracle["results"].as_array().unwrap())
    {
        assert_eq!(case["id"], want["id"]);
        let options: RerankOptions = serde_json::from_value(case["options"].clone()).unwrap();
        let scorer = OnnxReranker::new(
            model.clone(),
            Some(prepared.clone()),
            None,
            temp.path().join("unused"),
            runtime(),
            options,
        )
        .unwrap();
        for (call, expected) in case["calls"]
            .as_array()
            .unwrap()
            .iter()
            .zip(want["calls"].as_array().unwrap())
        {
            let query = call["query"].as_str().unwrap();
            let texts: Vec<_> = call["texts"]
                .as_array()
                .map(|a| a.iter().map(|x| x.as_str().unwrap()).collect())
                .unwrap_or_default();
            match call["op"].as_str().unwrap() {
                "tokens" => assert_eq!(
                    serde_json::to_value(scorer.tokenize_pairs(query, &texts).unwrap()).unwrap(),
                    *expected,
                    "{}",
                    case["id"]
                ),
                "pair_fits" => assert_eq!(
                    scorer
                        .pair_fits(query, call["text"].as_str().unwrap())
                        .unwrap(),
                    expected.as_bool().unwrap()
                ),
                "score" => {
                    let actual = scorer.score(query, &texts);
                    if !expected["error"].is_null() {
                        assert!(
                            actual
                                .unwrap_err()
                                .to_string()
                                .contains(expected["error"]["message"].as_str().unwrap()),
                            "{}",
                            case["id"]
                        );
                        continue;
                    }
                    let actual = actual.unwrap();
                    let scores = expected["scores"].as_array().unwrap();
                    assert_eq!(actual.scores.len(), scores.len());
                    for (got, want) in actual.scores.iter().zip(scores) {
                        let want = want.as_f64().unwrap();
                        assert!(got.is_finite());
                        assert!(
                            (f64::from(*got) - want).abs() <= 1e-5 + 1e-5 * want.abs(),
                            "{} wanted{want} got{got}",
                            case["id"]
                        );
                        if want == 0. {
                            assert_eq!(*got, 0.);
                        }
                    }
                    let actual = serde_json::to_value(actual.details).unwrap();
                    for field in ["truncated_documents", "pair_tokens", "pad_id"] {
                        assert_eq!(
                            actual[field], expected["details"][field],
                            "{} {field}",
                            case["id"]
                        );
                    }
                }
                _ => panic!("unknown history operation"),
            }
        }
        assert_eq!(
            scorer.is_prepared().unwrap(),
            want["session_loaded"].as_bool().unwrap(),
            "{}",
            case["id"]
        );
    }
}
