pub mod feature_support;
use feature_support as f;
use ken_retrieval::evidence_features::{base_features, evidence_features};
#[test]
fn complete_owner_feature_names_values_and_model_calls_match_original() {
    for case in f::cases()
        .into_iter()
        .filter(|c| matches!(c.kind.as_str(), "base" | "evidence"))
    {
        let request = f::request(&case.input);
        let candidates: Vec<_> = case
            .input
            .candidates
            .iter()
            .map(|c| c.materialize())
            .collect();
        let encoder = f::Encoder::new(&case.input);
        let stems = f::Stems::new(&case.input);
        if case.kind == "base" {
            let want: Vec<std::collections::BTreeMap<String, f64>> =
                serde_json::from_str(case.result.as_ref().unwrap().get()).unwrap();
            for (c, want) in candidates.iter().zip(want) {
                let got = base_features(&request, c).unwrap();
                assert_eq!(
                    got.keys().collect::<Vec<_>>(),
                    want.keys().collect::<Vec<_>>()
                );
                for (k, v) in got {
                    f::close(v, want[&k], &format!("{}/{k}", case.id));
                }
            }
        } else {
            let descriptions = f::descriptions(&case.input);
            let got = evidence_features(
                &request,
                &candidates,
                &descriptions,
                &encoder,
                &stems,
                case.input.expanded.as_ref(),
            )
            .unwrap();
            assert_eq!(got.names.len(), 227);
            f::matrix(&got, case.result.as_ref().unwrap());
        }
        f::check_calls(&case, &encoder, &stems);
    }
}
#[test]
fn source_admission_rejects_incoherent_complete_owners_before_any_model_call() {
    for case in f::cases()
        .into_iter()
        .filter(|c| c.kind == "evidence_admission")
    {
        let request = f::request(&case.input);
        let candidates: Vec<_> = case
            .input
            .candidates
            .iter()
            .map(|c| c.materialize())
            .collect();
        let descriptions = f::descriptions(&case.input);
        let encoder = f::Encoder::new(&case.input);
        let stems = f::Stems::new(&case.input);
        assert!(
            evidence_features(&request, &candidates, &descriptions, &encoder, &stems, None)
                .is_err(),
            "{}",
            case.id
        );
        assert!(encoder.calls.borrow().is_empty());
        assert!(stems.calls.lock().unwrap().is_empty());
    }
    let case = f::cases()
        .into_iter()
        .find(|c| c.kind == "evidence")
        .unwrap();
    let request = f::request(&case.input);
    let mut candidates: Vec<_> = case
        .input
        .candidates
        .iter()
        .map(|c| c.materialize())
        .collect();
    candidates[1].passages[0].source_hash = "changed".into();
    let before = candidates.clone();
    let encoder = f::Encoder::new(&case.input);
    let stems = f::Stems::new(&case.input);
    assert!(
        evidence_features(
            &request,
            &candidates,
            &f::descriptions(&case.input),
            &encoder,
            &stems,
            None
        )
        .is_err()
    );
    assert_eq!(candidates, before);
    assert!(encoder.calls.borrow().is_empty());
    assert!(stems.calls.lock().unwrap().is_empty());
}
