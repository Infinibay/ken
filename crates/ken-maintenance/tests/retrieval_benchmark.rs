//! Frozen response scoring never invokes an encoder or a retrieval engine.
use ken_maintenance::retrieval_benchmark::{self as bench, *};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::PathBuf};
const SOURCE: &str = "def target():\n    return 1\n";
const HASH: &str = "e90074bde6f68906b18cd2dd68cec01eb01d6b35cfa5264896405a14cf650435";
fn case(i: usize) -> Value {
    json!({"id":i.to_string(),"repo_id":format!("repo{}",i/25),"repo_commit":"a".repeat(40),"query":format!("find behavior {i}"),"language":if i%25<15{"en"}else{"es"},"purpose":if i<210{"implementation"}else if i<255{"identity"}else{"usage"},"behavior_group":format!("behavior-{i}"),"answerable":true,"alternatives":[{"path":"target.py","source_hash":HASH,"entity":{"kind":"function","qualname":"target","owner":null,"definition_ordinal":0},"anchors":[{"start_line":2,"end_line":2}]}]})
}
fn answer(i: usize) -> Value {
    json!({"id":i.to_string(),"results":[{"path":"target.py","source_hash":HASH,"entity":{"kind":"function","qualname":"target","owner":null,"definition_ordinal":0},"evidence":[{"start_line":2,"end_line":2,"content":"    return 1"}]}]})
}
fn fixture() -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("target.py"), SOURCE).unwrap();
    root
}
fn roots(root: &std::path::Path, cases: &[Value]) -> BTreeMap<String, PathBuf> {
    cases
        .iter()
        .map(|c| (c["repo_id"].as_str().unwrap().into(), root.into()))
        .collect()
}
fn evaluate_here(cases: &[Value], answers: &[Value]) -> Value {
    let root = fixture();
    bench::evaluate(cases, answers, &roots(root.path(), cases)).unwrap()
}

#[test]
fn strict_top_one_needs_identity_faithful_current_source_and_all_anchors_together() {
    assert_eq!(
        evaluate_here(&[case(0)], &[answer(0)])["rows"][0]["reason"],
        "hit"
    );
    for (mutation, reason, identity) in [
        ("file_only", "wrong_identity", false),
        ("owner", "wrong_identity", false),
        ("anchor", "missing_anchor", true),
        ("stale", "invalid_evidence", true),
        ("invented", "invalid_evidence", true),
        ("ordinal", "wrong_identity", false),
    ] {
        let mut answer = answer(0);
        match mutation {
            "file_only" => answer["results"][0]["entity"] = Value::Null,
            "owner" => answer["results"][0]["entity"]["owner"] = json!("Wrong"),
            "ordinal" => answer["results"][0]["entity"]["definition_ordinal"] = json!(1),
            "anchor" => {
                answer["results"][0]["evidence"] =
                    json!([{"start_line":1,"end_line":1,"content":"def target():"}])
            }
            "stale" => answer["results"][0]["source_hash"] = json!("0".repeat(64)),
            _ => answer["results"][0]["evidence"][0]["content"] = json!("invented"),
        };
        let report = evaluate_here(&[case(0)], &[answer]);
        assert_eq!(report["rows"][0]["reason"], reason, "{mutation}");
        assert_eq!(report["rows"][0]["identity_hit"], identity, "{mutation}");
        assert_eq!(report["strict_top1"]["hits"], 0);
    }
    let mut gold = case(0);
    gold["alternatives"][0]["anchors"]
        .as_array_mut()
        .unwrap()
        .push(json!({"start_line":1,"end_line":1}));
    assert_eq!(
        evaluate_here(&[gold.clone()], &[answer(0)])["rows"][0]["reason"],
        "missing_anchor"
    );
    gold["alternatives"]
        .as_array_mut()
        .unwrap()
        .push(case(0)["alternatives"][0].clone());
    assert_eq!(
        evaluate_here(&[gold], &[answer(0)])["strict_top1"]["hits"],
        1
    );
}

#[test]
fn errors_empty_missing_and_wrong_first_results_remain_in_denominator() {
    let cases = (0..6).map(case).collect::<Vec<_>>();
    let mut wrong = answer(4);
    wrong["results"][0]["path"] = json!("wrong.py");
    wrong["results"]
        .as_array_mut()
        .unwrap()
        .push(answer(4)["results"][0].clone());
    let records = vec![
        answer(0),
        json!({"id":"1","error":"failed"}),
        json!({"id":"2","results":[]}),
        wrong,
        json!({"id":"5","results":[12]}),
    ];
    let report = evaluate_here(&cases, &records);
    assert_eq!(
        report["strict_top1"],
        json!({"hits":1,"total":6,"rate":1./6.})
    );
    assert_eq!(report["missing_response_ids"], json!(["3"]));
    assert_eq!(
        report["rows"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["reason"].as_str().unwrap())
            .collect::<Vec<_>>(),
        [
            "hit",
            "error",
            "empty",
            "missing_response",
            "wrong_identity",
            "invalid_results"
        ]
    );
    let mut negative = case(6);
    negative["answerable"] = json!(false);
    negative["alternatives"] = json!([]);
    let report = evaluate_here(&[negative], &[answer(6)]);
    assert_eq!(report["strict_top1"], json!({"hits":0,"total":0,"rate":0.}));
    assert_eq!(
        report["negatives"],
        json!([{"id":"6","returned_results":true}])
    );
}

#[test]
fn unicode_output_budget_excludes_identifier_and_duplicate_shown_lines_count_against_40() {
    let mut gold = case(0);
    gold["id"] = json!("x".repeat(13000));
    let mut response = answer(0);
    response["id"] = gold["id"].clone();
    response["warnings"] = json!(["optional context unavailable"]);
    assert_eq!(
        evaluate_here(&[gold.clone()], &[response.clone()])["rows"][0]["reason"],
        "hit"
    );
    response["explain"] = json!("🦀".repeat(3000));
    assert_eq!(
        evaluate_here(&[gold.clone()], &[response.clone()])["rows"][0]["reason"],
        "hit",
        "budget counts Unicode codepoints, not UTF8 bytes"
    );
    response["explain"] = json!("x".repeat(12001));
    assert_eq!(
        evaluate_here(&[gold], &[response])["rows"][0]["reason"],
        "output_budget"
    );
    let mut duplicate = answer(0);
    duplicate["results"][0]["evidence"] = json!(
        (0..41)
            .map(|_| json!({"start_line":2,"end_line":2,"content":"    return 1"}))
            .collect::<Vec<_>>()
    );
    assert_eq!(
        evaluate_here(&[case(0)], &[duplicate])["rows"][0]["reason"],
        "invalid_evidence"
    );
    let mut out = answer(0);
    out["results"][0]["evidence"][0]["end_line"] = json!(900);
    assert_eq!(
        evaluate_here(&[case(0)], &[out])["rows"][0]["reason"],
        "invalid_evidence"
    );
}

#[test]
fn gold_corruption_and_duplicate_or_unknown_records_are_input_errors_not_search_misses() {
    let root = fixture();
    let cases = vec![case(0)];
    let mapping = roots(root.path(), &cases);
    assert!(
        bench::evaluate(&cases, &[answer(0), answer(0)], &mapping)
            .unwrap_err()
            .to_string()
            .contains("duplicate")
    );
    assert!(
        bench::evaluate(&cases, &[answer(9)], &mapping)
            .unwrap_err()
            .to_string()
            .contains("unknown")
    );
    assert!(bench::evaluate(&[case(0), case(0)], &[], &mapping).is_err());
    std::fs::write(root.path().join("target.py"), "changed\n").unwrap();
    assert!(
        bench::evaluate(&cases, &[], &mapping)
            .unwrap_err()
            .to_string()
            .contains("reference snapshot mismatch")
    );
    let request = request_for_case(&case(0));
    assert_eq!(
        request,
        json!({"query":"find behavior 0","purpose":"auto","target":"symbol","limit":10,"max_chars":12000})
    );
}

#[test]
fn gate_is_90_percent_in_every_required_slice_and_macro_repo_cannot_be_hidden() {
    let cases = (0..300).map(case).collect::<Vec<_>>();
    let mut misses = (0..300)
        .filter(|i| i % 25 == 0 || i % 25 == 15)
        .collect::<std::collections::BTreeSet<_>>();
    misses.extend([26, 51, 76, 101, 226, 276]);
    let mut responses = (0..300)
        .map(|i| {
            if misses.contains(&i) {
                json!({"id":i.to_string(),"results":[]})
            } else {
                answer(i)
            }
        })
        .collect::<Vec<_>>();
    let report = evaluate_here(&cases, &responses);
    assert_eq!(report["strict_top1"]["hits"], 270);
    assert!(check_gate(&report, None).unwrap().is_empty());
    responses[201] = json!({"id":"201","results":[]});
    let report = evaluate_here(&cases, &responses);
    assert_eq!(report["strict_top1"]["hits"], 269);
    assert!(!check_gate(&report, None).unwrap().is_empty());
    for policy in [
        json!({"min_top1":0.89}),
        json!({"min_top1":true}),
        json!({"min_top1":"0.9"}),
        json!({"min_top1":1.01}),
    ] {
        assert!(check_gate(&report, Some(&policy)).is_err());
    }
    let mut responses = (0..300).map(answer).collect::<Vec<_>>();
    for i in (0..300).filter(|i| i % 25 >= 15).take(20) {
        responses[i]["results"] = json!([]);
    }
    let report = evaluate_here(&cases, &responses);
    assert!(report["strict_top1"]["rate"].as_f64().unwrap() > 0.9);
    assert!(
        check_gate(&report, None)
            .unwrap()
            .iter()
            .any(|s| s.contains("language:es"))
    );
}

#[test]
fn file_adapter_hashes_raw_dataset_and_only_gate_mode_applies_acceptance_quotas() {
    let root = fixture();
    let dataset = root.path().join("cases.jsonl");
    let responses = root.path().join("responses.jsonl");
    let mapping = root.path().join("roots.json");
    let gate = root.path().join("gate.json");
    let raw = format!("{}\n", case(0));
    std::fs::write(&dataset, &raw).unwrap();
    std::fs::write(&responses, format!("{}\n", answer(0))).unwrap();
    std::fs::write(
        &mapping,
        serde_json::to_vec(&roots(root.path(), &[case(0)])).unwrap(),
    )
    .unwrap();
    std::fs::write(&gate, "{\"min_top1\":0.90}").unwrap();
    let loaded = load_dataset(&dataset).unwrap();
    assert_eq!(loaded.cases.len(), 1);
    let (report, status) = evaluate_files(&dataset, &mapping, &responses, None).unwrap();
    assert_eq!(status, 0);
    assert_eq!(report["failures"], json!([]));
    assert_eq!(report["dataset_sha256"], loaded.sha256);
    let (report, status) = evaluate_files(&dataset, &mapping, &responses, Some(&gate)).unwrap();
    assert_eq!(status, 1);
    assert_eq!(report["strict_top1"]["hits"], 1);
    assert!(
        report["failures"]
            .as_array()
            .unwrap()
            .iter()
            .any(|f| f.as_str().unwrap().contains("300"))
    );
    std::fs::write(&dataset, format!("\n{raw}")).unwrap();
    assert_ne!(load_dataset(&dataset).unwrap().sha256, loaded.sha256);
    for path in [
        "../target.py",
        "./target.py",
        "x//target.py",
        "/target.py",
        "x\\target.py",
    ] {
        let mut invalid = case(0);
        invalid["alternatives"][0]["path"] = json!(path);
        assert!(validate_case(&invalid).is_err(), "{path}");
    }
}

#[test]
fn acceptance_quotas_partition_casefold_and_frozen_artifact_consumption_are_enforced() {
    let mut cases = (0..300).map(case).collect::<Vec<_>>();
    for i in 300..360 {
        let mut negative = case(i);
        negative["answerable"] = json!(false);
        negative["alternatives"] = json!([]);
        negative["repo_id"] = json!("repo0");
        cases.push(negative);
    }
    assert!(acceptance_failures(&cases).unwrap().is_empty());
    let dev = case(0);
    let mut reserve = case(1);
    assert!(
        validate_partitions(std::slice::from_ref(&dev), std::slice::from_ref(&reserve)).is_err()
    );
    reserve["repo_id"] = json!("other");
    reserve["behavior_group"] = json!("other");
    reserve["query"] = json!(" STRASSE  ");
    let mut dev = dev;
    dev["query"] = json!("straße");
    assert!(
        validate_partitions(&[dev], &[reserve])
            .unwrap_err()
            .to_string()
            .contains("query")
    );
    let root = fixture();
    let expected = BTreeMap::from([("target.py".into(), HASH.into())]);
    verify_files(root.path(), &expected).unwrap();
    std::fs::write(root.path().join("target.py"), "changed").unwrap();
    assert!(verify_files(root.path(), &expected).is_err());
    let registry = root.path().join("attempts.sqlite");
    claim_reserve(&registry, &"a".repeat(64), &"b".repeat(64), &"c".repeat(64)).unwrap();
    assert!(
        claim_reserve(&registry, &"a".repeat(64), &"d".repeat(64), &"c".repeat(64))
            .unwrap_err()
            .to_string()
            .contains("consumed")
    );
    assert!(claim_reserve(&registry, "bad", &"b".repeat(64), &"c".repeat(64)).is_err());
}
