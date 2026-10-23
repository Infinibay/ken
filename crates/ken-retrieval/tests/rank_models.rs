pub mod feature_support;
use ken_models::{EncoderSpec, StaticTableEncoder};
use ken_retrieval::{
    Result, RetrievalError, matrix::Matrix, owner_ranking::EvidenceReranker,
    rank_models::ProductionRankModels, ranking_trace::RankingTrace, stemming::EnglishStems,
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{
    cell::RefCell,
    fs,
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};
fn resources() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/ranking")
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Box<RawValue>,
    result: Value,
    encoder_calls: Vec<feature_support::Call>,
    stemmer_calls: Vec<Vec<PythonText>>,
}
fn cases() -> Vec<Case> {
    #[derive(Deserialize)]
    struct Root {
        cases: Vec<Case>,
    }
    #[cfg(target_os = "macos")]
    let raw = include_str!("fixtures/numeric-reference-production.json");
    #[cfg(target_os = "linux")]
    let raw = include_str!("fixtures/numeric-reference-production-linux.json");
    let raw = ken_retrieval::json_transport::python_strings(raw).unwrap();
    serde_json::from_str::<Root>(&raw).unwrap().cases
}
#[test]
fn registered_forests_reproduce_original_identity_and_predictions() {
    let models = ProductionRankModels::open(resources()).unwrap();
    for c in cases()
        .into_iter()
        .filter(|c| c.kind != "production_compose")
    {
        let input: Value = serde_json::from_str(c.input.get()).unwrap();
        let role = input["role"].as_str().unwrap();
        let model = if role == "native" {
            models.native().unwrap()
        } else {
            models.piece().unwrap()
        };
        if c.kind == "production_identity" {
            assert_eq!(model.fingerprint().unwrap(), c.result["fingerprint"]);
            assert_eq!(
                serde_json::to_value(model.features()).unwrap(),
                c.result["features"]
            );
            assert_eq!(model.tree_count() as u64, c.result["trees"]);
            let name = if role == "native" {
                "native-forest-mean-v140.json.gz"
            } else {
                "piece-forest-mean-v140.json.gz"
            };
            let bytes = fs::read(resources().join(name)).unwrap();
            assert_eq!(
                format!("{:x}", Sha256::digest(&bytes)),
                c.result["compressed_sha256"]
            );
            assert_eq!(bytes.len() as u64, c.result["compressed_bytes"]);
        } else {
            let rows = input["rows"].as_u64().unwrap() as usize;
            let width = model.features().len();
            let values = (0..rows)
                .flat_map(|r| {
                    (0..width).map(move |col| ((r * 17 + col * 7) % 257) as f64 / 16. - 8.)
                })
                .collect();
            let got = model
                .predict(&Matrix::new(rows, width, values).unwrap())
                .unwrap();
            let want: Vec<f64> = serde_json::from_value(c.result["scores"].clone()).unwrap();
            assert_eq!(got, want, "{}", c.id);
        }
        assert!(c.encoder_calls.is_empty() && c.stemmer_calls.is_empty());
    }
    let a = models.native().unwrap();
    let started = std::time::Instant::now();
    for _ in 0..20 {
        assert_eq!(
            a.fingerprint().unwrap(),
            "6b563fed14ed276e1b310beba84006078ef65ab5d7d3cb5622d759f6a671e3a0"
        );
    }
    eprintln!(
        "production native warm fingerprint20_ns={}",
        started.elapsed().as_nanos()
    );
    assert!(Arc::ptr_eq(&a, &models.native().unwrap()));
    let a = models.piece().unwrap();
    assert!(Arc::ptr_eq(&a, &models.piece().unwrap()));
}
fn copied() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for f in fs::read_dir(resources()).unwrap() {
        let f = f.unwrap();
        if f.file_type().unwrap().is_file() {
            fs::copy(f.path(), dir.path().join(f.file_name())).unwrap();
        }
    }
    dir
}
#[test]
fn artifact_identity_and_lazy_missing_resources_are_enforced() {
    let dir = copied();
    fs::remove_file(dir.path().join("piece-forest-mean-v140.json.gz")).unwrap();
    let models = ProductionRankModels::open(dir.path()).unwrap();
    assert!(models.native().is_ok());
    assert!(models.piece().is_err());
    for mode in ["corrupt", "truncate", "decoded-model", "registry"] {
        let dir = copied();
        let path = dir.path().join("native-forest-mean-v140.json.gz");
        let mut bytes = fs::read(&path).unwrap();
        match mode {
            "corrupt" => {
                let n = bytes.len() / 2;
                bytes[n] ^= 1;
            }
            "truncate" => {
                bytes.truncate(bytes.len() / 2);
            }
            "decoded-model" => {
                bytes = b"{\"schema\":2,\"features\":[\"wrong\"],\"trees\":[0]}".to_vec();
            }
            _ => {
                fs::write(dir.path().join("manifest.json"), "{\"schema\":2}").unwrap();
            }
        }
        if mode != "registry" {
            fs::write(path, bytes).unwrap();
            let models = ProductionRankModels::open(dir.path()).unwrap();
            assert!(models.native().is_err(), "{mode}");
        } else {
            assert!(ProductionRankModels::open(dir.path()).is_err());
        }
    }
}
struct StaticWords {
    table: StaticTableEncoder,
    spec: EncoderSpec,
    calls: RefCell<Vec<feature_support::Call>>,
}
impl WordEncoder for StaticWords {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        self.calls.borrow_mut().push(feature_support::Call {
            op: "query".into(),
            text: Some(text.clone()),
            texts: None,
        });
        Ok(self.table.embed_query(
            &text
                .to_utf8()
                .ok_or_else(|| RetrievalError::Invalid("non-scalar static query".into()))?,
        )?)
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        self.calls.borrow_mut().push(feature_support::Call {
            op: "passages".into(),
            text: None,
            texts: Some(texts.to_vec()),
        });
        let texts: Vec<_> = texts.iter().map(|s| s.to_utf8().unwrap()).collect();
        Ok(self
            .table
            .embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?)
    }
}
#[test]
fn production_owner_ranking_composes_with_the_accepted_static_encoder() {
    #[derive(Deserialize)]
    struct Paths {
        cases: Vec<Case>,
    }
    #[cfg(target_os = "macos")]
    let raw = include_str!("fixtures/numeric-reference-production-paths.json");
    #[cfg(target_os = "linux")]
    let raw = include_str!("fixtures/numeric-reference-production-paths-linux.json");
    let paths: Paths =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(raw).unwrap()).unwrap();
    let models = ProductionRankModels::open(resources()).unwrap();
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../src/ken/embedder/data/ken__static-qwen3-r512-v2.npz");
    let bytes = fs::read(path).unwrap();
    let sha = format!("{:x}", Sha256::digest(&bytes));
    let spec: EncoderSpec = serde_json::from_value(
        json!({"model_id":"ken/static-qwen3-r512-v2","revision":sha,"backend":"static"}),
    )
    .unwrap();
    let encoder = Rc::new(StaticWords {
        table: StaticTableEncoder::from_npz(&bytes).unwrap(),
        spec,
        calls: RefCell::new(vec![]),
    });
    for c in cases()
        .into_iter()
        .filter(|c| c.kind == "production_compose")
    {
        let input: feature_support::Input = serde_json::from_str(c.input.get()).unwrap();
        let request = feature_support::request(&input);
        let candidates: Vec<_> = input.candidates.iter().map(|c| c.materialize()).collect();
        let descriptions = feature_support::descriptions(&input);
        let stems = Arc::new(feature_support::Stems::new(&feature_support::Input {
            stemmer: Some("english".into()),
            ..input.clone()
        }));
        let runtime = EvidenceReranker::new(
            models.native().unwrap(),
            encoder.clone(),
            stems.clone(),
            None,
        )
        .unwrap();
        let mut trace = RankingTrace::new(Some("production-static-composition".into())).unwrap();
        let matches = runtime
            .rank(
                &request,
                &candidates,
                &descriptions,
                input.expanded.as_ref(),
                3,
                Some(&mut trace),
            )
            .unwrap();
        assert_eq!(
            serde_json::to_value(&matches).unwrap(),
            c.result["matches"],
            "{}",
            c.id
        );
        let got: Value = serde_json::from_str(&trace.to_json(true).unwrap()).unwrap();
        compare(&got, &c.result["trace"], "trace");
        let expected = paths
            .cases
            .iter()
            .find(|p| p.id == format!("{}-paths", c.id))
            .unwrap();
        assert_eq!(
            path_digest(&got, &models.native().unwrap()),
            expected.result["paths_sha256"],
            "every actual leaf and threshold decision {}",
            c.id
        );
        assert_eq!(expected.encoder_calls, c.encoder_calls);
        assert_eq!(expected.stemmer_calls, c.stemmer_calls);
        assert_eq!(sha, c.result["static_sha256"]);
        assert_eq!(
            serde_json::to_value(encoder.spec()).unwrap(),
            c.result["word_spec"]
        );
        assert_eq!(encoder.calls.take(), c.encoder_calls);
        assert_eq!(*stems.calls.lock().unwrap(), c.stemmer_calls);
    }
    // The actual stemmer, not a test implementation, owns the lexical algorithm/cache.
    assert!(EnglishStems::shared().cached_words() > 0);
}
fn compare(a: &Value, b: &Value, path: &str) {
    match (a, b) {
        (Value::Number(a), Value::Number(b)) if path.contains("feature_values") => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            assert!(
                (a - b).abs() <= 1e-6 + 1e-6 * b.abs(),
                "{path}: {a:?} vs {b:?}"
            );
        }
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len(), "{path}");
            for (i, (a, b)) in a.iter().zip(b).enumerate() {
                compare(a, b, &format!("{path}/{i}"));
            }
        }
        (Value::Object(a), Value::Object(b)) => {
            assert_eq!(
                a.keys().collect::<Vec<_>>(),
                b.keys().collect::<Vec<_>>(),
                "{path}"
            );
            for (k, a) in a {
                compare(a, &b[k], &format!("{path}/{k}"));
            }
        }
        _ => assert_eq!(a, b, "{path}"),
    }
}

fn path_digest(trace: &Value, model: &ken_retrieval::numeric_ranker::NumericRanker) -> String {
    type LeafRoute = (String, Vec<(usize, String)>);
    let paths: Vec<Vec<LeafRoute>> = trace["owners"]
        .as_array()
        .unwrap()
        .iter()
        .map(|owner| {
            let row: Vec<f64> = serde_json::from_value(owner["feature_values"].clone()).unwrap();
            model
                .explain_pair(&row, &row)
                .unwrap()
                .trees
                .into_iter()
                .map(|tree| {
                    (
                        format!("{:016x}", tree.left_leaf.to_bits()),
                        tree.left_path
                            .into_iter()
                            .map(|step| (step.feature_index, step.branch))
                            .collect(),
                    )
                })
                .collect()
        })
        .collect();
    format!("{:x}", Sha256::digest(serde_json::to_vec(&paths).unwrap()))
}
