pub mod feature_support;
pub mod owner_support;
#[test]
fn original_owner_ranking_versions_profiles_expansion_and_evidence() {
    for case in owner_support::cases()
        .into_iter()
        .filter(|c| !c.kind.starts_with("trace_"))
    {
        owner_support::observe(case);
    }
}
