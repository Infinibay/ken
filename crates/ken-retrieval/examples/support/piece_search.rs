//! Input-only PieceSearch caller using concrete numeric ranking and shared paired model.
#[path = "source_catalog.rs"]
mod source_catalog;
use ken_models::{EncoderSpec, RerankOptions};
use ken_retrieval::{
    EntityKey, Result, RetrievalError,
    numeric_ranker::NumericRanker,
    paired_reranker::{NeuralScores, PairedReranker},
    piece_features::piece_feature_names,
    piece_ranking::PieceReranker,
    piece_search::PieceSearch,
    query::{CodeMatch, SearchRequest, Signals},
    stemming::WordStemmer,
    word_encoder::WordEncoder,
};
use ken_syntax::GrammarCatalog;
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
pub use source_catalog::{Physical, ProbeResult, catalog};
use std::{cell::RefCell, fs, rc::Rc, sync::Arc};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub physical: Physical,
    pub keys: Vec<EntityKey>,
    pub scores: Vec<f64>,
    pub signals: Vec<Signals>,
    pub request: SearchRequest,
    pub expanded_query: PythonText,
    pub exact: bool,
    pub forest: String,
    pub disk: String,
    pub model: Control,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Control {
    pub kind: String,
    #[serde(default)]
    pub mode: Option<String>,
    #[serde(default)]
    pub pair_budget: Option<usize>,
    #[serde(default)]
    pub fail_pair: bool,
    #[serde(default)]
    pub fail_score: bool,
    #[serde(default)]
    pub options: RerankOptions,
}
pub struct Observed {
    control: Control,
    inner: Option<Rc<dyn PairedReranker>>,
    calls: RefCell<Vec<Value>>,
}
impl Observed {
    pub fn clear(&self) {
        self.calls.borrow_mut().clear();
    }
    pub fn calls(&self) -> Vec<Value> {
        self.calls.borrow().clone()
    }
}
impl PairedReranker for Observed {
    fn pair_fits(&self, q: &PythonText, t: &PythonText) -> Result<bool> {
        self.calls
            .borrow_mut()
            .push(json!({"op":"pair_fits","query":q,"text":t}));
        if self.control.fail_pair {
            return Err(RetrievalError::Invalid("pair failed".into()));
        }
        if let Some(inner) = &self.inner {
            return inner.pair_fits(q, t);
        }
        Ok(q.codepoints().len() + t.codepoints().len()
            <= self
                .control
                .pair_budget
                .ok_or_else(|| RetrievalError::Invalid("controlled pair budget required".into()))?)
    }
    fn score(&self, q: &PythonText, texts: &[PythonText]) -> Result<NeuralScores> {
        self.calls
            .borrow_mut()
            .push(json!({"op":"score","query":q,"texts":texts}));
        if self.control.fail_score {
            return Err(RetrievalError::Invalid("score failed".into()));
        }
        if let Some(inner) = &self.inner {
            return inner.score(q, texts);
        }
        let scores = texts
            .iter()
            .map(|t| match self.control.mode.as_deref() {
                Some("zero") => Ok(0.),
                Some("length") => Ok((t.codepoints().len() % 19) as f64 / 4. - 9. / 4.),
                _ => Err(RetrievalError::Invalid(
                    "controlled score mode differs".into(),
                )),
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(NeuralScores {
            scores,
            details: json!({"model":"controlled-piece-search","documents":texts.len()}),
        })
    }
}

struct Words(EncoderSpec);
impl WordEncoder for Words {
    fn spec(&self) -> &EncoderSpec {
        &self.0
    }
    fn embed_query(&self, _: &PythonText) -> Result<Vec<f32>> {
        Ok(vec![1., 0.])
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        Ok(texts.iter().map(|_| vec![1., 0.]).collect())
    }
}
struct Stems;
impl WordStemmer for Stems {
    fn stem(&self, word: &PythonText) -> Result<PythonText> {
        Ok(word.clone())
    }
}
pub fn numeric_ranker(forest: &str) -> ProbeResult<PieceReranker> {
    let tree = match forest {
        "zero" => json!({"value":0.}),
        "native-score" => {
            json!({"feature":0,"threshold":5.,"left":{"value":2.},"right":{"value":-1.}})
        }
        _ => return Err("unknown numeric leaf policy".into()),
    };
    let model = NumericRanker::from_json(
        &json!({"schema":1,"features":piece_feature_names(),"trees":[tree]}).to_string(),
    )?;
    let words = Words(EncoderSpec::from_json(
        r#"{"model_id":"test/piece-search","revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","backend":"provided","batch_size":1}"#,
    )?);
    Ok(PieceReranker::new(
        Arc::new(model),
        Rc::new(words),
        Arc::new(Stems),
    )?)
}
pub fn observe(
    input: Input,
    grammars: Arc<GrammarCatalog>,
    inner: Option<Rc<dyn PairedReranker>>,
) -> ProbeResult<Value> {
    if !matches!(
        (input.model.kind.as_str(), inner.is_some()),
        ("controlled", false) | ("ettin", true)
    ) {
        return Err("explicit production model required for Ettin frames".into());
    }
    if input.keys.len() != input.scores.len() || input.keys.len() != input.signals.len() {
        return Err("match cardinality differs".into());
    }
    let (directory, catalog) = catalog(input.physical)?;
    let catalog = Arc::new(catalog);
    let matches = input
        .keys
        .iter()
        .zip(input.scores)
        .zip(input.signals)
        .map(|((k, score), signals)| {
            let passages = catalog.passages(k)?;
            Ok(CodeMatch {
                entity: k.clone(),
                score,
                evidence: passages.to_vec(),
                source_hash: passages[0].source_hash.clone(),
                signals,
                owned_regions: vec![],
            })
        })
        .collect::<std::result::Result<Vec<_>, ken_retrieval::source_snapshot::SourceError>>()?;
    let neural = Rc::new(Observed {
        control: input.model,
        inner,
        calls: RefCell::default(),
    });
    let mut search = PieceSearch::new(
        catalog.clone(),
        numeric_ranker(&input.forest)?,
        neural.clone(),
        grammars,
    );
    match input.disk.as_str() {
        "unchanged" => (),
        "changed" => {
            fs::write(
                directory
                    .path()
                    .join(catalog.snapshots().keys().next().ok_or("source required")?),
                b"changed after snapshot construction\n",
            )?;
        }
        _ => return Err("unknown disk mutation".into()),
    }
    let mut rows = Vec::new();
    for _ in 0..2 {
        neural.clear();
        let mut row = json!({});
        match search.search(
            &input.request,
            &matches,
            &input.expanded_query,
            "piece-search-composition",
            input.exact,
        ) {
            Ok(result) => row["result"] = serde_json::to_value(result)?,
            Err(error) => row["error"] = json!({"type":"ValueError","message":error.to_string()}),
        }
        row["calls"] = json!(neural.calls());
        row["cache"] = json!(
            search
                .descriptions()
                .iter()
                .map(Arc::as_ref)
                .collect::<Vec<_>>()
        );
        rows.push(row);
    }
    Ok(json!(rows))
}
