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
