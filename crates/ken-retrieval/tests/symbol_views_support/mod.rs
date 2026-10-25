#![allow(dead_code)]
use flate2::read::GzDecoder;
use ken_models::RerankOptions;
use ken_retrieval::description::OwnerDescription;
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use std::io::Read;

#[derive(Deserialize)]
pub struct Corpus {
    pub cases: Vec<Case>,
    pub frames: Vec<Frame>,
    pub fusion_grouping_extension: Value,
}
#[derive(Deserialize)]
pub struct Case {
    pub id: String,
    pub kind: String,
    pub input: Input,
    pub result: Option<Box<RawValue>>,
    pub error: Option<Value>,
    pub calls: Vec<Call>,
}
#[derive(Deserialize)]
pub struct Input {
    pub descriptions: Vec<OwnerDescription>,
    pub query: Option<PythonText>,
    #[serde(default)]
    pub original_scores: Vec<Value>,
    #[serde(default)]
    pub code_scores: Vec<Value>,
    #[serde(default)]
    pub accepted: Vec<bool>,
    pub details: Option<Value>,
    pub fail_pair: Option<usize>,
    #[serde(default)]
    pub fail_score: bool,
}
#[derive(Clone, Debug, Deserialize, serde::Serialize, PartialEq)]
pub struct Call {
    pub op: String,
    pub query: PythonText,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<PythonText>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub texts: Option<Vec<PythonText>>,
}
#[derive(Deserialize)]
pub struct Frame {
    pub input: FrameInput,
    pub result: Value,
    pub calls: Vec<Call>,
}
#[derive(Deserialize)]
pub struct FrameInput {
    pub id: String,
    pub query: PythonText,
    pub descriptions: Vec<OwnerDescription>,
    pub card_texts: Vec<PythonText>,
    pub options: RerankOptions,
}
pub fn corpus() -> Corpus {
    let mut raw = String::new();
    GzDecoder::new(&include_bytes!("../fixtures/symbol-views-reference.json.gz")[..])
        .read_to_string(&mut raw)
        .unwrap();
    serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw).unwrap()).unwrap()
}
pub fn number(value: &Value) -> f64 {
    value
        .as_f64()
        .unwrap_or_else(|| match value["$float"].as_str().unwrap() {
            "inf" => f64::INFINITY,
            "-inf" => f64::NEG_INFINITY,
            "nan" => f64::NAN,
            _ => panic!("invalid IEEE tag"),
        })
}
pub fn exact_scores(got: &[f64], want: &Value) {
    let want = want.as_array().unwrap();
    assert_eq!(got.len(), want.len());
    for (got, want) in got.iter().zip(want) {
        assert_eq!(got.to_bits(), number(want).to_bits());
    }
}
pub fn real_scores(got: &[f64], want: &Value) {
    let want = want.as_array().unwrap();
    assert_eq!(got.len(), want.len());
    for (got, want) in got.iter().zip(want) {
        let want = number(want);
        assert!(
            got.is_finite() && (*got - want).abs() <= 1e-5 + 1e-5 * want.abs(),
            "wanted{want} got{got}"
        );
    }
}
pub fn details(got: &Value, want: &Value) {
    assert_eq!(
        got.as_object().unwrap().keys().collect::<Vec<_>>(),
        want.as_object().unwrap().keys().collect::<Vec<_>>()
    );
    for (key, want) in want.as_object().unwrap() {
        if matches!(key.as_str(), "token_ms" | "inference_ms") {
            let v = got[key].as_f64().unwrap();
            assert!(v.is_finite() && v >= 0.);
            if want == 0. {
                assert_eq!(v, 0.);
            }
        } else {
            assert_eq!(got[key], *want, "{key}");
        }
    }
}
