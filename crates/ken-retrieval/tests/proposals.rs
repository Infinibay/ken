use ken_retrieval::{Span, proposals::fuse_proposals, query::Candidate};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    kind: String,
    input: Box<RawValue>,
    result: Option<Box<RawValue>>,
    error: Option<Value>,
}
#[derive(Deserialize)]
struct Input {
    channels: Vec<(String, Vec<Candidate>)>,
    limit: usize,
    rrf_k: usize,
}
fn fixture() -> Fixture {
    serde_json::from_str(include_str!("fixtures/kernel-reference.json")).unwrap()
}
#[test]
fn owner_proposal_fusion_matches_original_without_mutating_inputs() {
    let mut count = 0;
    for case in fixture().cases.into_iter().filter(|c| c.kind == "fusion") {
        count += 1;
        let i: Input = serde_json::from_str(case.input.get()).unwrap();
        let before = i.channels.clone();
        let actual = fuse_proposals(&i.channels, i.limit, i.rrf_k);
        assert_eq!(i.channels, before);
        if let Some(error) = case.error {
            assert!(
                actual
                    .unwrap_err()
                    .to_string()
                    .contains(error["message"].as_str().unwrap())
            );
        } else {
            let expected: Vec<Candidate> =
                serde_json::from_str(case.result.unwrap().get()).unwrap();
            let mut actual = actual.unwrap();
            assert_eq!(actual.len(), expected.len());
            for (a, mut e) in actual.iter_mut().zip(expected) {
                assert_eq!(
                    a.signals.keys().collect::<Vec<_>>(),
                    e.signals.keys().collect::<Vec<_>>()
                );
                for (k, &v) in &a.signals {
                    assert!((v - e.signals[k]).abs() <= 1e-12 + 1e-12 * e.signals[k].abs())
                }
                a.signals.clear();
                e.signals.clear();
                assert_eq!(*a, e, "exact evidence and owner ordering");
            }
        }
    }
    assert_eq!(count, 70);
}
#[test]
fn repeated_owner_merges_spans_and_measurements_but_named_runs_are_unique() {
    let case = fixture()
        .cases
        .into_iter()
        .find(|c| c.kind == "fusion" && c.error.is_none())
        .unwrap();
    let i: Input = serde_json::from_str(case.input.get()).unwrap();
    let mut first = i.channels[0].1[0].clone();
    first.passages[0].entity_span = Span::new(1, 6).unwrap();
    let mut second = first.clone();
    second.passages[0].span = Span::new(4, 6).unwrap();
    first.owned_regions = vec![Span::new(1, 3).unwrap()];
    second.owned_regions = vec![Span::new(3, 6).unwrap()];
    second.signals.insert("cosine_behavior".into(), 0.9);
    second.passages[0]
        .signals
        .insert("cosine_behavior".into(), 0.9);
    let runs = vec![("code".into(), vec![first.clone(), second])];
    let result = fuse_proposals(&runs, 2, 60).unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].signals["rrf"], 1. / 61.);
    assert_eq!(result[0].signals["cosine_behavior"], 0.9);
    assert_eq!(result[0].passages.len(), 2);
    assert_eq!(result[0].owned_regions, vec![Span::new(1, 6).unwrap()]);
    let mut nonfinite = first.clone();
    nonfinite.signals.insert("diagnostic".into(), f64::NAN);
    let mut finite = first.clone();
    finite.signals.insert("diagnostic".into(), 2.);
    let measured = fuse_proposals(
        &[
            ("earlier".into(), vec![nonfinite]),
            ("later".into(), vec![finite]),
        ],
        2,
        60,
    )
    .unwrap();
    assert_eq!(
        measured[0].signals["diagnostic"], 2.,
        "max(new, prior) retains Python's unordered comparison behavior"
    );
    assert!(
        fuse_proposals(
            &[
                ("code".into(), vec![first.clone()]),
                ("code".into(), vec![first])
            ],
            2,
            60
        )
        .is_err()
    );
}
