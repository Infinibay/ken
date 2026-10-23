#[path = "common/context_cases.rs"]
mod cases;
#[test]
fn complete_contextual_owners_queries_and_source_versions_match_original() {
    cases::run(&["context"]);
}
