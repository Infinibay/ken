pub mod feature_support;
use feature_support as support;
use ken_models::{EncoderSpec, StaticTableEncoder};
use ken_retrieval::{
    EntityKey, Result,
    description::OwnerDescription,
    feature_matrix::FeatureMatrix,
    numeric_ranker::NumericRanker,
    piece_candidates::PieceCandidate,
    piece_features::{piece_feature_names, piece_features},
    piece_ranking::PieceReranker,
    query::{CodeMatch, SearchRequest},
    rank_models::ProductionRankModels,
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{cell::RefCell, path::Path, rc::Rc, sync::Arc};

#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Box<RawValue>,
    result: Option<Value>,
    error: Option<Value>,
    encoder_calls: Vec<support::Call>,
    stemmer_calls: Vec<Vec<PythonText>>,
}
#[derive(Deserialize)]
struct Input {
    request: SearchRequest,
    pieces: Vec<RawPiece>,
    expanded: Option<PythonText>,
    model: Option<Box<RawValue>>,
    #[serde(default)]
    production: bool,
}
#[derive(Deserialize)]
struct RawPiece {
    kind: String,
    path: String,
    entity: Option<EntityKey>,
    members: Vec<OwnerDescription>,
    matches: Vec<CodeMatch>,
}
impl RawPiece {
    fn materialize(self) -> Result<PieceCandidate> {
        PieceCandidate::new(
            self.kind,
            self.path,
            self.entity,
            self.members.into_iter().map(Arc::new).collect(),
            self.matches,
        )
    }
}
enum Words {
    Synthetic(support::Encoder),
    Static {
        table: Box<StaticTableEncoder>,
        spec: EncoderSpec,
        calls: RefCell<Vec<support::Call>>,
    },
}
impl Words {
    fn production() -> Self {
        let bytes = std::fs::read(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../src/ken/embedder/data/ken__static-qwen3-r512-v2.npz"),
        )
        .unwrap();
        let spec = serde_json::from_value(json!({"model_id":"ken/static-qwen3-r512-v2",
            "revision":format!("{:x}",Sha256::digest(&bytes)),"backend":"static"}))
        .unwrap();
        Self::Static {
            table: Box::new(StaticTableEncoder::from_npz(&bytes).unwrap()),
            spec,
            calls: RefCell::default(),
        }
    }
    fn take_calls(&self) -> Vec<support::Call> {
        match self {
            Self::Synthetic(encoder) => encoder.calls.take(),
            Self::Static { calls, .. } => calls.take(),
        }
    }
}
impl WordEncoder for Words {
    fn spec(&self) -> &EncoderSpec {
        match self {
            Self::Synthetic(e) => e.spec(),
            Self::Static { spec, .. } => spec,
        }
    }
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        match self {
            Self::Synthetic(e) => e.embed_query(text),
            Self::Static { table, calls, .. } => {
                calls.borrow_mut().push(support::Call {
                    op: "query".into(),
                    text: Some(text.clone()),
                    texts: None,
                });
                Ok(table.embed_query(&text.to_utf8().unwrap())?)
            }
        }
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        match self {
            Self::Synthetic(e) => e.embed_passages(texts),
            Self::Static { table, calls, .. } => {
                calls.borrow_mut().push(support::Call {
                    op: "passages".into(),
                    text: None,
                    texts: Some(texts.to_vec()),
                });
                let texts: Vec<_> = texts.iter().map(|s| s.to_utf8().unwrap()).collect();
                Ok(table.embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?)
            }
        }
    }
}
fn matrix(got: &FeatureMatrix, want: &Value, id: &str, production: bool) {
    assert_eq!(
        serde_json::to_value(&got.names).unwrap(),
        want["names"],
        "schema {id}"
    );
    let rows = want["values"].as_array().unwrap();
    assert_eq!(
        (got.values.rows(), got.values.columns()),
        (rows.len(), 262),
        "shape {id}"
    );
    for (row, expected) in rows.iter().enumerate() {
        for (column, value) in expected.as_array().unwrap().iter().enumerate() {
            let want = support::number(value);
            let actual = got.values.values()[row * 262 + column];
            let name = got.names[column].to_utf8().unwrap();
            if !want.is_finite() {
                assert!(
                    actual.to_bits() == want.to_bits() || actual.is_nan() && want.is_nan(),
                    "{id} {name}"
                );
            } else if want == 0. {
                assert_eq!(actual.to_bits(), want.to_bits(), "{id} {name}");
            } else if production && column >= 30 {
                // The approved static F32 composition bound applies only to coverage inputs.
                assert!(
                    actual.is_finite() && (actual - want).abs() <= 1e-6 + 1e-6 * want.abs(),
                    "{id} {name}: {actual:?} vs {want:?}"
                );
            } else {
                support::close(actual, want, &format!("{id}_{name}"));
            }
        }
    }
}
fn paths(model: &NumericRanker, features: &FeatureMatrix) -> String {
    let mut paths = Vec::new();
    for row in features.values.values().chunks(262) {
        let explanation = model.explain_pair(row, row).unwrap();
        paths.push(
            explanation
                .trees
                .iter()
                .map(|t| {
                    let leaf = format!("{:016x}", t.left_leaf.to_bits());
                    json!([
                        leaf,
                        t.left_path
                            .iter()
                            .map(|s| json!([s.feature_index, s.branch]))
                            .collect::<Vec<_>>()
                    ])
                })
                .collect::<Vec<_>>(),
        );
    }
    format!("{:x}", Sha256::digest(serde_json::to_vec(&paths).unwrap()))
}

fn decompress(bytes: &[u8]) -> String {
    use std::io::Read;
    let mut raw = String::new();
    flate2::read::GzDecoder::new(bytes)
        .read_to_string(&mut raw)
        .unwrap();
    raw
}
fn ranking_fixture() -> String {
    #[cfg(target_os = "linux")]
    let raw = decompress(include_bytes!(
        "fixtures/piece-reference-ranking-linux.json.gz"
    ));
    #[cfg(target_os = "macos")]
    let raw = include_str!("fixtures/piece-reference-ranking.json").to_string();
    raw
}
#[test]
fn piece_feature_columns_calls_and_stable_order() {
    let raw = ranking_fixture();
    let edges = decompress(include_bytes!(
        "fixtures/piece-reference-ranking-edges-linux.json.gz"
    ));
    let empty = decompress(include_bytes!(
        "fixtures/piece-reference-ranking-empty-declaration-linux.json.gz"
    ));
    let cases: Vec<_> = [raw, edges, empty]
        .iter()
        .flat_map(|raw| {
            serde_json::from_str::<Corpus>(
                &ken_retrieval::json_transport::python_strings(raw).unwrap(),
            )
            .unwrap()
            .cases
        })
        .collect();
    assert_eq!(cases.len(), 98);
    let models =
        ProductionRankModels::open(Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/ranking"))
            .unwrap();
    let mut production = None;
    for case in cases {
        let input: Input = serde_json::from_str(case.input.get()).unwrap();
        let common: support::Input = serde_json::from_str(case.input.get()).unwrap();
        let encoder = if input.production {
            production
                .get_or_insert_with(|| Rc::new(Words::production()))
                .clone()
        } else {
            Rc::new(Words::Synthetic(support::Encoder::new(&common)))
        };
        let stems = Arc::new(support::Stems::new(&common));
        let pieces = input
            .pieces
            .into_iter()
            .map(RawPiece::materialize)
            .collect::<Result<Vec<_>>>()
            .unwrap();
        let result = if case.kind == "piece_features" {
            piece_features(
                &input.request,
                &pieces,
                encoder.as_ref(),
                stems.as_ref(),
                input.expanded.as_ref(),
            )
            .map(|features| {
                matrix(
                    &features,
                    case.result.as_ref().unwrap(),
                    &case.id,
                    input.production,
                );
            })
        } else {
            let model = if input.production {
                models.piece().unwrap()
            } else {
                Arc::new(NumericRanker::from_json(input.model.as_ref().unwrap().get()).unwrap())
            };
            let outcome = PieceReranker::new(model.clone(), encoder.clone(), stems.clone())
                .and_then(|ranker| ranker.rank(&input.request, &pieces, input.expanded.as_ref()));
            let calls = encoder.take_calls();
            let stem_calls = std::mem::take(&mut *stems.calls.lock().unwrap());
            assert_eq!(calls, case.encoder_calls, "rank encoder {}", case.id);
            assert_eq!(stem_calls, case.stemmer_calls, "rank stems {}", case.id);
            outcome.map(|ranked| {
                let want = case.result.as_ref().unwrap();
                assert_eq!(
                    ranked.iter().map(|m| m.proposal_index).collect::<Vec<_>>(),
                    serde_json::from_value::<Vec<usize>>(want["order"].clone()).unwrap(),
                    "order {}",
                    case.id
                );
                for (matched, score) in ranked.iter().zip(want["scores"].as_array().unwrap()) {
                    assert_eq!(
                        matched.score.to_bits(),
                        support::number(score).to_bits(),
                        "score {}",
                        case.id
                    );
                    assert_eq!(
                        serde_json::to_value(&matched.piece).unwrap(),
                        serde_json::to_value(&pieces[matched.proposal_index]).unwrap()
                    );
                }
                if !want["features"].is_null() {
                    let features = piece_features(
                        &input.request,
                        &pieces,
                        encoder.as_ref(),
                        stems.as_ref(),
                        input.expanded.as_ref(),
                    )
                    .unwrap();
                    matrix(&features, &want["features"], &case.id, input.production);
                    assert_eq!(
                        encoder.take_calls(),
                        case.encoder_calls,
                        "feature encoder {}",
                        case.id
                    );
                    assert_eq!(
                        std::mem::take(&mut *stems.calls.lock().unwrap()),
                        case.stemmer_calls,
                        "feature stems {}",
                        case.id
                    );
                    if let Some(want) = want.get("paths_sha256") {
                        assert_eq!(
                            paths(&model, &features),
                            want.as_str().unwrap(),
                            "paths {}",
                            case.id
                        );
                    }
                }
            })
        };
        match case.error {
            Some(error) => assert_eq!(
                result.unwrap_err().to_string(),
                error["message"],
                "{}",
                case.id
            ),
            None => result.unwrap(),
        }
        if case.kind == "piece_features" {
            assert_eq!(
                encoder.take_calls(),
                case.encoder_calls,
                "encoder {}",
                case.id
            );
            assert_eq!(
                *stems.calls.lock().unwrap(),
                case.stemmer_calls,
                "stems {}",
                case.id
            );
        }
    }
    assert_eq!(piece_feature_names().len(), 262);
}

#[test]
fn hidden_dotfiles_do_not_become_data_files_without_an_extension() {
    fn rebase(value: &mut Value, path: &str) {
        match value {
            Value::Object(fields) => {
                for (key, value) in fields {
                    if key == "path" {
                        *value = json!(path);
                    } else {
                        rebase(value, path);
                    }
                }
            }
            Value::Array(values) => {
                for value in values {
                    rebase(value, path);
                }
            }
            _ => (),
        }
    }
    let corpus: Corpus = serde_json::from_str(&ranking_fixture()).unwrap();
    let case = corpus
        .cases
        .into_iter()
        .find(|c| c.id == "file-features-auto")
        .unwrap();
    for (path, want) in [
        (".json", 0.),
        ("dir/.toml", 0.),
        ("dir/config.json", 1.),
        ("dir/.config.toml", 1.),
    ] {
        let mut raw: Value = serde_json::from_str(case.input.get()).unwrap();
        rebase(&mut raw["pieces"][0], path);
        let common: support::Input = serde_json::from_value(raw.clone()).unwrap();
        let input: Input = serde_json::from_value(raw).unwrap();
        let piece = input
            .pieces
            .into_iter()
            .next()
            .unwrap()
            .materialize()
            .unwrap();
        let encoder = support::Encoder::new(&common);
        let stems = support::Stems::new(&common);
        let features = piece_features(&input.request, &[piece], &encoder, &stems, None).unwrap();
        let column = features
            .names
            .iter()
            .position(|n| n.to_utf8().as_deref() == Some("data_file"))
            .unwrap();
        assert_eq!(features.values.values()[column], want, "{path}");
    }
}
