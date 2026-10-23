pub mod feature_support;
pub mod owner_support;
#[test]
fn original_trace_copy_restore_queries_order_paths_and_default_ids() {
    for case in owner_support::cases()
        .into_iter()
        .filter(|c| c.kind.starts_with("trace_"))
    {
        owner_support::observe(case);
    }
}

#[test]
fn imported_trace_rejects_ragged_owner_rows_even_when_total_shape_and_scores_match() {
    use ken_retrieval::{numeric_ranker::NumericRanker, ranking_trace::RankingTrace};
    let corpus: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/numeric-review-regressions.json")).unwrap();
    let model = NumericRanker::from_json(&corpus["trace_model"].to_string()).unwrap();
    let trace = corpus["ragged_trace"].to_string();
    assert!(RankingTrace::from_json(&trace, &model).is_err());
}
