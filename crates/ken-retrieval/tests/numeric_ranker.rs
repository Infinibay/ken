use ken_retrieval::{matrix::Matrix, numeric_ranker::NumericRanker};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Input,
    result: Option<Box<RawValue>>,
    error: Option<Failure>,
}
#[derive(Deserialize)]
struct Failure {
    r#type: String,
    message: String,
}
#[derive(Deserialize)]
struct Input {
    model: Box<RawValue>,
    rows: Option<usize>,
    columns: Option<usize>,
    values: Option<Vec<Value>>,
    left: Option<Vec<Value>>,
    right: Option<Vec<Value>>,
}
fn number(v: &Value) -> f64 {
    v.as_f64()
        .unwrap_or_else(|| match v["$float"].as_str().unwrap() {
            "nan" => f64::NAN,
            "inf" => f64::INFINITY,
            "-inf" => f64::NEG_INFINITY,
            _ => panic!("unknown float"),
        })
}
#[test]
fn full_frozen_original_numeric_forest_observations() {
    observe_corpus(include_str!("fixtures/numeric-reference-forest.json"), 318);
}
#[test]
fn disjoint_original_forest_edges_preserve_coercions_and_errors() {
    observe_corpus(
        include_str!("fixtures/numeric-reference-forest-edges.json"),
        28,
    );
}
fn observe_corpus(raw: &str, count: usize) {
    let corpus: Corpus = serde_json::from_str(raw).unwrap();
    assert_eq!(corpus.cases.len(), count);
    for case in corpus.cases {
        let got = (|| {
            let model = NumericRanker::from_json(case.input.model.get())?;
            let before = model.to_json()?;
            let result = match case.kind.as_str() {
                "model" => {
                    let fingerprint = model.fingerprint()?;
                    let expected: Value =
                        serde_json::from_str(case.result.as_ref().unwrap().get()).unwrap();
                    assert_eq!(
                        before,
                        expected["canonical"].as_str().unwrap(),
                        "canonical {}",
                        case.id
                    );
                    assert_eq!(
                        fingerprint, expected["fingerprint"],
                        "fingerprint {}",
                        case.id
                    );
                    Value::Null
                }
                "dict" => {
                    #[derive(Deserialize)]
                    struct Names {
                        features: Vec<PythonText>,
                    }
                    let names: Names =
                        serde_json::from_str(case.result.as_ref().unwrap().get()).unwrap();
                    assert_eq!(model.features(), names.features, "names {}", case.id);
                    let restored = NumericRanker::from_json(&before)?;
                    assert_eq!(
                        restored.features(),
                        model.features(),
                        "lossless names {}",
                        case.id
                    );
                    Value::Null
                }
                "predict" => {
                    let matrix = Matrix::new(
                        case.input.rows.unwrap(),
                        case.input.columns.unwrap(),
                        case.input
                            .values
                            .as_ref()
                            .unwrap()
                            .iter()
                            .map(number)
                            .collect(),
                    )
                    .unwrap();
                    let scores = model.predict(&matrix)?;
                    let expected: Value =
                        serde_json::from_str(case.result.as_ref().map_or("{}", |r| r.get()))
                            .unwrap();
                    if let Some(want) = expected["scores"].as_array() {
                        assert_eq!(scores.len(), want.len(), "rows {}", case.id);
                        for (a, b) in scores.iter().zip(want) {
                            let b = number(b);
                            assert!(
                                a.to_bits() == b.to_bits() || (a.is_nan() && b.is_nan()),
                                "prediction {}: {a:?} vs {b:?}",
                                case.id
                            );
                        }
                    }
                    Value::Null
                }
                "explain" => serde_json::to_value(
                    model.explain_pair(
                        &case
                            .input
                            .left
                            .as_ref()
                            .unwrap()
                            .iter()
                            .map(number)
                            .collect::<Vec<_>>(),
                        &case
                            .input
                            .right
                            .as_ref()
                            .unwrap()
                            .iter()
                            .map(number)
                            .collect::<Vec<_>>(),
                    )?,
                )
                .unwrap(),
                _ => panic!("unknown operation"),
            };
            assert_eq!(model.to_json()?, before, "immutable {}", case.id);
            Ok::<_, ken_retrieval::numeric_ranker::NumericError>(result)
        })();
        match (got, case.error) {
            (Err(got), Some(expected)) => {
                assert_eq!(got.kind(), expected.r#type, "type {}", case.id);
                assert_eq!(got.to_string(), expected.message, "message {}", case.id);
            }
            (Ok(value), None) => {
                if case.kind == "explain" {
                    assert_eq!(
                        value,
                        serde_json::from_str::<Value>(case.result.unwrap().get()).unwrap(),
                        "explanation {}",
                        case.id
                    );
                }
            }
            (got, expected) => panic!(
                "{}: {got:?}, expected error {:?}",
                case.id,
                expected.map(|e| e.message)
            ),
        }
    }
}
#[test]
fn rectangular_values_are_checked_and_owned() {
    assert!(Matrix::<f64>::new(usize::MAX, 2, vec![]).is_err());
    assert!(Matrix::<f64>::new(2, 3, vec![0.; 5]).is_err());
    let empty = Matrix::<f64>::new(0, 3, vec![]).unwrap();
    assert_eq!((empty.rows(), empty.columns()), (0, 3));
    let m = Matrix::new(1, 2, vec![1., 2.]).unwrap();
    assert_eq!(m.values(), &[1., 2.]);
}
#[test]
fn numeric_json_reads_the_original_f64_bits() {
    let literal = "-1.9990128200625301";
    let value: Value = serde_json::from_str(literal).unwrap();
    assert_eq!(
        value.as_f64().unwrap().to_bits(),
        literal.parse::<f64>().unwrap().to_bits()
    );
}

#[test]
fn python_shortest_decimal_ties_neighbors_and_full_exponent_range() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/numeric-review-regressions.json")).unwrap();
    assert!(corpus["values"].as_u64().unwrap() >= 32_768);
    for entry in corpus["models"].as_array().unwrap() {
        let model = NumericRanker::from_json(&entry["model"].to_string()).unwrap();
        assert_eq!(model.to_json().unwrap(), entry["canonical"]);
        assert_eq!(model.fingerprint().unwrap(), entry["fingerprint"]);
    }
}
