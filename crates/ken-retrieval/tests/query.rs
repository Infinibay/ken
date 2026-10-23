use ken_retrieval::{
    Span,
    query::{SearchOptions, SearchRequest, merge_spans},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::value::RawValue;
#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    kind: String,
    input: Box<RawValue>,
    result: Option<Box<RawValue>>,
    error: Option<Error>,
}
#[derive(Deserialize)]
struct Error {
    message: String,
}
fn fixture() -> Fixture {
    serde_json::from_str(include_str!("fixtures/kernel-reference.json")).unwrap()
}
#[test]
fn validated_search_requests_match_original() {
    let mut count = 0;
    for case in fixture().cases.into_iter().filter(|c| c.kind == "request") {
        count += 1;
        let actual = serde_json::from_str::<SearchRequest>(case.input.get());
        if let Some(error) = case.error {
            assert!(actual.unwrap_err().to_string().contains(&error.message));
        } else {
            let expected: SearchRequest = serde_json::from_str(case.result.unwrap().get()).unwrap();
            assert_eq!(actual.unwrap(), expected);
        }
    }
    assert_eq!(count, 41);
    let defaults = SearchRequest::new("find code").unwrap();
    assert_eq!(defaults.target(), "symbol");
    assert_eq!(defaults.purpose(), "auto");
    assert_eq!(defaults.limit(), 10);
    assert_eq!(defaults.max_chars(), 12000);
    assert!(!defaults.explain());
    assert_eq!(defaults.piece_kind(), None);
    assert!(
        SearchRequest::try_from(SearchOptions {
            query: "query".into(),
            limit: 0,
            ..Default::default()
        })
        .is_err()
    );
}
#[test]
fn inclusive_source_regions_match_original() {
    let mut count = 0;
    for case in fixture().cases.into_iter().filter(|c| c.kind == "spans") {
        count += 1;
        let raw: Vec<[usize; 2]> = serde_json::from_str(case.input.get()).unwrap();
        let input = raw
            .into_iter()
            .map(|p| Span::new(p[0], p[1]))
            .collect::<ken_retrieval::Result<Vec<_>>>();
        if case.error.is_some() {
            assert!(input.is_err());
        } else {
            let expected: Vec<Span> = serde_json::from_str(case.result.unwrap().get()).unwrap();
            assert_eq!(merge_spans(&input.unwrap()), expected);
        }
    }
    assert_eq!(count, 23);
    assert_eq!(
        merge_spans(&[Span::new(1, usize::MAX).unwrap(), Span::new(4, 5).unwrap()]),
        vec![Span::new(1, usize::MAX).unwrap()]
    );
}
#[test]
fn json_query_pairs_and_lone_surrogates_preserve_python_text() {
    let pair: SearchRequest = serde_json::from_str(r#"{"query":"\ud801\udc00"}"#).unwrap();
    assert_eq!(pair.query().codepoints(), &[0x10400]);
    let lone: SearchRequest = serde_json::from_str(r#"{"query":"x\ud800y"}"#).unwrap();
    assert_eq!(lone.query().codepoints(), &[120, 0xd800, 121]);
    assert_eq!(
        SearchRequest::new(PythonText::from_codepoints(vec![0xd800]).unwrap())
            .unwrap()
            .query()
            .codepoints(),
        &[0xd800]
    );
    assert!(serde_json::from_str::<SearchRequest>(r#"{"query":"x","expected":{}}"#).is_err());
}
