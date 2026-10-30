use ken_responsibility::{WhoReport, structure};
use ken_structural::application::inspection::Program;
use serde_json::{Value, json};
use std::{path::PathBuf, sync::Arc};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/responsibility-structure.json")).unwrap()
}
fn catalog() -> Arc<ken_syntax::GrammarCatalog> {
    Arc::new(
        ken_syntax::GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    )
}
#[test]
fn original_structural_join_preserves_scores_return_occurrences_and_partial_coverage() {
    let f = fixture();
    for case in f["cases"].as_array().unwrap() {
        let mut batch = f["batch"].clone();
        if case["kind"] == "partial" {
            for name in ["calls", "usages"] {
                batch["results"][name]["complete"] = json!(false);
                batch["results"][name]["reason"] = json!("bounded observation");
            }
        }
        let program = Program::from_batch(".", &batch).unwrap();
        let mut result: WhoReport = serde_json::from_str(&case["initial"].to_string()).unwrap();
        structure::enrich_program(&mut result, &program).unwrap();
        assert_eq!(
            result.to_json().unwrap(),
            case["result"],
            "{}",
            case["kind"]
        );
    }
}
#[test]
fn real_native_inspection_enriches_candidates_under_one_structural_budget() {
    let f = fixture();
    let d = tempfile::tempdir().unwrap();
    for (path, source) in f["files"].as_object().unwrap() {
        let file = d.path().join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, source.as_str().unwrap()).unwrap();
    }
    let mut result: WhoReport =
        serde_json::from_str(&f["cases"][0]["initial"].to_string()).unwrap();
    let before = result.to_json().unwrap();
    structure::enrich_native(d.path(), &mut result, 10000., catalog(), Default::default()).unwrap();
    let actual = result.to_json().unwrap();
    assert_eq!(
        actual["candidates"][0]["confidence"],
        before["candidates"][0]["confidence"]
    );
    assert_eq!(actual["status"], before["status"]);
    assert!(
        !actual["candidates"][0]["structure"]["evidence"]["calls"]["sites"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert!(actual["responsibility_map"].is_object());
    assert_eq!(actual["candidates"][0]["structure"]["scope"], ".");
}
#[test]
fn invalid_structural_timeout_is_rejected_before_acquiring_sources() {
    let d = tempfile::tempdir().unwrap();
    let mut result: WhoReport =
        serde_json::from_str(&fixture()["cases"][0]["initial"].to_string()).unwrap();
    assert!(
        structure::enrich_native(d.path(), &mut result, 0., catalog(), Default::default()).is_err()
    );
    assert!(!d.path().join(".ken").exists());
}
