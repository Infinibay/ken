//! Caller-level original structural-target comparisons, including ambiguities.
use ken_core::imports::{ImportCatalog, ImportError, ImportRequest};
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

#[test]
fn original_javascript_aliases_preserve_targets_classification_and_config_failures() {
    compare_javascript(include_str!("fixtures/import-reference.json"), 25);
}
#[test]
fn original_alias_workspace_order_duplicates_and_inherited_bases_match() {
    compare_javascript(include_str!("fixtures/import-alias-edges.json"), 10);
}
#[test]
fn original_non_scalar_alias_targets_keep_internal_shape() {
    compare_javascript(include_str!("fixtures/import-alias-surrogates.json"), 2);
}
fn compare_javascript(corpus: &str, minimum: usize) {
    let reference: Value = serde_json::from_str(corpus).unwrap();
    let mut queries = 0;
    for row in reference["cases"].as_array().unwrap() {
        let requests: Vec<ImportRequest> =
            serde_json::from_value(row["input"]["imports"].clone()).unwrap();
        if !requests
            .iter()
            .any(|r| matches!(r.language.as_deref(), Some("typescript" | "javascript")))
        {
            continue;
        }
        let files = serde_json::from_value(row["input"]["files"].clone()).unwrap();
        let configs = row["input"]["configs"].as_object().map(|cfg| {
            cfg.iter()
                .map(|(name, value)| {
                    let hex = value.as_str().unwrap();
                    let bytes = (0..hex.len())
                        .step_by(2)
                        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
                        .collect();
                    (name.clone(), bytes)
                })
                .collect()
        });
        let catalog = ImportCatalog::from_inputs(files, configs);
        if row.get("error").is_some() {
            assert!(
                matches!(catalog, Err(ImportError::Config { .. })),
                "original wrong config shape must fail"
            );
            continue;
        }
        let catalog = catalog.unwrap();
        for (request, expected) in requests.iter().zip(row["results"].as_array().unwrap()) {
            if !matches!(
                request.language.as_deref(),
                Some("typescript" | "javascript")
            ) {
                continue;
            }
            let actual = catalog.resolve(request).unwrap();
            assert_eq!(
                serde_json::to_value(actual).unwrap(),
                *expected,
                "case={} request={request:?}",
                row["id"]
            );
            queries += 1;
        }
    }
    assert!(queries >= minimum, "lost JS/TS case inventory");
}
