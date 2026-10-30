use flate2::read::GzDecoder;
use ken_contracts::checks::{
    Observation, Receipt, Store, judgment_observation, observation_report, query_report,
};
use ken_program::value::GraphValue;
use serde_json::{Value, json};
use sha2::Digest;
use std::io::Read;
fn fixture() -> Value {
    let bytes = include_bytes!("fixtures/checks-application-reference.json.gz");
    assert_eq!(bytes.len(), 1294);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "7d748b76552d155f95594ff03b846aa46b2eaaf1fcbfb53df17ecde4f0c3f84d"
    );
    let mut s = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut s).unwrap();
    serde_json::from_str(&s).unwrap()
}
fn canonical(s: &str) -> GraphValue {
    fn sort(v: &mut GraphValue) {
        match v {
            GraphValue::Dict(items) => {
                for (_, v) in items.iter_mut() {
                    sort(v);
                }
                items.sort_by(|a, b| a.0.codepoints().cmp(b.0.codepoints()));
            }
            GraphValue::List(items) => {
                for v in items {
                    sort(v)
                }
            }
            _ => (),
        }
    }
    let mut v = GraphValue::parse(&serde_json::value::RawValue::from_string(s.to_owned()).unwrap())
        .unwrap();
    sort(&mut v);
    v
}
#[test]
fn original_lossless_observations_keep_certainty_rows_and_compact_witnesses() {
    let f = fixture();
    for c in f["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| !c["name"].as_str().unwrap().starts_with("batch"))
    {
        let input = c["result_json"].as_str().unwrap();
        let observation = Observation::parse(input).unwrap();
        assert_eq!(observation.row_count(), Some(1));
        assert!(observation.to_json().is_err());
        assert_eq!(
            canonical(&serde_json::to_string(&observation).unwrap()),
            canonical(input)
        );
        assert_eq!(
            judgment_observation(&observation, "some_match"),
            c["some_match"]
        );
        assert_eq!(
            judgment_observation(&observation, "no_matches"),
            c["no_matches"]
        );
        let compact = query_report(&observation, false).unwrap();
        assert_eq!(
            canonical(compact.json()),
            canonical(c["compact_json"].as_str().unwrap())
        );
        let record = format!(
            r#"{{"rule":"app.lossless","description":"Opaque literal witness","path":"src","expectation":"some_match","status":{},"result":{input}}}"#,
            serde_json::to_string(c["some_match"].as_str().unwrap()).unwrap()
        );
        let record = serde_json::from_str(&record).unwrap();
        let report = observation_report(&record).unwrap();
        assert_eq!(
            canonical(report.json()),
            canonical(c["observation_json"].as_str().unwrap())
        );
    }
}
#[test]
fn legacy_v1_receipts_roundtrip_raw_results_and_remain_immutable() {
    let f = fixture();
    let raw = f["cases"][0]["result_json"].as_str().unwrap();
    let body = format!(
        r#"{{"version":1,"run_id":"legacy.lossless","created_at":"2026-10-30T15:00:00+00:00","scope":"project","selection":"src","status":"pass","checks":[{{"rule":"app.lossless","description":"Opaque literal witness","revision":"legacy-revision","path":"src","query":"declared query","libraries":{{}},"expectation":"some_match","status":"pass","engine":"controlled-engine/1","result":{raw}}}],"selection_evidence":{{}},"legacy_extension":{{"preserve":"yes"}}}}"#
    );
    let receipt: Receipt = serde_json::from_str(&body).unwrap();
    let root = tempfile::tempdir().unwrap();
    let store = Store::new(root.path()).unwrap();
    store.write_receipt(&receipt).unwrap();
    let read = store.read_receipt("legacy.lossless").unwrap();
    assert_eq!(
        canonical(&serde_json::to_string(&read).unwrap()),
        canonical(&body)
    );
    assert!(store.write_receipt(&receipt).is_err());
    assert_eq!(read.checks[0].result.row_count(), Some(1));
    assert_eq!(
        judgment_observation(&read.checks[0].result, "some_match"),
        "pass"
    );
}
#[test]
fn incomplete_or_missing_admission_never_certifies_an_opaque_payload() {
    for patch in [
        json!({"complete":false}),
        json!({"coverage_complete":false}),
        json!({"results_truncated":true}),
        json!({"unknown_candidates":1}),
        json!({"reason":"timeout"}),
    ] {
        for rows in [json!([]), json!([[1]])] {
            let mut result = json!({"complete":true,"coverage_complete":true,"results_truncated":false,"unknown_candidates":0,"reason":null,"rows":rows});
            result
                .as_object_mut()
                .unwrap()
                .extend(patch.as_object().unwrap().clone());
            let observation = Observation::parse(&result.to_string()).unwrap();
            assert_eq!(judgment_observation(&observation, "some_match"), "unknown");
            assert_eq!(judgment_observation(&observation, "no_matches"), "unknown");
        }
    }
    let missing =
        Observation::parse(r#"{"rows":[],"complete":true,"coverage_complete":true,"reason":null}"#)
            .unwrap();
    assert_eq!(judgment_observation(&missing, "no_matches"), "unknown");
}
