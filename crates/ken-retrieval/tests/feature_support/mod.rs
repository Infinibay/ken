use ken_models::EncoderSpec;
use ken_retrieval::{
    EntityKey, Passage, Result, RetrievalError,
    description::{OwnerDescription, describe_owner},
    feature_matrix::FeatureMatrix,
    query::{Candidate, SearchOptions, SearchRequest},
    stemming::{EnglishStems, WordStemmer},
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::{Value, value::RawValue};
use std::{cell::RefCell, collections::BTreeMap, sync::Mutex};
#[derive(Deserialize)]
pub struct Case {
    pub id: String,
    pub kind: String,
    pub input: Input,
    pub result: Option<Box<RawValue>>,
    pub error: Option<Value>,
    pub encoder_calls: Vec<Call>,
    pub stemmer_calls: Vec<Vec<PythonText>>,
}
#[derive(Clone, Deserialize)]
pub struct Input {
    pub request: Option<SearchOptions>,
    pub query: Option<PythonText>,
    #[serde(default)]
    pub candidates: Vec<RawCandidate>,
    #[serde(default)]
    pub owners: Vec<Owner>,
    pub expanded: Option<PythonText>,
    pub stemmer: Option<String>,
    #[serde(default)]
    pub documents: Vec<BTreeMap<String, Vec<String>>>,
    #[serde(default)]
    pub fields: Vec<String>,
    #[serde(default)]
    pub source_views: bool,
    #[serde(default = "default_dim")]
    pub dimensions: usize,
    #[serde(default)]
    pub vectors: BTreeMap<String, Vec<f32>>,
}
fn default_dim() -> usize {
    3
}
#[derive(Clone, Deserialize)]
pub struct RawCandidate {
    pub entity: EntityKey,
    pub passages: Vec<Passage>,
    #[serde(default)]
    pub signals: BTreeMap<String, Value>,
    #[serde(default)]
    pub owned_regions: Vec<ken_retrieval::Span>,
}
impl RawCandidate {
    pub fn materialize(&self) -> Candidate {
        Candidate {
            entity: self.entity.clone(),
            passages: self.passages.clone(),
            owned_regions: self.owned_regions.clone(),
            signals: self
                .signals
                .iter()
                .map(|(k, v)| (k.clone(), number(v)))
                .collect(),
        }
    }
}
#[derive(Clone, Deserialize)]
pub struct Owner {
    key: EntityKey,
    passages: Vec<Passage>,
    #[serde(default)]
    overrides: BTreeMap<String, Box<RawValue>>,
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Call {
    pub op: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<PythonText>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub texts: Option<Vec<PythonText>>,
}
pub struct Encoder {
    spec: EncoderSpec,
    dim: usize,
    vectors: BTreeMap<String, Vec<f32>>,
    pub calls: RefCell<Vec<Call>>,
}
impl Encoder {
    pub fn new(input: &Input) -> Self {
        Self{spec:EncoderSpec::from_json(r#"{"model_id":"test/words","revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","backend":"provided","batch_size":1}"#).unwrap(),dim:input.dimensions,vectors:input.vectors.clone(),calls:RefCell::default()}
    }
    fn vector(&self, text: &PythonText) -> Vec<f32> {
        if let Some(value) = text.to_utf8().and_then(|s| self.vectors.get(&s)) {
            return value.clone();
        }
        let mut values = vec![0.; self.dim];
        if !text.is_empty() {
            let index = text.codepoints().iter().map(|c| *c as u64).sum::<u64>() as usize % 6;
            values[index % self.dim] = if index < 3 { 1. } else { -1. };
        }
        values
    }
}
impl WordEncoder for Encoder {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        self.calls.borrow_mut().push(Call {
            op: "query".into(),
            text: Some(text.clone()),
            texts: None,
        });
        Ok(self.vector(text))
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        assert!(texts.len() <= 4096, "bounded vector blocks");
        self.calls.borrow_mut().push(Call {
            op: "passages".into(),
            text: None,
            texts: Some(texts.to_vec()),
        });
        Ok(texts.iter().map(|t| self.vector(t)).collect())
    }
}
pub struct Stems {
    english: bool,
    pub calls: Mutex<Vec<Vec<PythonText>>>,
}
impl Stems {
    pub fn new(input: &Input) -> Self {
        Self {
            english: input.stemmer.as_deref() == Some("english"),
            calls: Mutex::default(),
        }
    }
}
impl WordStemmer for Stems {
    fn stem(&self, w: &PythonText) -> Result<PythonText> {
        if self.english {
            EnglishStems::shared().stem(w)
        } else {
            Ok(w.clone())
        }
    }
    fn stem_words(&self, words: &[PythonText]) -> Result<Vec<PythonText>> {
        self.calls.lock().unwrap().push(words.to_vec());
        words.iter().map(|w| self.stem(w)).collect()
    }
}
pub fn cases() -> Vec<Case> {
    #[derive(Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    #[cfg(target_os = "macos")]
    let files = [
        include_str!("../fixtures/numeric-reference-features.json"),
        include_str!("../fixtures/numeric-reference-features-edges.json"),
        include_str!("../fixtures/numeric-reference-features-math-edges.json"),
    ];
    #[cfg(target_os = "linux")]
    let files = [
        include_str!("../fixtures/numeric-reference-features-linux.json"),
        include_str!("../fixtures/numeric-reference-features-edges-linux.json"),
        include_str!("../fixtures/numeric-reference-features-math-edges-linux.json"),
    ];
    let all: Vec<_> = files
        .iter()
        .flat_map(|raw| serde_json::from_str::<Corpus>(raw).unwrap().cases)
        .collect();
    assert_eq!(all.len(), 86);
    all
}
pub fn request(input: &Input) -> SearchRequest {
    input.request.clone().unwrap().try_into().unwrap()
}
pub fn descriptions(input: &Input) -> BTreeMap<EntityKey, OwnerDescription> {
    input
        .owners
        .iter()
        .map(|owner| {
            let mut d = describe_owner(&owner.passages).unwrap();
            for (k, v) in &owner.overrides {
                match k.as_str() {
                    "entity" => d.entity = serde_json::from_str(v.get()).unwrap(),
                    "source_hash" => d.source_hash = serde_json::from_str(v.get()).unwrap(),
                    "passages" => d.passages = serde_json::from_str(v.get()).unwrap(),
                    _ => panic!("unknown original description override"),
                }
            }
            (owner.key.clone(), d)
        })
        .collect()
}
pub fn number(value: &Value) -> f64 {
    value
        .as_f64()
        .unwrap_or_else(|| match value["$float"].as_str().unwrap() {
            "nan" => f64::NAN,
            "inf" => f64::INFINITY,
            "-inf" => f64::NEG_INFINITY,
            _ => panic!("unknown number"),
        })
}
pub fn close(got: f64, want: f64, name: &str) {
    let f32_field = matches!(name.rsplit('_').next(), Some("mean" | "min" | "p25"));
    let tolerance = if f32_field { 1e-6 } else { 1e-12 };
    assert!(
        got.is_finite()
            && want.is_finite()
            && (got - want).abs() <= tolerance + tolerance * want.abs(),
        "{name}: {got:?} vs {want:?}"
    );
}
pub fn matrix(got: &FeatureMatrix, raw: &RawValue) {
    #[derive(Deserialize)]
    struct Expected {
        names: Vec<PythonText>,
        values: Vec<Vec<f64>>,
    }
    let want: Expected = serde_json::from_str(raw.get()).unwrap();
    assert_eq!(got.names, want.names);
    assert_eq!(
        (got.values.rows(), got.values.columns()),
        (want.values.len(), want.names.len())
    );
    for (i, row) in want.values.iter().enumerate() {
        for (j, w) in row.iter().enumerate() {
            close(
                got.values.values()[i * got.values.columns() + j],
                *w,
                &want.names[j].to_utf8().unwrap(),
            );
        }
    }
}
pub fn check_calls(case: &Case, encoder: &Encoder, stems: &Stems) {
    assert_eq!(
        *encoder.calls.borrow(),
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
pub fn error(error: RetrievalError, expected: &Value, id: &str) {
    assert_eq!(expected["type"], "ValueError", "{id}");
    assert_eq!(
        error.to_string(),
        expected["message"].as_str().unwrap(),
        "{id}"
    );
}
