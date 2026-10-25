#[path = "../examples/support/symbol_preferences.rs"]
mod support;
mod symbol_views_support;
use ken_retrieval::{
    Result,
    paired_reranker::{NeuralScores, PairedReranker},
    query::SearchRequest,
    symbol_preferences::apply_symbol_preferences,
    symbol_requirements::requirements,
    symbol_views::rank_symbol_views,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
    catalogs: Vec<Catalog>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: support::Input,
    result: Value,
}
#[derive(Deserialize)]
struct Catalog {
    input: support::Physical,
    result: Value,
}
fn corpus() -> Corpus {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/symbol-preferences-reference.json.gz").as_slice(),
    )
    .read_to_string(&mut raw)
    .unwrap();
    serde_json::from_str(&ken_retrieval::json_transport::python_strings(&raw).unwrap()).unwrap()
}
#[test]
fn frozen_requirements_preserve_explicit_intent_and_python_text() {
    let data = corpus();
    assert_eq!(data.cases.len(), 286);
    for case in data.cases.into_iter().filter(|c| c.kind == "requirements") {
        assert_eq!(
            support::observe(&case.kind, &case.input).unwrap(),
            case.result,
            "{}",
            case.id
        );
    }
}
#[test]
fn frozen_preferences_preserve_stable_three_pass_order_and_membership() {
    for case in corpus()
        .cases
        .into_iter()
        .filter(|c| c.kind == "preferences")
    {
        let got = support::observe(&case.kind, &case.input).unwrap();
        assert_eq!(got, case.result, "{}", case.id);
        let mut order: Vec<usize> = serde_json::from_value(got["order"].clone()).unwrap();
        order.sort_unstable();
        assert_eq!(order, (0..case.input.order.len()).collect::<Vec<_>>());
    }
}
#[test]
fn frozen_test_identity_uses_catalog_snapshot_and_callable_boundaries() {
    for case in corpus().catalogs {
        assert_eq!(support::classify(case.input).unwrap(), case.result);
    }
}
#[test]
fn malformed_candidate_evidence_and_orders_return_errors() {
    let required = requirements(&SearchRequest::new("Find tests with AND").unwrap());
    let witnesses = vec![BTreeSet::new(); 2];
    let flags = vec![false; 2];
    let code = vec![PythonText::from("AND"); 2];
    for order in [
        vec![0],
        vec![0, 0],
        vec![2, 0],
        vec![usize::MAX, 1],
        vec![1, 0, 2],
    ] {
        assert!(apply_symbol_preferences(&required, &witnesses, &flags, &code, &order).is_err());
    }
    assert!(apply_symbol_preferences(&required, &witnesses[..1], &flags, &code, &[1, 0]).is_err());
    assert!(apply_symbol_preferences(&required, &witnesses, &flags[..1], &code, &[1, 0]).is_err());
    assert!(apply_symbol_preferences(&required, &witnesses, &flags, &code[..1], &[1, 0]).is_err());
}
struct Fallback;
impl PairedReranker for Fallback {
    fn pair_fits(&self, _: &PythonText, _: &PythonText) -> Result<bool> {
        Ok(false)
    }
    fn score(&self, _: &PythonText, texts: &[PythonText]) -> Result<NeuralScores> {
        assert!(texts.is_empty());
        Ok(NeuralScores {
            scores: vec![],
            details: json!({}),
        })
    }
}
#[test]
fn preferences_compose_after_neural_views_without_changing_scores() {
    let data = symbol_views_support::corpus();
    let description = data
        .cases
        .iter()
        .find(|c| c.id == "rank-single")
        .unwrap()
        .input
        .descriptions[0]
        .clone();
    let views = rank_symbol_views(
        &"x".into(),
        &[description.clone(), description.clone(), description],
        &[0., 4., 2.],
        &Fallback,
    )
    .unwrap();
    assert_eq!(views.order, [1, 2, 0]);
    let required =
        requirements(&SearchRequest::new("Find tests that keep exception cause AND").unwrap());
    let witnesses = vec![
        BTreeSet::from(["cause:Other".into()]),
        BTreeSet::new(),
        BTreeSet::new(),
    ];
    let order = apply_symbol_preferences(
        &required,
        &witnesses,
        &[false, true, false],
        &["AND".into(), "".into(), "AND".into()],
        &views.order,
    )
    .unwrap();
    assert_eq!(order, [0, 2, 1]);
    assert_eq!(views.mean_scores, [0., 4., 2.]);
}
#[test]
fn java_test_annotations_obey_twelve_line_and_first_brace_bounds() {
    use sha2::{Digest, Sha256};
    for (prefix, expected) in [
        ("// line\n".repeat(11), true),
        ("// line\n".repeat(12), false),
        ("// { brace\n".into(), false),
    ] {
        let mut physical = corpus().catalogs.pop().unwrap().input;
        physical
            .owners
            .retain(|o| o.key.qualname.as_deref() == Some("Sample.direct"));
        assert_eq!(physical.owners.len(), 1);
        let owner = &mut physical.owners[0];
        let text = format!("{prefix}@Test\nvoid direct() {{}}\n");
        let count = text.lines().count();
        let hash = format!("{:x}", Sha256::digest(text.as_bytes()));
        for p in &mut owner.passages {
            p.source_hash = hash.clone();
            p.span.start_line = 1;
            p.span.end_line = count;
            p.entity_span = p.span;
        }
        physical.files = BTreeMap::from([(owner.key.path.clone(), text.into_bytes())]);
        let key = owner.key.clone();
        let (_directory, catalog) = support::catalog(physical).unwrap();
        assert_eq!(
            ken_retrieval::symbol_preferences::is_test_case(&key, &catalog).unwrap(),
            expected
        );
    }
}
