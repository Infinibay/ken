use ken_responsibility::{Candidate, CurrentSources, IndexedCandidate, NativeSources};
use serde_json::{Value, json};
use std::{path::PathBuf, sync::Arc};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/responsibility-domain.json")).unwrap()
}
fn hex(value: &str) -> Vec<u8> {
    (0..value.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&value[i..i + 2], 16).unwrap())
        .collect()
}
fn catalog() -> Arc<ken_syntax::GrammarCatalog> {
    Arc::new(
        ken_syntax::GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    )
}
fn row(value: &Value) -> IndexedCandidate {
    let mut value = value.clone();
    value["content_hash"] = json!(hex(value["content_hash"].as_str().unwrap()));
    serde_json::from_str(&value.to_string()).unwrap()
}
#[test]
fn current_source_facts_and_snapshot_previews_match_original_owners() {
    let d = tempfile::tempdir().unwrap();
    let f = fixture();
    for case in f["sources"].as_array().unwrap() {
        std::fs::write(
            d.path().join(case["path"].as_str().unwrap()),
            hex(case["bytes"].as_str().unwrap()),
        )
        .unwrap();
    }
    let mut sources = NativeSources::new(d.path(), catalog()).unwrap();
    for case in f["sources"].as_array().unwrap() {
        for expected in case["resolved"].as_array().unwrap() {
            let symbol = sources.resolve(&row(&expected["row"])).unwrap();
            assert_eq!(serde_json::to_value(symbol).unwrap(), expected["symbol"]);
            let candidate: Candidate =
                serde_json::from_str(&expected["candidate"].to_string()).unwrap();
            assert_eq!(
                serde_json::to_value(sources.preview(&candidate).unwrap()).unwrap(),
                expected["preview"]
            );
        }
    }
}
#[test]
fn decoder_obeys_original_pep263_bom_and_invalid_source_contract() {
    for case in fixture()["decoding"].as_array().unwrap() {
        let result = ken_text::source::decode_python(&hex(case["bytes"].as_str().unwrap()));
        if let Some(text) = case["result"]["text"].as_str() {
            assert_eq!(result.unwrap(), text, "{}", case["id"]);
        } else {
            assert!(result.is_err(), "{}", case["id"]);
        }
    }
}
#[test]
fn snapshot_cache_is_confined_bounded_and_does_not_refresh_quotes_mid_request() {
    let d = tempfile::tempdir().unwrap();
    let f = fixture();
    let case = &f["sources"][1];
    let path = case["path"].as_str().unwrap();
    let bytes = hex(case["bytes"].as_str().unwrap());
    std::fs::write(d.path().join(path), &bytes).unwrap();
    let row = row(&case["resolved"][0]["row"]);
    let mut sources = NativeSources::new(d.path(), catalog()).unwrap();
    let old = sources.resolve(&row).unwrap();
    std::fs::write(d.path().join(path), "removed=1\n").unwrap();
    assert_eq!(
        serde_json::to_value(sources.resolve(&row).unwrap()).unwrap(),
        serde_json::to_value(old).unwrap()
    );
    let mut fresh = NativeSources::new(d.path(), catalog()).unwrap();
    assert!(fresh.resolve(&row).is_err());
    let mut fresh = NativeSources::new(d.path(), catalog()).unwrap();
    for index in 0..25 {
        let path = format!("source{index}.py");
        std::fs::write(d.path().join(&path), &bytes).unwrap();
        let mut current = row.clone();
        current.path = path;
        if index < 24 {
            fresh.resolve(&current).unwrap();
        } else {
            assert!(
                fresh
                    .resolve(&current)
                    .unwrap_err()
                    .to_string()
                    .contains("budget")
            );
        }
    }
}
#[cfg(unix)]
#[test]
fn external_source_symlinks_and_oversized_sources_cannot_supply_positive_evidence() {
    let d = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let f = fixture();
    let case = &f["sources"][1];
    let row = row(&case["resolved"][0]["row"]);
    std::fs::write(
        outside.path().join("secret.py"),
        hex(case["bytes"].as_str().unwrap()),
    )
    .unwrap();
    std::os::unix::fs::symlink(outside.path().join("secret.py"), d.path().join(&row.path)).unwrap();
    let mut sources = NativeSources::new(d.path(), catalog()).unwrap();
    assert!(sources.resolve(&row).is_err());
    std::fs::remove_file(d.path().join(&row.path)).unwrap();
    std::fs::write(d.path().join(&row.path), vec![b' '; 2 * 1024 * 1024 + 1]).unwrap();
    assert!(
        sources
            .resolve(&row)
            .unwrap_err()
            .to_string()
            .contains("2 MiB")
    );
}
