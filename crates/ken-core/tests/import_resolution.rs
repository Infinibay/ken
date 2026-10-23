//! Caller-level original structural-target comparisons, including ambiguities.
use ken_core::imports::ImportCatalog;
use serde_json::Value;

#[test]
fn original_structural_phase_preserves_every_target_and_missing_result() {
    let reference: Value =
        serde_json::from_str(include_str!("fixtures/import-reference.json")).unwrap();
    let mut queries = 0;
    for row in reference["cases"].as_array().unwrap() {
        let files = serde_json::from_value(row["input"]["files"].clone()).unwrap();
        let catalog = ImportCatalog::from_inputs(files, None).unwrap();
        for (request, expected) in row["input"]["imports"]
            .as_array()
            .unwrap()
            .iter()
            .zip(row["structural_targets"].as_array().unwrap())
        {
            let target = catalog.structural_target(
                request["module"].as_str().unwrap(),
                request["source_path"].as_str(),
            );
            assert_eq!(
                serde_json::to_value(target).unwrap(),
                *expected,
                "case={} request={request}",
                row["id"]
            );
            queries += 1;
        }
    }
    assert!(queries >= 50, "lost original request inventory");
}

#[test]
fn structural_phase_supports_absent_source_and_quote_whitespace_rules() {
    let catalog =
        ImportCatalog::from_inputs(vec!["src/café.py".into(), "asset.json".into()], None).unwrap();
    assert_eq!(
        catalog.structural_target("\u{1c}'café'\u{1f}", None),
        Some("src/café.py".into())
    );
    assert_eq!(
        catalog.structural_target("./asset.json", Some("main.ts")),
        Some("asset.json".into())
    );
    assert_eq!(catalog.structural_target("   ", None), None);
    let ambiguous =
        ImportCatalog::from_inputs(vec!["a/item.py".into(), "b/item.py".into()], None).unwrap();
    assert_eq!(ambiguous.structural_target("item", None), None);
}
