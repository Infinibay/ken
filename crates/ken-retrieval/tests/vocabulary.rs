use ken_retrieval::{LexicalCounter, TokenCounter, vocabulary::*};
use serde::Deserialize;
use std::collections::BTreeSet;
#[derive(Deserialize)]
struct Fixture {
    vocabulary: Vec<Case>,
}
#[derive(Deserialize)]
struct Input {
    text: String,
    extra_stopwords: BTreeSet<String>,
}
#[derive(Deserialize)]
struct Terms {
    limit: Option<usize>,
    result: Vec<String>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    code_tokens: Vec<String>,
    terms: Vec<Terms>,
    name_tokens: BTreeSet<String>,
    camel: Vec<String>,
    lexical_count: usize,
}
#[test]
fn vocabulary_matches_original() {
    let fixture: Fixture =
        serde_json::from_str(include_str!("fixtures/source-reference.json")).unwrap();
    assert_eq!(fixture.vocabulary.len(), 195);
    for c in fixture.vocabulary {
        assert_eq!(split_camel(&c.input.text), c.camel, "{} camel", c.id);
        assert_eq!(
            name_tokens(&c.input.text, &c.input.extra_stopwords),
            c.name_tokens,
            "{} names",
            c.id
        );
        assert_eq!(code_tokens(&c.input.text), c.code_tokens, "{} code", c.id);
        assert_eq!(
            LexicalCounter.count(&c.input.text).unwrap(),
            c.lexical_count,
            "{} count",
            c.id
        );
        for t in c.terms {
            assert_eq!(
                code_terms(&c.input.text, t.limit),
                t.result,
                "{} terms {:?}",
                c.id,
                t.limit
            );
        }
    }
}
