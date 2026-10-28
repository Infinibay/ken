#[path = "../examples/support/symbol_ranking.rs"]
mod support;
use ken_retrieval::{
    owner_descriptions::OwnerDescriptions, piece_candidates::PieceAssembler,
    symbol_ranking::SymbolRanker,
};
use ken_syntax::GrammarCatalog;
use serde_json::{Value, json};
use std::{io::Read, rc::Rc, sync::Arc};
fn corpus() -> Value {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/symbol-ranking-reference.json.gz").as_slice(),
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
fn complete_controlled_symbol_rankings_match_independent_original_cold_and_warm() {
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
#[test]
fn descriptions_are_shared_with_piece_assembly_and_bound_to_one_catalog() {
    let case = corpus()["cases"][0]["input"].clone();
    let input: support::Input = serde_json::from_value(case).unwrap();
    let (_dir, catalog) = support::catalog(input.physical).unwrap();
    let catalog = Arc::new(catalog);
    let mut assembler = PieceAssembler::new(catalog.clone());
    let key = &input.keys[0];
    let first = assembler.descriptions_mut().get(key).unwrap();
    assert_eq!(assembler.cache_len(), 1);
    let again = assembler.descriptions_mut().get(key).unwrap();
    assert!(Arc::ptr_eq(&first, &again));
    let passages = catalog.passages(key).unwrap();
    let matched = ken_retrieval::query::CodeMatch {
        entity: key.clone(),
        score: 1.,
        evidence: passages.to_vec(),
        source_hash: passages[0].source_hash.clone(),
        signals: Default::default(),
        owned_regions: vec![],
    };
    let pieces = assembler.assemble(&[matched], "symbol", 10).unwrap();
    assert!(Arc::ptr_eq(&first, &pieces[0].members()[0]));

    let model = Rc::new(support::Observed::controlled(input.model));
    let mut ranker = SymbolRanker::new(catalog.clone(), model.clone(), grammars());
    let output = ranker
        .rank(
            &input.request,
            &input.keys,
            &input.expanded_query,
            &input.original_scores,
            assembler.descriptions_mut(),
        )
        .unwrap();
    assert_eq!(output.order.len(), input.keys.len());
    assert_eq!(assembler.cache_len(), input.keys.len());
    assert!(Arc::ptr_eq(
        &first,
        &assembler.descriptions_mut().get(key).unwrap()
    ));
    let other: support::Input =
        serde_json::from_value(corpus()["cases"][0]["input"].clone()).unwrap();
    let (_other_dir, other) = support::catalog(other.physical).unwrap();
    let mut foreign = OwnerDescriptions::new(Arc::new(other));
    model.clear();
    assert!(
        ranker
            .rank(
                &input.request,
                &input.keys,
                &input.expanded_query,
                &input.original_scores,
                &mut foreign
            )
            .is_err()
    );
    assert!(model.calls().is_empty());
    assert!(foreign.is_empty());
    let mut unknown = key.clone();
    unknown.qualname = Some("absent".into());
    assert!(assembler.descriptions_mut().get(&unknown).is_err());
    assert_eq!(assembler.cache_len(), input.keys.len());
    model.clear();
    assert!(
        ranker
            .rank(
                &input.request,
                std::slice::from_ref(key),
                &input.expanded_query,
                &[f64::NAN],
                assembler.descriptions_mut()
            )
            .is_err()
    );
    assert!(model.calls().is_empty());
    assert!(
        ranker
            .rank(
                &input.request,
                &[unknown],
                &input.expanded_query,
                &[0.],
                assembler.descriptions_mut()
            )
            .is_err()
    );
    assert!(model.calls().is_empty());
    let _ = json!(output.witnesses);
}
mod symbol_views_support;
#[test]
fn production_ettin_symbol_ranker_matches_three_original_compositions() {
    use ken_models::{NativeOnnxRuntime, OnnxReranker, RerankerModel};
    use ken_retrieval::paired_reranker::OnnxPairedReranker;
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
            assert_eq!(got["calls"], wanted["calls"], "{} calls", case["id"]);
            assert_eq!(got["cache"], wanted["cache"]);
            assert_eq!(got["result"]["order"], wanted["result"]["order"]);
            assert_eq!(got["result"]["witnesses"], wanted["result"]["witnesses"]);
            assert_eq!(
                got["result"]["code_view_used"],
                wanted["result"]["code_view_used"]
            );
            for path in [
                &["first_scores"][..],
                &["result", "code_scores"][..],
                &["result", "mean_scores"][..],
            ] {
                let (mut a, mut b) = (got, wanted);
                for key in path {
                    a = &a[*key];
                    b = &b[*key];
                }
                let scores = serde_json::from_value::<Vec<f64>>(a.clone()).unwrap();
                symbol_views_support::real_scores(&scores, b);
            }
            symbol_views_support::details(&got["first_inference"], &wanted["first_inference"]);
            symbol_views_support::details(
                &got["result"]["additional_inference"],
                &wanted["result"]["additional_inference"],
            );
        }
    }
}
#[test]
fn replaced_assembly_cache_rejects_foreign_catalog_metadata() {
    let data = corpus()["cases"][0]["input"].clone();
    let mut foreign = data.clone();
    foreign["physical"]["owners"][0]["passages"][0]["fields"]["signature"] =
        "foreign canonical signature".into();
    let input: support::Input = serde_json::from_value(data).unwrap();
    let foreign: support::Input = serde_json::from_value(foreign).unwrap();
    let (_dir, catalog) = support::catalog(input.physical).unwrap();
    let catalog = Arc::new(catalog);
    let (_other_dir, other) = support::catalog(foreign.physical).unwrap();
    let other = Arc::new(other);
    let key = &input.keys[0];
    let passages = catalog.passages(key).unwrap();
    let matched = ken_retrieval::query::CodeMatch {
        entity: key.clone(),
        score: 1.,
        evidence: passages.to_vec(),
        source_hash: passages[0].source_hash.clone(),
        signals: Default::default(),
        owned_regions: vec![],
    };
    let mut replacement = OwnerDescriptions::new(other);
    let description = replacement.get(key).unwrap();
    assert_ne!(
        description.fields["signature"],
        ken_retrieval::description::describe_owner(passages)
            .unwrap()
            .fields["signature"]
    );
    let mut assembler = PieceAssembler::new(catalog);
    *assembler.descriptions_mut() = replacement;
    let error = assembler.assemble(&[matched], "symbol", 10).unwrap_err();
    assert!(error.to_string().contains("different catalog"), "{error}");
    assert_eq!(assembler.cache_len(), 1);
}
