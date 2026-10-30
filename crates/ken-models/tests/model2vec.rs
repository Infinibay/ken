#[path = "support/fixture_json.rs"]
mod fixture_json;
use ken_models::{Model2VecEncoder, ModelAssets};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{path::PathBuf, sync::Arc};

fn encoder(dtype: &str) -> Model2VecEncoder {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(dtype);
    let registration = std::fs::read_to_string(root.join("registration.json")).unwrap();
    let value: Value = serde_json::from_str(&registration).unwrap();
    let snapshot = ModelAssets::from_json(&registration)
        .unwrap()
        .verify(&root.join(value["revision"].as_str().unwrap()))
        .unwrap();
    Model2VecEncoder::load(&snapshot).unwrap()
}

fn expected(dtype: &str, case: usize) -> Vec<f32> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(dtype)
        .join("reference.json");
    let value: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let vector = if case == 2 {
        &value["results"][case]["calls"][0]
    } else {
        &value["results"][case]["calls"][0]["vectors"][0]
    };
    vector
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap() as f32)
        .collect()
}

fn close(actual: &[f32], want: &[f32]) {
    assert_eq!(actual.len(), want.len());
    for (a, b) in actual.iter().zip(want) {
        assert!((a - b).abs() < 2e-6, "{actual:?} != {want:?}");
    }
}

#[test]
fn mean_and_norm_match_weight_dtype() {
    for dtype in ["float16", "float32"] {
        let model = encoder(dtype);
        assert_eq!(model.dim(), 3);
        close(&model.embed_query("a b").unwrap(), &expected(dtype, 0));
        assert!(model.embed_passages(&[]).unwrap().is_empty());
    }
}

#[test]
fn empty_row_promotes_its_batch() {
    let model = encoder("float16");
    let output = model.embed_passages(&["a b".into(), "".into()]).unwrap();
    close(&output[0], &expected("float16", 1));
    assert_eq!(output[1], [0.0; 3]);
    assert_ne!(output[0], model.embed_query("a b").unwrap());
}

#[test]
fn batch_boundary_1024_is_preserved() {
    let model = encoder("float16");
    let mut texts = vec!["a b".into(); 1025];
    texts[1023] = String::new();
    let output = model.embed_passages(&texts).unwrap();
    assert_eq!(output.len(), 1025);
    close(&output[0], &expected("float16", 1));
    close(&output[1024], &expected("float16", 0));
    assert_eq!(output[1023], [0.0; 3]);
}

#[test]
fn cache_matches_call_history_and_returns_independent_values() {
    let model = encoder("float16");
    let original = model.embed_query("a").unwrap();
    let mut copied = model.embed_query("a").unwrap();
    copied[0] = 999.0;
    let output = model.embed_passages(&["a".into(), "".into()]).unwrap();
    assert_eq!(output[0], original);
    let fresh = encoder("float16")
        .embed_passages(&["a".into(), "".into()])
        .unwrap();
    assert_ne!(fresh[0], original);
    // Python treats these C0 separators as whitespace, unlike Rust is_whitespace.
    for suffix in ["\u{1c}", "\u{1d}", "\u{1e}", "\u{1f}", "\u{85}", "\u{a0}"] {
        let model = encoder("float16");
        let text = format!("a{suffix}");
        let alone = model.embed_query(&text).unwrap();
        let mixed = model.embed_passages(&[text, "".into()]).unwrap();
        assert_ne!(alone, mixed[0], "separator {suffix:?} was cached");
    }
}

fn custom_encoder(
    rows: usize,
    dim: usize,
    dtype: &str,
    nonfinite: bool,
) -> Result<Model2VecEncoder, ken_models::ModelError> {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("4444444444444444444444444444444444444444");
    std::fs::create_dir(&root).unwrap();
    let mut data = Vec::new();
    for row in 0..rows {
        for column in 0..dim {
            let value = if nonfinite {
                f32::INFINITY
            } else {
                [0.1, 0.2, 0.3, 0.6, 0.8][row % 5] + (column % 3) as f32 * 0.07
            };
            data.extend(value.to_le_bytes());
        }
    }
    let mut header = serde_json::to_vec(
        &json!({"embeddings":{"dtype":dtype,"shape":[rows,dim],"data_offsets":[0,data.len()]}}),
    )
    .unwrap();
    while !header.len().is_multiple_of(8) {
        header.push(b' ');
    }
    let mut file = (header.len() as u64).to_le_bytes().to_vec();
    file.extend(header);
    file.extend(data);
    std::fs::write(root.join("model.safetensors"), &file).unwrap();
    let tokenizer = include_bytes!("fixtures/policy-tokenizer.json");
    std::fs::write(root.join("tokenizer.json"), tokenizer).unwrap();
    let registration = json!({"model_id":"test/static", "revision":root.file_name().unwrap().to_str().unwrap(),
        "artifacts":{"model.safetensors":{"bytes":file.len(),"sha256":format!("{:x}",Sha256::digest(&file))},
                     "tokenizer.json":{"bytes":tokenizer.len(),"sha256":format!("{:x}",Sha256::digest(tokenizer))}}});
    let snapshot = ModelAssets::from_json(&registration.to_string())
        .unwrap()
        .verify(&root)
        .unwrap();
    Model2VecEncoder::load(&snapshot)
}

#[test]
fn corrupt_shapes_and_nonfinite_weights_fail() {
    assert!(custom_encoder(4, 3, "F32", false).is_err());
    assert!(custom_encoder(5, 0, "F32", false).is_err());
    assert!(custom_encoder(5, 3, "I32", false).is_err());
    assert!(custom_encoder(5, 3, "F32", true).is_err());
}

#[test]
fn cache_entry_budget_evicts_least_recent_term() {
    let model = encoder("float16");
    model.embed_query("a").unwrap();
    model.embed_query("b").unwrap();
    model
        .embed_passages(&(0..8190).map(|i| format!("unknown{i}")).collect::<Vec<_>>())
        .unwrap();
    let a = model.embed_query("a").unwrap(); // refresh a, b is now oldest
    model.embed_query("newunknown").unwrap();
    let output = model
        .embed_passages(&["a".into(), "b".into(), "".into()])
        .unwrap();
    assert_eq!(output[0], a);
    let b_mixed = encoder("float16")
        .embed_passages(&["b".into(), "".into()])
        .unwrap();
    assert_eq!(output[1], b_mixed[0]);
}

#[test]
fn cache_is_safe_for_concurrent_queries() {
    let model = Arc::new(encoder("float16"));
    let want = model.embed_query("a").unwrap();
    let handles: Vec<_> = (0..8)
        .map(|_| {
            let model = Arc::clone(&model);
            let want = want.clone();
            std::thread::spawn(move || {
                for _ in 0..50 {
                    assert_eq!(model.embed_query("a").unwrap(), want);
                }
            })
        })
        .collect();
    for handle in handles {
        handle.join().unwrap();
    }
}

#[test]
fn cache_byte_budget_evicts_before_the_entry_limit() {
    let model = custom_encoder(5, 1024, "F32", false).unwrap();
    let alone = model.embed_query("a").unwrap();
    let fresh = custom_encoder(5, 1024, "F32", false)
        .unwrap()
        .embed_passages(&["a".into(), "".into()])
        .unwrap();
    assert_ne!(
        alone, fresh[0],
        "fixture must distinguish cache hit from re-encode"
    );
    model
        .embed_passages(&(0..2100).map(|i| format!("unknown{i}")).collect::<Vec<_>>())
        .unwrap();
    let result = model.embed_passages(&["a".into(), "".into()]).unwrap();
    assert_eq!(result[0], fresh[0]);
}

#[test]
fn real_registered_potion_matches_all_frozen_calls() {
    let snapshot = std::env::var_os("KEN_POTION_SNAPSHOT").expect("prepare the pinned Potion artifacts and set KEN_POTION_SNAPSHOT; model validation never skips missing weights");
    let registration = include_str!("../../../src/ken/embedder/data/potion-code-16M-v2.json");
    let verified = ModelAssets::from_json(registration)
        .unwrap()
        .verify(std::path::Path::new(&snapshot))
        .unwrap();
    let oracle: Value = serde_json::from_slice(&fixture_json::decode(include_bytes!(
        "fixtures/portable/potion-reference.json.gz"
    )))
    .unwrap();
    for (case, result) in oracle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(oracle["results"].as_array().unwrap())
    {
        let model = Model2VecEncoder::load(&verified).unwrap();
        for (call, want) in case["calls"]
            .as_array()
            .unwrap()
            .iter()
            .zip(result["calls"].as_array().unwrap())
        {
            match call["op"].as_str().unwrap() {
                "tokens" => {
                    let actual = model
                        .token_ids(
                            call["text"].as_str().unwrap(),
                            call["max_length"].as_u64().map(|x| x as usize),
                        )
                        .unwrap();
                    assert_eq!(
                        serde_json::to_value(actual).unwrap(),
                        *want,
                        "{}",
                        case["id"]
                    );
                }
                "count" => assert_eq!(
                    model
                        .token_ids(call["text"].as_str().unwrap(), None)
                        .unwrap()
                        .len(),
                    want.as_u64().unwrap() as usize
                ),
                "query" => check_real_vector(
                    &model.embed_query(call["text"].as_str().unwrap()).unwrap(),
                    want,
                    &case["id"],
                ),
                "passages" => {
                    let texts: Vec<String> = serde_json::from_value(call["texts"].clone()).unwrap();
                    let actual = model.embed_passages(&texts).unwrap();
                    assert_eq!(actual.len(), want["rows"].as_array().unwrap().len());
                    for (vector, row) in actual.iter().zip(want["rows"].as_array().unwrap()) {
                        check_real_vector(
                            vector,
                            &want["vectors"][row.as_u64().unwrap() as usize],
                            &case["id"],
                        );
                    }
                }
                _ => panic!("unrecognized fixed operation"),
            }
        }
    }
}

fn check_real_vector(actual: &[f32], expected: &Value, case: &Value) {
    let want: Vec<f64> = expected
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap())
        .collect();
    assert_eq!(actual.len(), want.len());
    let all_zero = want.iter().all(|v| *v == 0.0);
    let mut dot = 0.0;
    let mut a2 = 0.0;
    let mut b2 = 0.0;
    for (&a, &b) in actual.iter().zip(&want) {
        let a = f64::from(a);
        assert!(a.is_finite());
        assert!((a - b).abs() <= 2e-4 + 2e-3 * b.abs(), "{case}: {a} != {b}");
        if all_zero {
            assert_eq!(a, 0.0);
        }
        dot += a * b;
        a2 += a * a;
        b2 += b * b;
    }
    if !all_zero {
        assert!(dot / (a2 * b2).sqrt() >= 0.99999, "{case}: cosine mismatch");
    }
}
