mod symbol_views_support;
use ken_models::{NativeOnnxRuntime, OnnxReranker, RerankOptions, RerankerModel};
use ken_retrieval::{
    Result,
    paired_reranker::{NeuralScores, OnnxPairedReranker, PairedReranker},
    symbol_views::rank_symbol_views,
};
use ken_text::PythonText;
use std::{cell::RefCell, fs, path::PathBuf, sync::Arc};
use symbol_views_support::*;
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../ken-models/tests/fixtures/ettin")
}
fn manifest() -> serde_json::Value {
    serde_json::from_slice(&fs::read(root().join("manifest.json")).unwrap()).unwrap()
}
fn runtime(path: PathBuf) -> NativeOnnxRuntime {
    NativeOnnxRuntime::from_json(
        include_str!("../../ken-models/resources/onnx-runtime-libraries.json"),
        &path,
    )
    .unwrap()
}
fn actual_runtime() -> NativeOnnxRuntime {
    runtime(
        std::env::var_os("KEN_ORT_LIBRARY")
            .expect("prepare actual ONNX core")
            .into(),
    )
}
struct Observed<'a> {
    inner: &'a dyn PairedReranker,
    calls: RefCell<Vec<Call>>,
}
impl PairedReranker for Observed<'_> {
    fn pair_fits(&self, q: &PythonText, text: &PythonText) -> Result<bool> {
        self.calls.borrow_mut().push(Call {
            op: "pair_fits".into(),
            query: q.clone(),
            text: Some(text.clone()),
            texts: None,
        });
        self.inner.pair_fits(q, text)
    }
    fn score(&self, q: &PythonText, texts: &[PythonText]) -> Result<NeuralScores> {
        self.calls.borrow_mut().push(Call {
            op: "score".into(),
            query: q.clone(),
            text: None,
            texts: Some(texts.to_vec()),
        });
        self.inner.score(q, texts)
    }
}
#[test]
fn empty_scoring_keeps_unavailable_model_and_non_scalar_query_lazy() {
    let manifest = manifest();
    let model = RerankerModel::from_json(&manifest["pair"]["definition"].to_string()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let missing = runtime(temp.path().join("missing-core"));
    let adapter = OnnxPairedReranker(Arc::new(
        OnnxReranker::new(
            model,
            None,
            None,
            temp.path().join("cache"),
            missing,
            RerankOptions::default(),
        )
        .unwrap(),
    ));
    let query = PythonText::from_codepoints(vec![0xd800]).unwrap();
    let scores = adapter.score(&query, &[]).unwrap();
    assert!(scores.scores.is_empty());
    assert_eq!(
        scores.details,
        serde_json::json!({"token_ms":0.,"inference_ms":0.,"truncated_documents":0,"pair_tokens":[]})
    );
    assert!(!adapter.0.is_prepared().unwrap());
    assert!(adapter.pair_fits(&query, &"x".into()).is_err());
    assert!(adapter.score(&query, &["x".into()]).is_err());
    assert!(!adapter.0.is_prepared().unwrap());
}
#[test]
fn actual_pair_capacity_and_raw_scores_survive_adapter() {
    let manifest = manifest();
    let row = &manifest["pair"];
    let model = RerankerModel::from_json(&row["definition"].to_string()).unwrap();
    let prepared = Arc::new(
        model
            .verify_prepared(&root().join(row["prepared"].as_str().unwrap()))
            .unwrap(),
    );
    let temp = tempfile::tempdir().unwrap();
    let adapter = OnnxPairedReranker(Arc::new(
        OnnxReranker::new(
            model,
            Some(prepared),
            None,
            temp.path().join("unused"),
            actual_runtime(),
            RerankOptions {
                max_tokens: 16,
                ..RerankOptions::default()
            },
        )
        .unwrap(),
    ));
    assert!(
        adapter
            .pair_fits(&"x".into(), &"y ".repeat(12).into())
            .unwrap()
    );
    assert!(
        !adapter
            .pair_fits(&"x".into(), &"y ".repeat(13).into())
            .unwrap()
    );
    let scores = adapter.score(&"x".into(), &["y".into()]).unwrap();
    assert_eq!(scores.scores, [29.]);
    assert_eq!(scores.details["pair_tokens"], serde_json::json!([5]));
}
#[test]
fn production_ettin_first_and_second_views_match_five_new_original_frames() {
    let corpus = corpus();
    assert_eq!(corpus.frames.len(), 5);
    let model = RerankerModel::from_json(include_str!(
        "../../ken-models/resources/ettin-68m-fp32.json"
    ))
    .unwrap();
    let source =
        PathBuf::from(std::env::var_os("KEN_ETTIN_SOURCE").expect("prepare actual Ettin source"));
    let temp = tempfile::tempdir().unwrap();
    let prepared = Arc::new(
        model
            .prepare(Some(&source), &temp.path().join("fresh"))
            .unwrap(),
    );
    for frame in corpus.frames {
        let input = frame.input;
        let adapter = OnnxPairedReranker(Arc::new(
            OnnxReranker::new(
                model.clone(),
                Some(prepared.clone()),
                None,
                temp.path().join("unused"),
                actual_runtime(),
                input.options,
            )
            .unwrap(),
        ));
        let neural = Observed {
            inner: &adapter,
            calls: RefCell::default(),
        };
        let first = neural.score(&input.query, &input.card_texts).unwrap();
        let ranked =
            rank_symbol_views(&input.query, &input.descriptions, &first.scores, &neural).unwrap();
        assert_eq!(*neural.calls.borrow(), frame.calls, "{}", input.id);
        real_scores(&first.scores, &frame.result["original_scores"]);
        real_scores(&ranked.code_scores, &frame.result["code_scores"]);
        real_scores(&ranked.mean_scores, &frame.result["mean_scores"]);
        assert_eq!(
            serde_json::to_value(&ranked.order).unwrap(),
            frame.result["order"],
            "{}",
            input.id
        );
        assert_eq!(
            serde_json::to_value(&ranked.code_view_used).unwrap(),
            frame.result["code_view_used"]
        );
        details(&first.details, &frame.result["first_inference"]);
        details(
            &ranked.additional_inference,
            &frame.result["additional_inference"],
        );
    }
}
