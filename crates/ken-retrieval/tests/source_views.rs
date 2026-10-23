#[path = "common/context_cases.rs"]
mod cases;
#[test]
fn registered_source_views_and_owned_texts_match_original() {
    cases::run(&["source_views", "view_texts"]);
}
