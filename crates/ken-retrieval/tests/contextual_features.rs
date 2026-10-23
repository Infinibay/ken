pub mod feature_support;
use feature_support as f;
use ken_retrieval::contextual_features::contextual_features;
#[test]
fn contextual_feature_schema_scores_and_stable_ranks_match_original() {
    for case in f::cases()
        .into_iter()
        .filter(|c| c.kind == "feature_context")
    {
        let candidates: Vec<_> = case
            .input
            .candidates
            .iter()
            .map(|c| c.materialize())
            .collect();
        let got = contextual_features(&candidates, case.input.source_views);
        match (got, case.error.as_ref()) {
            (Ok(got), None) => f::matrix(&got, case.result.as_ref().unwrap()),
            (Err(got), Some(want)) => f::error(got, want, &case.id),
            (got, want) => panic!("{}: {got:?}, wanted {want:?}", case.id),
        }
    }
}
