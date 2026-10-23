//! Actual native grammar trees, resource integrity and ownership boundaries.
use ken_syntax::{GrammarCatalog, Language};
use serde_json::Value;
use std::{fs, path::PathBuf, sync::Arc};

fn manifest() -> PathBuf {
    std::env::var_os("KEN_GRAMMAR_MANIFEST")
        .map(PathBuf::from)
        .expect("prepared native grammar manifest is required")
}
fn reference() -> Value {
    serde_json::from_str(include_str!("fixtures/reference.json")).unwrap()
}
fn bytes(text: &str) -> Vec<u8> {
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn all_twenty_grammars_preserve_complete_original_syntax_shapes() {
    let catalog = GrammarCatalog::prepared(&manifest()).unwrap();
    let original = reference();
    for case in original["cases"].as_array().unwrap() {
        let request = &case["input"];
        let language: Language = serde_json::from_value(request["language"].clone()).unwrap();
        let source = bytes(request["source_hex"].as_str().unwrap());
        let tree = catalog
            .syntax(language, &source, request["hint"].as_str().unwrap())
            .unwrap();
        assert_eq!(
            serde_json::to_value(tree.snapshot()).unwrap(),
            case["syntax"],
            "case={} grammar={}",
            case["id"],
            case["grammar"]
        );
    }
}

#[test]
fn dynamic_tree_survives_catalog_drop_and_concurrent_callers_are_independent() {
    let catalog = Arc::new(GrammarCatalog::prepared(&manifest()).unwrap());
    let held = catalog
        .syntax(
            Language::Cpp,
            b"class Reader { int read() { return 1; } };",
            "api.hpp",
        )
        .unwrap();
    let threads: Vec<_> = (0..8)
        .map(|i| {
            let catalog = Arc::clone(&catalog);
            std::thread::spawn(move || {
                let text = format!("int read_{i}() {{ return {i}; }}");
                let tree = catalog
                    .syntax(Language::Cpp, text.as_bytes(), "api.cpp")
                    .unwrap();
                assert_eq!(tree.root().kind(), "translation_unit");
                assert!(tree.snapshot().len() > 8);
            })
        })
        .collect();
    for thread in threads {
        thread.join().unwrap();
    }
    drop(catalog);
    assert_eq!(held.root().kind(), "translation_unit");
    assert!(held.snapshot().len() > 12);
}

fn prepared_copy() -> (tempfile::TempDir, PathBuf, Value) {
    let original = manifest();
    let folder = tempfile::tempdir().unwrap();
    let data: Value = serde_json::from_slice(&fs::read(&original).unwrap()).unwrap();
    for row in data["libraries"].as_array().unwrap() {
        let name = row["file"].as_str().unwrap();
        fs::copy(
            original.parent().unwrap().join(name),
            folder.path().join(name),
        )
        .unwrap();
    }
    let path = folder.path().join("manifest.json");
    fs::copy(original, &path).unwrap();
    (folder, path, data)
}

#[test]
fn corrupt_or_missing_optional_grammar_only_fails_its_own_consumer() {
    for missing in [false, true] {
        let (folder, path, data) = prepared_copy();
        let row = data["libraries"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["language"] == "cpp")
            .unwrap();
        let library = folder.path().join(row["file"].as_str().unwrap());
        if missing {
            fs::remove_file(library).unwrap();
        } else {
            fs::write(library, b"altered native module").unwrap();
        }
        let catalog = GrammarCatalog::prepared(&path).unwrap();
        assert!(
            catalog
                .syntax(Language::Cpp, b"int read();", "api.cpp")
                .err()
                .unwrap()
                .to_string()
                .contains("cpp")
        );
        assert_eq!(
            catalog
                .syntax(Language::Python, b"def read(): pass", "api.py")
                .unwrap()
                .root()
                .kind(),
            "module"
        );
        assert_eq!(
            catalog
                .syntax(Language::C, b"int read(void);", "api.c")
                .unwrap()
                .root()
                .kind(),
            "translation_unit"
        );
    }
}

#[test]
fn unsafe_duplicate_or_wrong_platform_manifest_is_rejected() {
    let (_folder, path, original) = prepared_copy();
    let mut variants = vec![];
    let mut wrong = original.clone();
    wrong["platform"] = "unsupported-platform".into();
    variants.push(wrong);
    let mut wrong = original.clone();
    wrong["libraries"][0]["file"] = "../outside.so".into();
    variants.push(wrong);
    let mut wrong = original.clone();
    wrong["libraries"][0]["file"] = "/outside.so".into();
    variants.push(wrong);
    let mut wrong = original.clone();
    let repeated = wrong["libraries"][0].clone();
    wrong["libraries"].as_array_mut().unwrap().push(repeated);
    variants.push(wrong);
    let mut wrong = original;
    wrong["libraries"][0]["sha256"] = "0".repeat(64).into();
    variants.push(wrong);
    for wrong in variants {
        fs::write(&path, serde_json::to_vec(&wrong).unwrap()).unwrap();
        assert!(GrammarCatalog::prepared(&path).is_err());
    }
}
