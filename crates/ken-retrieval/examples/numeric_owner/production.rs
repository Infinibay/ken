use super::{Observation, Resources, Result, features as f, finish, invalid, raw};
use ken_models::{EncoderSpec, StaticTableEncoder};
use ken_retrieval::{
    matrix::Matrix, numeric_ranker::NumericRanker, owner_ranking::EvidenceReranker,
    rank_models::ProductionRankModels, ranking_trace::RankingTrace, word_encoder::WordEncoder,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{cell::RefCell, fs, io::Read, rc::Rc, sync::Arc};
const STATIC_SHA: &str = "e6ab79ad2462d447d367ac4c9735e1062cb752ba6ed50901773ec2bd427a1ff0";
pub struct Runtime<'a> {
    resources: &'a Resources,
    models: RefCell<Option<ProductionRankModels>>,
    words: RefCell<Option<Rc<StaticWords>>>,
}
#[derive(Deserialize)]
struct Input {
    role: String,
    rows: Option<usize>,
}
pub(crate) struct StaticWords {
    table: StaticTableEncoder,
    spec: EncoderSpec,
    calls: RefCell<Vec<f::Call>>,
}
impl WordEncoder for StaticWords {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        self.calls.borrow_mut().push(f::Call {
            op: "query".into(),
            text: Some(text.clone()),
            texts: None,
        });
        Ok(self.table.embed_query(
            &text
                .to_utf8()
                .ok_or_else(|| invalid("non-scalar static query"))?,
        )?)
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        self.calls.borrow_mut().push(f::Call {
            op: "passages".into(),
            text: None,
            texts: Some(texts.to_vec()),
        });
        let texts: Vec<_> = texts
            .iter()
            .map(|s| s.to_utf8().ok_or_else(|| invalid("non-scalar static word")))
            .collect::<Result<_>>()?;
        Ok(self
            .table
            .embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?)
    }
}
impl StaticWords {
    pub(crate) fn take_calls(&self) -> Vec<f::Call> {
        self.calls.take()
    }
}
impl<'a> Runtime<'a> {
    pub fn new(resources: &'a Resources) -> Self {
        Self {
            resources,
            models: RefCell::new(None),
            words: RefCell::new(None),
        }
    }
    pub(crate) fn model(&self, role: &str) -> Result<Arc<NumericRanker>> {
        let mut models = self.models.borrow_mut();
        if models.is_none() {
            *models = Some(ProductionRankModels::open(
                self.resources
                    .ranking
                    .as_ref()
                    .ok_or_else(|| invalid("registered ranking resources required"))?,
            )?);
        }
        let models = models.as_ref().expect("opened registry");
        match role {
            "native" => models.native(),
            "piece" => models.piece(),
            _ => Err(invalid("unknown registered forest role")),
        }
    }
    pub(crate) fn words(&self) -> Result<Rc<StaticWords>> {
        let mut words = self.words.borrow_mut();
        if let Some(words) = &*words {
            return Ok(words.clone());
        }
        let path = self
            .resources
            .static_table
            .as_ref()
            .ok_or_else(|| invalid("registered static resource required"))?;
        let mut bytes = Vec::new();
        fs::File::open(path)
            .and_then(|f| f.take(64 * 1024 * 1024 + 1).read_to_end(&mut bytes))
            .map_err(|e| invalid(&format!("static resource: {e}")))?;
        if bytes.len() > 64 * 1024 * 1024 || format!("{:x}", Sha256::digest(&bytes)) != STATIC_SHA {
            return Err(invalid("registered static resource identity mismatch"));
        }
        let spec: EncoderSpec = serde_json::from_value(
            json!({"model_id":"ken/static-qwen3-r512-v2","revision":STATIC_SHA,"backend":"static"}),
        )?;
        let encoder = Rc::new(StaticWords {
            table: StaticTableEncoder::from_npz(&bytes)?,
            spec,
            calls: RefCell::default(),
        });
        *words = Some(encoder.clone());
        Ok(encoder)
    }
    pub fn run(&self, text: &str, kind: &str) -> Observation {
        let mut extra = Observation::new();
        let mut calls = Vec::new();
        let mut stem_calls = Vec::new();
        let got = (|| -> Result<Box<serde_json::value::RawValue>> {
            let input: Input = serde_json::from_str(text)?;
            let model = self.model(&input.role)?;
            if kind == "production_identity" {
                let name = format!("{}-forest-mean-v140.json.gz", input.role);
                let bytes = fs::read(
                    self.resources
                        .ranking
                        .as_ref()
                        .expect("opened resource")
                        .join(name),
                )
                .map_err(|e| invalid(&e.to_string()))?;
                let mut decoded = Vec::new();
                flate2::read::GzDecoder::new(&bytes[..])
                    .take(16 * 1024 * 1024 + 1)
                    .read_to_end(&mut decoded)
                    .map_err(|e| invalid(&e.to_string()))?;
                return raw(
                    &json!({"fingerprint":model.fingerprint()?,"features":model.features(),"trees":model.tree_count(),"compressed_sha256":format!("{:x}",Sha256::digest(&bytes)),"compressed_bytes":bytes.len(),"decoded_sha256":format!("{:x}",Sha256::digest(&decoded)),"decoded_bytes":decoded.len()}),
                );
            }
            if kind == "production_predict" {
                let rows = input
                    .rows
                    .ok_or_else(|| invalid("prediction rows required"))?;
                if rows > 1024 {
                    return Err(invalid("bounded prediction rows required"));
                }
                let width = model.features().len();
                let values = (0..rows)
                    .flat_map(|r| {
                        (0..width).map(move |c| ((r * 17 + c * 7) % 257) as f64 / 16. - 8.)
                    })
                    .collect();
                return raw(&json!({"scores":model.predict(&Matrix::new(rows,width,values)?)?}));
            }
            let mut base: f::Input = serde_json::from_str(text)?;
            base.stemmer = Some("english".into());
            let request = f::request(&base);
            let candidates: Vec<_> = base
                .candidates
                .iter()
                .map(f::RawCandidate::materialize)
                .collect();
            let descriptions = f::descriptions(&base);
            let words = self.words()?;
            let stems = Arc::new(f::Stems::new(&base));
            let result = (|| -> Result<Value> {
                let runtime =
                    EvidenceReranker::new(model.clone(), words.clone(), stems.clone(), None)?;
                let mut trace = RankingTrace::new(Some("production-static-composition".into()))?;
                let matches = runtime.rank(
                    &request,
                    &candidates,
                    &descriptions,
                    base.expanded.as_ref(),
                    3,
                    Some(&mut trace),
                )?;
                let trace: Value = serde_json::from_str(&trace.to_json(true)?)?;
                if kind == "production_paths" {
                    return Ok(json!({"paths_sha256":path_digest(&trace,&model)?}));
                }
                Ok(
                    json!({"matches":matches,"trace":trace,"static_sha256":STATIC_SHA,"word_spec":words.spec()}),
                )
            })();
            calls = words.take_calls();
            stem_calls = stems
                .calls
                .lock()
                .map_err(|_| invalid("stem call log poisoned"))?
                .clone();
            raw(&result?)
        })();
        extra.insert("encoder_calls".into(), raw(&calls).expect("word calls"));
        extra.insert(
            "stemmer_calls".into(),
            raw(&stem_calls).expect("stem calls"),
        );
        finish(got, extra)
    }
}
fn path_digest(trace: &Value, model: &NumericRanker) -> Result<String> {
    type LeafRoute = (String, Vec<(usize, String)>);
    let owners = trace["owners"]
        .as_array()
        .ok_or_else(|| invalid("trace owners required"))?;
    let paths: Vec<Vec<LeafRoute>> = owners
        .iter()
        .map(|owner| -> Result<_> {
            let row: Vec<f64> = serde_json::from_value(owner["feature_values"].clone())?;
            Ok(model
                .explain_pair(&row, &row)?
                .trees
                .into_iter()
                .map(|tree| {
                    (
                        format!("{:016x}", tree.left_leaf.to_bits()),
                        tree.left_path
                            .into_iter()
                            .map(|s| (s.feature_index, s.branch))
                            .collect(),
                    )
                })
                .collect())
        })
        .collect::<Result<_>>()?;
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(&paths)?)))
}
