//! Annotation families retain complete nested syntax descriptors.
use ken_program::{TypeRef, parse_type, split_types};
use serde::Deserialize;
#[derive(Deserialize)]
struct Input {
    annotation: String,
    language: String,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    result: TypeRef,
}
#[derive(Deserialize)]
struct Corpus {
    types: Vec<Case>,
}
#[test]
fn all_original_nested_and_scalar_type_descriptors_match() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/type-reference.json")).unwrap();
    assert_eq!(corpus.types.len(), 204);
    for case in corpus.types {
        assert_eq!(
            parse_type(&case.input.annotation, &case.input.language),
            case.result,
            "{} {} {:?}",
            case.id,
            case.input.language,
            case.input.annotation
        );
    }
}
#[test]
fn delimiter_depth_and_python_unicode_word_classes_are_preserved() {
    assert_eq!(
        split_types("a,List<b,c>,(d,e),f", ','),
        ["a", "List<b,c>", "(d,e)", "f"]
    );
    assert_eq!(parse_type("π", "python").kind, "nominal");
    assert_eq!(parse_type("A\u{301}", "python").kind, "opaque");
    assert_eq!(parse_type("A\u{1c89}", "python").kind, "opaque");
}
