//! Explicit input-provided word vectors and observed calls; no reference outputs.
use ken_models::EncoderSpec;
use ken_retrieval::{
    EntityKey, Passage, Result,
    description::{OwnerDescription, describe_owner},
    query::{Candidate, SearchOptions, SearchRequest},
    stemming::{EnglishStems, WordStemmer},
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::{Value, value::RawValue};
use std::{cell::RefCell, collections::BTreeMap, sync::Mutex};
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

fn matrix(
    value: &ken_retrieval::feature_matrix::FeatureMatrix,
) -> ken_retrieval::Result<Box<RawValue>> {
    #[derive(Serialize)]
    struct Output<'a> {
        names: &'a [PythonText],
        values: Vec<Vec<serde_json::Value>>,
    }
    let values = (0..value.values.rows())
        .map(|i| {
            value.values.values()[i * value.values.columns()..(i + 1) * value.values.columns()]
                .iter()
                .map(|v| super::tagged(*v))
                .collect()
        })
        .collect();
    super::raw(&Output {
        names: &value.names,
        values,
    })
}
pub fn run(text: &str, kind: &str) -> super::Observation {
    let mut extra = super::Observation::new();
    let input: Input = match serde_json::from_str(text) {
        Ok(v) => v,
        Err(e) => return super::finish(Err(e.into()), extra),
    };
    let encoder = Encoder::new(&input);
    let stems = Stems::new(&input);
    let got = (|| -> Result<Box<RawValue>> {
        use ken_retrieval::{
            contextual_features::contextual_features,
            coverage::coverage,
            evidence_features::{base_features, evidence_features},
        };
        if kind == "coverage" {
            let fields: Vec<_> = input.fields.iter().map(String::as_str).collect();
            let query = input
                .query
                .as_ref()
                .ok_or_else(|| super::invalid("query required"))?;
            let got = coverage(
                query,
                &input.documents,
                &fields,
                &encoder,
                input.stemmer.as_ref().map(|_| &stems as &dyn WordStemmer),
            )?;
            let value: Vec<BTreeMap<_, _>> = got
                .into_iter()
                .map(|row| {
                    row.into_iter()
                        .map(|(k, v)| (k, super::tagged(v)))
                        .collect()
                })
                .collect();
            return super::raw(&value);
        }
        let candidates: Vec<_> = input
            .candidates
            .iter()
            .map(RawCandidate::materialize)
            .collect();
        if kind == "feature_context" {
            return matrix(&contextual_features(&candidates, input.source_views)?);
        }
        let request = request(&input);
        if kind == "base" {
            return super::raw(
                &candidates
                    .iter()
                    .map(|c| base_features(&request, c))
                    .collect::<Result<Vec<_>>>()?,
            );
        }
        matrix(&evidence_features(
            &request,
            &candidates,
            &descriptions(&input),
            &encoder,
            &stems,
            input.expanded.as_ref(),
        )?)
    })();
    extra.insert(
        "encoder_calls".into(),
        super::raw(&*encoder.calls.borrow()).expect("observed calls"),
    );
    extra.insert(
        "stemmer_calls".into(),
        super::raw(&*stems.calls.lock().unwrap()).expect("observed stem calls"),
    );
    super::finish(got, extra)
}
