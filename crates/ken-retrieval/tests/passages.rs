use ken_retrieval::{LexicalCounter, Passage, PassagePolicy, Span, extract_passages};
use ken_syntax::ParsedFile;
use serde::Deserialize;
#[derive(Deserialize)]
struct Fixture {
    passages: Vec<Case>,
}
#[derive(Deserialize)]
struct Input {
    source_hex: String,
    parsed: ParsedFile,
    path: String,
    language: String,
    max_tokens: usize,
    tokenizer_version: String,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    result: Vec<Passage>,
}
#[test]
fn physical_passages_match_original() {
    let fixture: Fixture =
        serde_json::from_str(include_str!("fixtures/source-reference.json")).unwrap();
    assert_eq!(fixture.passages.len(), 496);
    for c in fixture.passages {
        let i = c.input;
        let source: Vec<u8> = (0..i.source_hex.len())
            .step_by(2)
            .map(|j| u8::from_str_radix(&i.source_hex[j..j + 2], 16).unwrap())
            .collect();
        let policy = PassagePolicy::new(i.max_tokens, i.tokenizer_version).unwrap();
        assert_eq!(
            extract_passages(
                &source,
                &i.parsed,
                &i.path,
                &i.language,
                &policy,
                &LexicalCounter
            )
            .unwrap(),
            c.result,
            "{} {}",
            c.id,
            i.path
        );
    }
}
#[test]
fn invalid_spans_and_budgets_are_rejected() {
    assert!(Span::new(0, 1).is_err());
    assert!(Span::new(2, 1).is_err());
    assert!(serde_json::from_str::<Span>(r#"{"start_line":0,"end_line":1}"#).is_err());
    assert!(PassagePolicy::new(0, "code-lexical-v1").is_err());
}
