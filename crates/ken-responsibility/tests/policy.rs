use ken_responsibility::{
    Evidence, Symbol, WhoReport, assessment, default_reasoners, reasoners, report,
};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/responsibility-domain.json")).unwrap()
}
fn from_value<T: DeserializeOwned>(v: &Value) -> T {
    serde_json::from_str(&v.to_string()).unwrap()
}
#[test]
fn original_term_normalization_and_confidence_policy_are_preserved() {
    let f = fixture();
    for c in f["terms"].as_array().unwrap() {
        assert_eq!(
            json!(reasoners::terms(c["input"].as_str().unwrap())),
            c["result"]
        );
    }
    for c in f["confidence"].as_array().unwrap() {
        let evidence: Vec<Evidence> = from_value(&c["evidence"]);
        assert_eq!(
            serde_json::to_value(reasoners::confidence(&evidence)).unwrap(),
            c["result"]
        );
    }
}
#[test]
fn alternative_formulations_preserve_denial_conditions_and_delegation() {
    let f = fixture();
    for c in f["policy"].as_array().unwrap() {
        let symbol: Symbol = from_value(&c["symbol"]);
        let forms: Vec<String> = from_value(&c["formulations"]);
        let similarities: Vec<f64> = from_value(&c["similarities"]);
        let actual =
            assessment::assess_symbol(&symbol, &forms, &similarities, &default_reasoners())
                .unwrap();
        assert_eq!(serde_json::to_value(actual).unwrap(), c["result"]);
    }
}
#[test]
fn compact_rendering_retains_original_ambiguity_and_relevant_caveats() {
    for c in fixture()["service"].as_array().unwrap() {
        let result: WhoReport = from_value(&c["result"]);
        assert_eq!(
            serde_json::to_value(report::render(&result, false)).unwrap(),
            c["compact"]
        );
        assert_eq!(
            serde_json::to_value(report::render(&result, true)).unwrap(),
            c["result"]
        );
    }
}
#[test]
fn custom_reasoner_contributions_use_the_same_conservative_confidence_owner() {
    struct Constraint;
    impl ken_responsibility::Reasoner for Constraint {
        fn assess(
            &self,
            _: &ken_responsibility::Inquiry,
            _: &Symbol,
        ) -> ken_responsibility::Result<Vec<Evidence>> {
            Ok(vec![Evidence {
                reasoner: "deployment_constraint".into(),
                direction: "against".into(),
                strength: 1.,
                explanation: "The required backend is unavailable.".into(),
                assumption: "".into(),
            }])
        }
    }
    let f = fixture();
    let symbol: Symbol = from_value(&f["policy"][0]["symbol"]);
    let mut providers = default_reasoners();
    providers.push(Box::new(Constraint));
    let candidate = assessment::assess_symbol(
        &symbol,
        &["Store reusable findings".into()],
        &[0.9],
        &providers,
    )
    .unwrap();
    let value = serde_json::to_value(candidate).unwrap();
    assert_eq!(value["status"], "counterevidence");
    assert_eq!(value["confidence"]["score"], 0.2);
}
