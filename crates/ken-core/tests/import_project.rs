//! Real config acquisition must preserve the independently observed edge results.
use ken_core::imports::{ImportCatalog, ImportError, ImportRequest, Resolution};
use serde_json::Value;
use std::fs;

#[test]
fn project_acquisition_matches_all_original_inputs_and_config_failures() {
    for corpus in [
        include_str!("fixtures/import-reference.json"),
        include_str!("fixtures/import-alias-edges.json"),
        include_str!("fixtures/import-alias-surrogates.json"),
        include_str!("fixtures/import-language-edges.json"),
    ] {
        let reference: Value = serde_json::from_str(corpus).unwrap();
        for row in reference["cases"].as_array().unwrap() {
            let root = tempfile::tempdir().unwrap();
            if let Some(configs) = row["input"]["configs"].as_object() {
                for (name, value) in configs {
                    let path = root.path().join(name);
                    fs::create_dir_all(path.parent().unwrap()).unwrap();
                    let hex = value.as_str().unwrap();
                    let bytes: Vec<_> = (0..hex.len())
                        .step_by(2)
                        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
                        .collect();
                    fs::write(path, bytes).unwrap();
                }
            }
            let files = serde_json::from_value(row["input"]["files"].clone()).unwrap();
            let catalog = ImportCatalog::from_project(
                (!row["input"]["configs"].is_null()).then_some(root.path()),
                files,
            );
            if row.get("error").is_some() {
                assert!(matches!(catalog, Err(ImportError::Config { .. })));
                continue;
            }
            let catalog = catalog.unwrap();
            let requests: Vec<ImportRequest> =
                serde_json::from_value(row["input"]["imports"].clone()).unwrap();
            for (request, expected) in requests.iter().zip(row["results"].as_array().unwrap()) {
                assert_eq!(
                    serde_json::to_value(catalog.resolve(request).unwrap()).unwrap(),
                    *expected,
                    "case={} request={request:?}",
                    row["id"]
                );
            }
        }
    }
}
fn request(module: &str, language: &str) -> ImportRequest {
    ImportRequest {
        module: module.into(),
        source_path: "main.ts".into(),
        language: Some(language.into()),
    }
}

#[test]
fn inherited_unindexed_config_is_reloaded_but_unindexed_package_is_ignored() {
    let root = tempfile::tempdir().unwrap();
    fs::write(root.path().join("tsconfig.json"), r#"{"extends":"./base"}"#).unwrap();
    fs::write(
        root.path().join("base.json"),
        r#"{"compilerOptions":{"paths":{"@value":["one"]}}}"#,
    )
    .unwrap();
    fs::write(root.path().join("package.json"), r#"{"name":"@hidden"}"#).unwrap();
    let files = vec![
        "main.ts".into(),
        "tsconfig.json".into(),
        "one.ts".into(),
        "two.ts".into(),
        "index.ts".into(),
    ];
    let first = ImportCatalog::from_project(Some(root.path()), files.clone()).unwrap();
    assert_eq!(
        first
            .resolve(&request("@value", "typescript"))
            .unwrap()
            .target
            .as_deref(),
        Some("one.ts")
    );
    assert_eq!(
        first
            .resolve(&request("@hidden", "typescript"))
            .unwrap()
            .resolution,
        Resolution::External
    );
    fs::write(
        root.path().join("base.json"),
        r#"{"compilerOptions":{"paths":{"@value":["two"]}}}"#,
    )
    .unwrap();
    let second = ImportCatalog::from_project(Some(root.path()), files).unwrap();
    assert_eq!(
        second
            .resolve(&request("@value", "typescript"))
            .unwrap()
            .target
            .as_deref(),
        Some("two.ts")
    );
    assert_eq!(
        first
            .resolve(&request("@value", "typescript"))
            .unwrap()
            .target
            .as_deref(),
        Some("one.ts")
    );
}

#[test]
fn jsonc_replaces_invalid_utf8_while_composer_strict_decoding_ignores_it() {
    let root = tempfile::tempdir().unwrap();
    fs::write(
        root.path().join("tsconfig.json"),
        b"{\"compilerOptions\":{\"paths\":{\"@value\":[\"one\"]}},\"unused\":\"\xff\"}",
    )
    .unwrap();
    fs::write(
        root.path().join("composer.json"),
        b"{\"autoload\":{\"psr-4\":{\"App\\\\\":\"one\"}},\"unused\":\"\xff\"}",
    )
    .unwrap();
    let files = vec![
        "main.ts".into(),
        "tsconfig.json".into(),
        "composer.json".into(),
        "one.ts".into(),
        "one/Value.php".into(),
        "two/Value.php".into(),
    ];
    let catalog = ImportCatalog::from_project(Some(root.path()), files).unwrap();
    assert_eq!(
        catalog
            .resolve(&request("@value", "typescript"))
            .unwrap()
            .target
            .as_deref(),
        Some("one.ts")
    );
    let php = catalog.resolve(&request("App\\Value", "php")).unwrap();
    assert_eq!(php.target, None);
    assert_eq!(php.resolution, Resolution::Unresolved);
}

#[test]
fn absent_root_missing_files_and_unreadable_directory_configs_are_tolerated() {
    let root = tempfile::tempdir().unwrap();
    fs::create_dir(root.path().join("tsconfig.json")).unwrap();
    let files = vec![
        "main.ts".into(),
        "tsconfig.json".into(),
        "missing/package.json".into(),
        "utility.py".into(),
    ];
    for project in [
        Some(root.path()),
        Some(root.path().join("missing-root").as_path()),
        None,
    ] {
        let catalog = ImportCatalog::from_project(project, files.clone()).unwrap();
        assert_eq!(
            catalog
                .resolve(&request("utility", "python"))
                .unwrap()
                .target
                .as_deref(),
            Some("utility.py")
        );
        assert_eq!(
            catalog
                .resolve(&request("@missing", "typescript"))
                .unwrap()
                .resolution,
            Resolution::External
        );
    }
}
