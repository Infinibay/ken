//! Public ranker caller over physical inputs; no expected ranking enters this adapter.
#[path = "source_catalog.rs"]
mod source_catalog;
use ken_models::RerankOptions;
use ken_retrieval::{
    EntityKey, Result, RetrievalError,
    owner_descriptions::OwnerDescriptions,
    paired_reranker::{NeuralScores, PairedReranker},
    piece_cards::{build_card, card_text},
    query::SearchRequest,
    source_catalog::PieceIdentity,
    symbol_ranking::SymbolRanker,
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
    pub request: SearchRequest,
    pub expanded_query: PythonText,
    pub original_scores: Vec<f64>,
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
    pub fn controlled(control: Control) -> Self {
        Self {
            control,
            inner: None,
            calls: RefCell::default(),
        }
    }
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
            details: json!({"model":"controlled-symbol-composition","documents":texts.len()}),
        })
    }
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
    let (directory, catalog) = catalog(input.physical)?;
    let catalog = Arc::new(catalog);
    let cards = if inner.is_some() {
        input
            .keys
            .iter()
            .map(|k| {
                build_card(
                    &PieceIdentity::Entity(k.clone()),
                    "symbol",
                    std::slice::from_ref(k),
                    &input.expanded_query,
                    &catalog,
                )
                .map(|c| PythonText::from(card_text(&c)))
            })
            .collect::<std::result::Result<Vec<_>, _>>()?
    } else {
        Vec::new()
    };
    let real = inner.is_some();
    let neural = Rc::new(if let Some(inner) = inner {
        Observed {
            control: input.model,
            inner: Some(inner),
            calls: RefCell::default(),
        }
    } else {
        Observed::controlled(input.model)
    });
    let mut descriptions = OwnerDescriptions::new(catalog.clone());
    let mut ranker = SymbolRanker::new(catalog.clone(), neural.clone(), grammars);
    for path in catalog.snapshots().keys() {
        fs::write(
            directory.path().join(path),
            b"changed after snapshot construction\n",
        )?;
    }
    let mut rows = Vec::new();
    for _ in 0..2 {
        neural.clear();
        let mut row = json!({});
        let mut originals = input.original_scores.clone();
        if real {
            let first = neural.score(&input.expanded_query, &cards)?;
            originals = first.scores;
            row["first_scores"] = json!(originals);
            row["first_inference"] = first.details;
        }
        match ranker.rank(
            &input.request,
            &input.keys,
            &input.expanded_query,
            &originals,
            &mut descriptions,
        ) {
            Ok(result) => row["result"] = serde_json::to_value(result)?,
            Err(error) => row["error"] = json!({"type":"ValueError","message":error.to_string()}),
        }
        row["calls"] = json!(neural.calls());
        row["cache"] = json!(descriptions.iter().map(Arc::as_ref).collect::<Vec<_>>());
        rows.push(row);
    }
    Ok(json!(rows))
}
