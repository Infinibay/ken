//! Input-only two-view inference: both card and code logits come from native Ettin.
use ken_models::{NativeOnnxRuntime, OnnxReranker, RerankOptions, RerankerModel};
use ken_retrieval::{
    Result,
    description::OwnerDescription,
    paired_reranker::{NeuralScores, OnnxPairedReranker, PairedReranker},
    symbol_views::{complete_code_view, rank_symbol_views},
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{cell::RefCell, io::Read, path::PathBuf, sync::Arc};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    registration: Value,
    source: PathBuf,
    cache: PathBuf,
    runtime_registration: Value,
    library: PathBuf,
    frames: Vec<Frame>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Frame {
    id: String,
    query: PythonText,
    descriptions: Vec<OwnerDescription>,
    card_texts: Vec<PythonText>,
    options: RerankOptions,
}
#[derive(Serialize)]
struct Call {
    op: &'static str,
    query: PythonText,
    #[serde(skip_serializing_if = "Option::is_none")]
    text: Option<PythonText>,
    #[serde(skip_serializing_if = "Option::is_none")]
    texts: Option<Vec<PythonText>>,
}
struct Observed<'a> {
    inner: &'a dyn PairedReranker,
    calls: RefCell<Vec<Call>>,
}
impl PairedReranker for Observed<'_> {
    fn pair_fits(&self, q: &PythonText, text: &PythonText) -> Result<bool> {
        self.calls.borrow_mut().push(Call {
            op: "pair_fits",
            query: q.clone(),
            text: Some(text.clone()),
            texts: None,
        });
        self.inner.pair_fits(q, text)
    }
    fn score(&self, q: &PythonText, texts: &[PythonText]) -> Result<NeuralScores> {
        self.calls.borrow_mut().push(Call {
            op: "score",
            query: q.clone(),
            text: None,
            texts: Some(texts.to_vec()),
        });
        self.inner.score(q, texts)
    }
}
fn run() -> std::result::Result<Value, Box<dyn std::error::Error>> {
    let mut raw = String::new();
    std::io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_string(&mut raw)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err("symbol view request exceeds8MiB".into());
    }
    let request: Request =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw)?)?;
    if request.frames.is_empty() || !request.source.is_absolute() || !request.cache.is_absolute() {
        return Err("nonempty frames and explicit source/cache required".into());
    }
    let model = RerankerModel::from_json(&request.registration.to_string())?;
    let prepared = Arc::new(model.prepare(Some(&request.source), &request.cache)?);
    let runtime =
        NativeOnnxRuntime::from_json(&request.runtime_registration.to_string(), &request.library)?;
    let mut results = Vec::new();
    for frame in request.frames {
        if frame.descriptions.len() != frame.card_texts.len() {
            return Err("one card text per symbol required".into());
        }
        let adapter = OnnxPairedReranker(Arc::new(OnnxReranker::new(
            model.clone(),
            Some(prepared.clone()),
            None,
            request.cache.clone(),
            runtime.clone(),
            frame.options,
        )?));
        let neural = Observed {
            inner: &adapter,
            calls: RefCell::default(),
        };
        let original = neural.score(&frame.query, &frame.card_texts)?;
        let ranked =
            rank_symbol_views(&frame.query, &frame.descriptions, &original.scores, &neural)?;
        let views = frame
            .descriptions
            .iter()
            .map(complete_code_view)
            .collect::<Result<Vec<_>>>()?;
        let mut result = serde_json::to_value(ranked)?;
        let object = result
            .as_object_mut()
            .ok_or("symbol result is not an object")?;
        object.insert("views".into(), serde_json::to_value(views)?);
        object.insert("original_scores".into(), json!(original.scores));
        object.insert("first_inference".into(), original.details);
        results.push(json!({"id":frame.id,"result":result,"calls":neural.calls.into_inner()}));
    }
    Ok(
        json!({"format":"ken-symbol-views-native/1","runtime":runtime.loaded_identity()?,"results":results}),
    )
}
fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("symbol_views_probe: {error}");
            std::process::exit(1);
        }
    }
}
