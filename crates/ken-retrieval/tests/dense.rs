use ken_retrieval::{Passage, dense::DenseView, embedding_store::VectorView, query::Candidate};
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
    passages: Vec<(i64, Passage)>,
    ids: Vec<i64>,
    matrix: Vec<Vec<f32>>,
    query: Vec<Value>,
    view: String,
    limit: isize,
}
fn fixture() -> Fixture {
    serde_json::from_str(include_str!("fixtures/kernel-reference.json")).unwrap()
}
#[test]
fn cancellation_preserves_owner_cutoff_and_same_owner_evidence_order() {
    let case = fixture()
        .cases
        .into_iter()
        .find(|c| c.kind == "dense")
        .unwrap();
    let input: Input = serde_json::from_str(case.input.get()).unwrap();
    let first = input.passages[0].1.clone();
    let mut second = first.clone();
    second.entity.qualname = Some("second".into());
    second.span = ken_retrieval::Span::new(10, 12).unwrap();
    let e = 2f32.powi(-26);
    let rows = vec![
        vec![0.5, e, -0.5, e, 0.5, 0., -0.5, 0.],
        vec![e, 0., 0., -0.5, 0.5, 0.5, -0.5, e],
    ];
    for same_owner in [false, true] {
        let mut other = second.clone();
        if same_owner {
            other.entity = first.entity.clone();
        }
        let view = DenseView::new(
            vec![(1, first.clone()), (2, other)],
            VectorView {
                ids: vec![1, 2],
                matrix: rows.clone(),
                model_revision: "provided-input-matrix".into(),
            },
        )
        .unwrap();
        let found = view.search(&[1.; 8], "identity", 1).unwrap();
        assert_eq!(found[0].entity, first.entity, "exact owner cutoff");
        assert_eq!(
            found[0].passages[0].span, first.span,
            "exact evidence order"
        );
        if same_owner {
            assert_eq!(found[0].passages[1].span, second.span);
        }
    }
}
#[test]
fn native_math_dispatch_and_runtime_boundaries_are_verified() {
    let case = fixture()
        .cases
        .into_iter()
        .find(|c| c.kind == "dense")
        .unwrap();
    let input: Input = serde_json::from_str(case.input.get()).unwrap();
    let a = input.passages[0].1.clone();
    for rows in [vec![vec![1., 0.]], vec![vec![1.], vec![-1.]]] {
        let dimension = rows[0].len();
        let ids: Vec<_> = (1..=rows.len() as i64).collect();
        let view = DenseView::new(
            ids.iter().map(|id| (*id, a.clone())).collect(),
            VectorView {
                ids,
                matrix: rows,
                model_revision: "r".into(),
            },
        )
        .unwrap();
        let mut query = vec![0.; dimension];
        query[0] = 1.;
        assert_eq!(
            view.search(&query, "identity", 1).unwrap()[0].signals["cosine_identity"],
            1.
        );
    }
    #[cfg(target_os = "linux")]
    {
        let missing = tempfile::tempdir().unwrap();
        assert!(
            ken_retrieval::verify_dense_runtime(missing.path())
                .unwrap_err()
                .to_string()
                .contains("prepare dense BLAS")
        );
        std::fs::write(
            missing
                .path()
                .join("libgfortran-daac5196-038a5e3c.so.5.0.0"),
            b"changed ELF",
        )
        .unwrap();
        assert!(
            ken_retrieval::verify_dense_runtime(missing.path())
                .unwrap_err()
                .to_string()
                .contains("integrity differs")
        );
    }
}
fn vector(v: &[Value]) -> Vec<f32> {
    v.iter()
        .map(|x| match x.as_str() {
            Some("nan") => f32::NAN,
            Some("inf") => f32::INFINITY,
            _ => x.as_f64().unwrap() as f32,
        })
        .collect()
}
#[test]
fn grouped_dense_scores_and_order_match_original() {
    let mut count = 0;
    for c in fixture().cases.into_iter().filter(|c| c.kind == "dense") {
        count += 1;
        let i: Input = serde_json::from_str(c.input.get()).unwrap();
        let view = DenseView::new(
            i.passages,
            VectorView {
                ids: i.ids,
                matrix: i.matrix,
                model_revision: "provided-input-matrix".into(),
            },
        )
        .unwrap();
        let actual = view.search(&vector(&i.query), &i.view, i.limit);
        if let Some(error) = c.error {
            assert!(
                actual
                    .unwrap_err()
                    .to_string()
                    .contains(error["message"].as_str().unwrap())
            );
        } else {
            let expected: Vec<Candidate> = serde_json::from_str(c.result.unwrap().get()).unwrap();
            let mut actual = actual.unwrap();
            assert_eq!(actual.len(), expected.len());
            for (a, mut e) in actual.iter_mut().zip(expected) {
                assert_eq!(
                    a.signals.keys().collect::<Vec<_>>(),
                    e.signals.keys().collect::<Vec<_>>()
                );
                for (k, &v) in &a.signals {
                    assert!((v - e.signals[k]).abs() <= 1e-6 + 1e-6 * e.signals[k].abs())
                }
                a.signals.clear();
                e.signals.clear();
                assert_eq!(a.passages.len(), e.passages.len());
                for (ap, ep) in a.passages.iter_mut().zip(e.passages.iter_mut()) {
                    assert_eq!(
                        ap.signals.keys().collect::<Vec<_>>(),
                        ep.signals.keys().collect::<Vec<_>>()
                    );
                    for (k, &v) in &ap.signals {
                        assert!((v - ep.signals[k]).abs() <= 1e-6 + 1e-6 * ep.signals[k].abs())
                    }
                    ap.signals.clear();
                    ep.signals.clear();
                }
                assert_eq!(*a, e, "exact owner/evidence ordering and data");
            }
        }
    }
    assert_eq!(count, 14);
}
#[test]
fn dense_shapes_empty_views_and_overflow_queries_have_explicit_behavior() {
    let c = fixture()
        .cases
        .into_iter()
        .find(|c| c.kind == "dense")
        .unwrap();
    let i: Input = serde_json::from_str(c.input.get()).unwrap();
    let p = i.passages[0].1.clone();
    let owned = vec![(1, p.clone())];
    assert!(
        DenseView::new(
            owned.clone(),
            VectorView {
                ids: vec![1, 2],
                matrix: vec![vec![1., 0.]],
                model_revision: "r".into()
            }
        )
        .is_err()
    );
    assert!(
        DenseView::new(
            owned.clone(),
            VectorView {
                ids: vec![2],
                matrix: vec![vec![1., 0.]],
                model_revision: "r".into()
            }
        )
        .is_err()
    );
    assert!(
        DenseView::new(
            owned.clone(),
            VectorView {
                ids: vec![1, 1],
                matrix: vec![vec![1., 0.], vec![1.]],
                model_revision: "r".into()
            }
        )
        .is_err()
    );
    let empty = DenseView::new(
        vec![],
        VectorView {
            ids: vec![],
            matrix: vec![],
            model_revision: "r".into(),
        },
    )
    .unwrap();
    assert!(empty.search(&[], "identity", 1).is_err());
    assert!(empty.search(&[1.], "identity", 1).is_err());
    let view = DenseView::new(
        owned,
        VectorView {
            ids: vec![1],
            matrix: vec![vec![1., 0.]],
            model_revision: "r".into(),
        },
    )
    .unwrap();
    assert!(view.search(&[1., 0.], "identity", 0).unwrap().is_empty());
    assert!(
        view.search(&[1., 0.], "identity", isize::MIN)
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        view.search(&[f32::MAX, f32::MAX], "identity", 1).unwrap()[0].signals["cosine_identity"],
        0.,
        "preserve original F32 norm-overflow division"
    );
}
