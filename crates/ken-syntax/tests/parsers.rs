//! Compare complete public results to independently captured original values.
use ken_syntax::{GrammarCatalog, Language, ParserRegistry};
use serde_json::Value;
use std::path::PathBuf;

fn original(language: &str, corpus: &str, minimum: usize) {
    let path =
        PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared grammar manifest"));
    let parsers = ParserRegistry::new(GrammarCatalog::prepared(&path).unwrap());
    let reference: Value = serde_json::from_str(corpus).unwrap();
    let mut count = 0;
    for case in reference["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["input"]["language"] == language)
    {
        let input = &case["input"];
        let text = input["source_hex"].as_str().unwrap();
        let bytes: Vec<_> = (0..text.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
            .collect();
        let language: Language = serde_json::from_value(input["language"].clone()).unwrap();
        let actual = parsers
            .parse(language, &bytes, input["hint"].as_str().unwrap())
            .unwrap();
        assert_eq!(
            serde_json::to_value(actual).unwrap(),
            case["parsed"],
            "case={} input={}",
            case["id"],
            String::from_utf8_lossy(&bytes)
        );
        count += 1;
    }
    assert!(count >= minimum, "language corpus missing");
}

#[test]
fn python_complete_outline_scopes_imports_and_documentation_match_original() {
    original("python", include_str!("fixtures/reference.json"), 5);
}
#[test]
fn rust_complete_outline_scopes_imports_and_documentation_match_original() {
    original("rust", include_str!("fixtures/reference.json"), 5);
}

#[test]
fn python_full_literal_forms_match_original() {
    original("python", include_str!("fixtures/parser-edges.json"), 18);
}
#[test]
fn rust_crlf_documentation_matches_original() {
    original("rust", include_str!("fixtures/parser-edges.json"), 1);
}
