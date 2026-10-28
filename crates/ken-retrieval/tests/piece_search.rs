#[path = "../examples/support/piece_search.rs"]
mod support;
use ken_syntax::GrammarCatalog;
use serde_json::Value;
use std::{io::Read, sync::Arc};
fn corpus() -> Value {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/piece-search-reference.json.gz").as_slice(),
    )
    .read_to_string(&mut raw)
    .unwrap();
    serde_json::from_str(&raw).unwrap()
}
fn grammars() -> Arc<GrammarCatalog> {
    Arc::new(
        GrammarCatalog::prepared(&std::path::PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    )
}
#[test]
fn complete_controlled_piece_search_matches_original_outputs_calls_and_shared_cache() {
    for case in corpus()["cases"].as_array().unwrap() {
        if case["input"]["model"]["kind"] != "controlled" {
            continue;
        }
        let actual = support::observe(
            serde_json::from_value(case["input"].clone()).unwrap(),
            grammars(),
            None,
        )
        .unwrap();
        assert_eq!(actual, case["observations"], "{}", case["id"]);
    }
}

mod symbol_views_support;
fn real_response(got: &Value, wanted: &Value, key: &str) {
    match key {
        "neural_score" | "code_score" | "mean_score" => {
            let a = got.as_f64().unwrap();
            let b = wanted.as_f64().unwrap();
            assert!(
                a.is_finite() && (b != 0. || a == 0.) && (a - b).abs() <= 1e-5 + 1e-5 * b.abs()
            );
        }
        "reranker" | "additional_reranker" => symbol_views_support::details(got, wanted),
        _ => match wanted {
            Value::Object(w) => {
                let g = got.as_object().unwrap();
                assert_eq!(g.keys().collect::<Vec<_>>(), w.keys().collect::<Vec<_>>());
                for (k, v) in w {
                    real_response(&g[k], v, k);
                }
            }
            Value::Array(w) => {
                let g = got.as_array().unwrap();
                assert_eq!(g.len(), w.len());
                for (a, b) in g.iter().zip(w) {
                    real_response(a, b, "");
                }
            }
            _ => assert_eq!(got, wanted, "{key}"),
        },
    }
}
#[test]
fn production_ettin_piece_search_matches_three_original_compositions() {
    use ken_models::{NativeOnnxRuntime, OnnxReranker, RerankerModel};
    use ken_retrieval::paired_reranker::OnnxPairedReranker;
    use std::rc::Rc;
    let model = RerankerModel::from_json(include_str!(
        "../../ken-models/resources/ettin-68m-fp32.json"
    ))
    .unwrap();
    let source = std::path::PathBuf::from(std::env::var_os("KEN_ETTIN_SOURCE").unwrap());
    let temp = tempfile::tempdir().unwrap();
    let prepared = Arc::new(
        model
            .prepare(Some(&source), &temp.path().join("fresh"))
            .unwrap(),
    );
    let runtime = NativeOnnxRuntime::from_json(
        include_str!("../../ken-models/resources/onnx-runtime-libraries.json"),
        &std::path::PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").unwrap()),
    )
    .unwrap();
    for case in corpus()["cases"].as_array().unwrap() {
        if case["input"]["model"]["kind"] != "ettin" {
            continue;
        }
        let input: support::Input = serde_json::from_value(case["input"].clone()).unwrap();
        let neural = Rc::new(OnnxPairedReranker(Arc::new(
            OnnxReranker::new(
                model.clone(),
                Some(prepared.clone()),
                None,
                temp.path().join("unused"),
                runtime.clone(),
                input.model.options,
            )
            .unwrap(),
        )));
        let actual = support::observe(input, grammars(), Some(neural)).unwrap();
        for (got, wanted) in actual
            .as_array()
            .unwrap()
            .iter()
            .zip(case["observations"].as_array().unwrap())
        {
            assert_eq!(got["calls"], wanted["calls"], "{}", case["id"]);
            assert_eq!(got["cache"], wanted["cache"]);
            real_response(&got["result"], &wanted["result"], "");
        }
    }
}
fn matches(
    input: &support::Input,
    catalog: &ken_retrieval::source_catalog::SourceCatalog,
) -> Vec<ken_retrieval::query::CodeMatch> {
    input
        .keys
        .iter()
        .zip(&input.scores)
        .zip(&input.signals)
        .map(|((k, score), signals)| {
            let p = catalog.passages(k).unwrap();
            ken_retrieval::query::CodeMatch {
                entity: k.clone(),
                score: *score,
                evidence: p.to_vec(),
                source_hash: p[0].source_hash.clone(),
                signals: signals.clone(),
                owned_regions: vec![],
            }
        })
        .collect()
}
#[test]
fn malformed_neural_scores_fail_before_indexing_but_exact_still_uses_numeric_ranking() {
    use ken_retrieval::{
        Result,
        paired_reranker::{NeuralScores, PairedReranker},
        piece_search::PieceSearch,
    };
    use ken_text::PythonText;
    use std::{cell::Cell, rc::Rc};
    struct Bad {
        scores: Vec<f64>,
        calls: Cell<usize>,
    }
    impl PairedReranker for Bad {
        fn pair_fits(&self, _: &PythonText, _: &PythonText) -> Result<bool> {
            panic!("file search has no code views")
        }
        fn score(&self, _: &PythonText, _: &[PythonText]) -> Result<NeuralScores> {
            self.calls.set(self.calls.get() + 1);
            Ok(NeuralScores {
                scores: self.scores.clone(),
                details: serde_json::json!({}),
            })
        }
    }
    for scores in [vec![], vec![f64::NAN, 0.], vec![0., f64::INFINITY]] {
        let data = corpus()["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == "file-exact")
            .unwrap()["input"]
            .clone();
        let input: support::Input = serde_json::from_value(data.clone()).unwrap();
        let (_dir, catalog) =
            support::catalog(serde_json::from_value(data["physical"].clone()).unwrap()).unwrap();
        let incoming = matches(&input, &catalog);
        let catalog = Arc::new(catalog);
        let neural = Rc::new(Bad {
            scores,
            calls: Cell::new(0),
        });
        let mut search = PieceSearch::new(
            catalog,
            support::numeric_ranker(&input.forest).unwrap(),
            neural.clone(),
            grammars(),
        );
        let error = search
            .search(
                &input.request,
                &incoming,
                &input.expanded_query,
                "public",
                false,
            )
            .unwrap_err();
        assert!(error.to_string().contains("finite piece reranker scores"));
        assert_eq!(neural.calls.get(), 1);
        let exact = serde_json::to_value(
            search
                .search(
                    &input.request,
                    &incoming,
                    &input.expanded_query,
                    "public",
                    true,
                )
                .unwrap(),
        )
        .unwrap();
        assert_eq!(neural.calls.get(), 1);
        assert_eq!(exact["results"][0]["signals"]["piece_score"], -1.);
        assert_eq!(exact["results"].as_array().unwrap().len(), 2);
        assert!(!search.descriptions().is_empty());
    }
}
#[test]
fn display_limit_does_not_limit_top10_and_named_path_is_promoted_last() {
    let cases = corpus();
    for name in ["native-top10", "file-leading-path", "symbol-leading-path"] {
        let case = cases["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == name)
            .unwrap();
        let mut input = case["input"].clone();
        input["request"]["limit"] = 1.into();
        let actual =
            support::observe(serde_json::from_value(input).unwrap(), grammars(), None).unwrap();
        let first = &actual[0]["result"]["results"][0];
        let expected = &case["observations"][0]["result"]["results"][0];
        assert_eq!(first, expected);
        assert_eq!(actual[0]["result"]["results"].as_array().unwrap().len(), 1);
        if name != "native-top10" {
            assert_eq!(first["path"], "pkg/second.py");
        } else {
            assert_eq!(actual[0]["calls"][0]["texts"].as_array().unwrap().len(), 10);
        }
    }
}
