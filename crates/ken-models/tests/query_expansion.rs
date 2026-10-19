use ken_models::{LocalQueryExpansion, ModelError, TranslationModel};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Barrier, OnceLock},
};

const REVISION: &str = "c96e2c5399ebfae4fc43d9669556b9afa74bb69d";
const QUESTION: &str = "¿Dónde está la función que elimina archivos?";
const FILES: [&str; 5] = [
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "source.spm",
    "target.spm",
];

fn model() -> TranslationModel {
    TranslationModel::from_json(include_str!(
        "../../../src/ken/embedder/data/es-en-ct2-int8.json"
    ))
    .unwrap()
}
fn oracle() -> Value {
    assert_eq!(
        std::env::consts::ARCH,
        "aarch64",
        "prepare an original oracle for this architecture"
    );
    let value: Value = serde_json::from_str(include_str!(
        "../../../docs/validation/rust-migration-2026-10-19/m2-translation/reference.json"
    ))
    .unwrap();
    value["oracles"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| {
            row["platform"]
                == if cfg!(target_os = "macos") {
                    "Darwin"
                } else {
                    "Linux"
                }
        })
        .unwrap()
        .clone()
}
struct Fixture {
    _root: tempfile::TempDir,
    cache: PathBuf,
}
fn fixture() -> &'static Fixture {
    static DATA: OnceLock<Fixture> = OnceLock::new();
    DATA.get_or_init(|| {
        let root = tempfile::tempdir().unwrap();
        let cache = root.path().join(REVISION);
        let source = PathBuf::from(
            std::env::var_os("KEN_TRANSLATION_SOURCE")
                .expect("prepare KEN_TRANSLATION_SOURCE for real native translation tests"),
        );
        model().prepare(Some(&source), &cache).unwrap();
        Fixture { _root: root, cache }
    })
}
fn copy_cache(root: &Path) -> PathBuf {
    let target = root.join(REVISION);
    fs::create_dir(&target).unwrap();
    for name in FILES {
        fs::copy(fixture().cache.join(name), target.join(name)).unwrap();
    }
    target
}
fn wanted(id: &str) -> String {
    oracle()["results"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["id"] == id)
        .unwrap()["calls"][0]["output"]
        .as_str()
        .unwrap()
        .into()
}

#[test]
fn english_and_repeated_single_spanish_word_need_no_assets_or_runtime() {
    let root = tempfile::tempdir().unwrap();
    let cache = root.path().join("absent").join(REVISION);
    let engine = LocalQueryExpansion::new(model(), None, cache.clone()).unwrap();
    for query in ["find the input parser", "", "busca busca", "English 👩🏽‍💻\0"] {
        assert_eq!(engine.expand(query).unwrap(), query);
        assert!(!engine.is_loaded());
        assert!(engine.runtime_identity().unwrap().is_none());
    }
    assert!(!cache.parent().unwrap().exists());
    assert!(engine.expand(QUESTION).is_err());
    assert!(!engine.is_loaded());
    assert_eq!(
        engine.expand("find the input parser").unwrap(),
        "find the input parser"
    );
    assert!(!cache.parent().unwrap().exists());
}

#[test]
fn all_original_histories_preserve_actual_tokens_hypotheses_text_errors_and_lazy_state() {
    let oracle = oracle();
    for (case, expected) in oracle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(oracle["results"].as_array().unwrap())
    {
        let temp = tempfile::tempdir().unwrap();
        let cache = if case["missing_assets"] == true {
            temp.path().join("missing").join(REVISION)
        } else if case["corrupt_artifact"].is_string() {
            let cache = copy_cache(temp.path());
            let path = cache.join("model.bin");
            let mut bytes = fs::read(&path).unwrap();
            bytes[0] ^= 1;
            fs::write(path, bytes).unwrap();
            cache
        } else {
            fixture().cache.clone()
        };
        let engine = LocalQueryExpansion::new(model(), None, cache).unwrap();
        assert!(!engine.is_loaded());
        for (query, call) in case["queries"]
            .as_array()
            .unwrap()
            .iter()
            .zip(expected["calls"].as_array().unwrap())
        {
            let query = query.as_str().unwrap();
            let result = engine.expand_detailed(query);
            if let Some(output) = call["output"].as_str() {
                let got = result.unwrap();
                if call["trace"].as_object().unwrap().is_empty() {
                    assert!(got.trace.is_none());
                } else {
                    let trace = got.trace.unwrap();
                    let original = &call["trace"];
                    assert_eq!(trace.prepared, original["prepared"].as_str().unwrap());
                    assert_eq!(
                        serde_json::to_value(trace.tokens.ids).unwrap(),
                        original["source_ids"]
                    );
                    assert_eq!(
                        serde_json::to_value(trace.tokens.pieces_with_eos).unwrap(),
                        original["source_pieces_with_eos"]
                    );
                    assert_eq!(
                        serde_json::to_value(trace.hypotheses).unwrap(),
                        original["hypotheses"]
                    );
                    assert_eq!(trace.decoded, original["decoded"].as_str().unwrap());
                }
                assert_eq!(got.text, output, "{}", case["id"]);
            } else {
                let error = result.unwrap_err();
                if call["error"]["type"] == "RuntimeError" {
                    let ModelError::Inference(message) = error else {
                        panic!("{}: {error}", case["id"])
                    };
                    assert_eq!(
                        message,
                        call["error"]["message"].as_str().unwrap(),
                        "{}",
                        case["id"]
                    );
                } else {
                    assert!(
                        matches!(error, ModelError::Artifact(_) | ModelError::Io { .. }),
                        "{}: {error}",
                        case["id"]
                    );
                }
            }
            assert_eq!(
                engine.is_loaded(),
                call["runtime_loaded"].as_bool().unwrap(),
                "{}",
                case["id"]
            );
        }
        if engine.is_loaded() {
            let identity =
                serde_json::to_value(engine.runtime_identity().unwrap().unwrap()).unwrap();
            assert_eq!(identity["observed_replicas"], 1);
            assert_eq!(identity["intra_threads"], 2);
            assert_eq!(identity["inter_threads"], 1);
            assert_eq!(identity["configured_device"], "cpu");
            assert_eq!(identity["configured_compute_type"], "int8");
            assert_eq!(identity["beam_size"], 1);
            assert_eq!(identity["max_input_length"], 1024);
            assert_eq!(identity["max_decoding_length"], 256);
            assert_eq!(identity["ctranslate2_source"], "4.8.2");
            assert_eq!(identity["sentencepiece_source"], "0.2.1");
            assert_eq!(
                identity["float_backend"],
                if cfg!(target_os = "macos") {
                    "Accelerate"
                } else {
                    "OpenBLAS0.3.26"
                }
            );
        }
    }
}

#[test]
fn failed_loading_is_retryable_and_english_remains_lazy_after_failure() {
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join(REVISION);
    fs::create_dir(&cache).unwrap();
    let engine = LocalQueryExpansion::new(model(), None, cache.clone()).unwrap();
    assert!(engine.expand(QUESTION).is_err());
    assert!(!engine.is_loaded());
    assert_eq!(
        engine.expand("find the input parser").unwrap(),
        "find the input parser"
    );
    for name in FILES {
        fs::copy(fixture().cache.join(name), cache.join(name)).unwrap();
    }
    assert_eq!(engine.expand(QUESTION).unwrap(), wanted("spanish"));
    assert!(engine.is_loaded());
}

#[test]
fn long_unmatched_identifier_attempt_reaches_normal_error_and_english_recovery() {
    let temp = tempfile::tempdir().unwrap();
    let cache = temp.path().join(REVISION);
    let engine = LocalQueryExpansion::new(model(), None, cache).unwrap();
    let query = format!("¿ {}é", "_".repeat(5_000));
    let attempt = engine.expand_attempt(&query);
    assert!(matches!(attempt.result, Err(ModelError::Artifact(_))));
    assert!(attempt.input.is_none());
    assert!(!engine.is_loaded());
    assert_eq!(engine.expand("find the parser").unwrap(), "find the parser");
}

#[test]
fn loaded_native_data_and_returned_traces_are_owned_after_cache_replacement() {
    let temp = tempfile::tempdir().unwrap();
    let cache = copy_cache(temp.path());
    let engine = LocalQueryExpansion::new(model(), None, cache.clone()).unwrap();
    let mut first = engine.expand_detailed(QUESTION).unwrap();
    let token_ids = first.trace.as_ref().unwrap().tokens.ids.clone();
    first.trace.as_mut().unwrap().tokens.ids.fill(999);
    fs::remove_dir_all(&cache).unwrap();
    fs::create_dir(&cache).unwrap();
    fs::write(cache.join("model.bin"), b"unverified replacement").unwrap();
    let second = engine.expand_detailed(QUESTION).unwrap();
    assert_eq!(second.text, wanted("spanish"));
    assert_eq!(second.trace.unwrap().tokens.ids, token_ids);
    assert_eq!(engine.expand("English").unwrap(), "English");
}

#[test]
fn simultaneous_first_calls_use_one_replica_without_crossing_queries_or_results() {
    let engine =
        Arc::new(LocalQueryExpansion::new(model(), None, fixture().cache.clone()).unwrap());
    let barrier = Arc::new(Barrier::new(8));
    let queries = [
        (QUESTION, wanted("spanish")),
        (
            "¿Dónde se invoca `Client.send` con project_name?",
            wanted("protected-code"),
        ),
    ];
    let workers: Vec<_> = (0..8)
        .map(|index| {
            let (engine, barrier) = (engine.clone(), barrier.clone());
            let (query, expected) = queries[index % 2].clone();
            std::thread::spawn(move || {
                barrier.wait();
                assert_eq!(engine.expand(query).unwrap(), expected);
            })
        })
        .collect();
    for worker in workers {
        worker.join().unwrap();
    }
    assert_eq!(
        engine
            .runtime_identity()
            .unwrap()
            .unwrap()
            .observed_replicas,
        1
    );
}

#[test]
fn failed_inference_attempt_owns_the_actual_input_before_error_and_keeps_lazy_recovery() {
    let engine = LocalQueryExpansion::new(model(), None, fixture().cache.clone()).unwrap();
    let query = "¿ ".to_owned() + &"hola ".repeat(511);
    let attempt = engine.expand_attempt(&query);
    let input = attempt.input.unwrap();
    assert_eq!(input.prepared, query);
    let original = oracle();
    let row = original["results"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["id"] == "source-boundary513")
        .unwrap();
    assert_eq!(
        serde_json::to_value(&input.tokens.ids).unwrap(),
        row["calls"][0]["trace"]["source_ids"]
    );
    assert_eq!(
        serde_json::to_value(&input.tokens.pieces_with_eos).unwrap(),
        row["calls"][0]["trace"]["source_pieces_with_eos"]
    );
    let ModelError::Inference(message) = attempt.result.unwrap_err() else {
        panic!("actual inference error required")
    };
    assert_eq!(
        message,
        "No position encodings are defined for positions >= 512, but got position 512"
    );
    assert!(engine.is_loaded());
    let english = engine.expand_attempt("find the input parser");
    assert!(english.input.is_none());
    assert_eq!(english.result.unwrap().text, "find the input parser");
    assert_eq!(input.tokens.pieces_with_eos.len(), 513);
    let missing = tempfile::tempdir().unwrap();
    let broken = LocalQueryExpansion::new(model(), None, missing.path().join(REVISION)).unwrap();
    let attempt = broken.expand_attempt(QUESTION);
    assert!(attempt.result.is_err() && attempt.input.is_none() && !broken.is_loaded());
}
