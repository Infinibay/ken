use ken_retrieval::{
    EntityKey, Passage, PassageFields, PassagePolicy, Span,
    lexical::{Posting, bm25f_score, lexical_candidates, score_postings},
    query::SearchRequest,
    storage::{generation, replace_file_passages},
};
use ken_store::ProjectDatabase;
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use std::collections::BTreeMap;
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
struct Scalar {
    frequencies: BTreeMap<String, f64>,
    lengths: BTreeMap<String, f64>,
    averages: BTreeMap<String, f64>,
    document_frequency: i64,
    documents: i64,
    #[serde(default = "k1")]
    k1: f64,
    weights: Option<BTreeMap<String, f64>>,
}
fn k1() -> f64 {
    1.2
}
#[derive(Deserialize)]
struct Postings {
    rows: Vec<(i64, String, String, f64, f64)>,
    documents: i64,
    averages: BTreeMap<String, f64>,
}
fn fixture() -> Fixture {
    serde_json::from_str(include_str!("fixtures/kernel-reference.json")).unwrap()
}
fn close(a: f64, b: f64) {
    assert!(
        a.is_finite() && b.is_finite() && (a - b).abs() <= 1e-12 + 1e-12 * b.abs(),
        "{a} != {b}"
    );
}
#[test]
fn scalar_zero_divisors_report_original_arithmetic_failure() {
    for (field, lengths, averages, k1) in [
        ("identity", BTreeMap::new(), BTreeMap::new(), -1.),
        (
            "body",
            BTreeMap::from([("body".into(), -1.)]),
            BTreeMap::from([("body".into(), 3.)]),
            1.2,
        ),
    ] {
        let error = bm25f_score(
            &BTreeMap::from([(field.into(), 1.)]),
            &lengths,
            &averages,
            1,
            2,
            k1,
            None,
        )
        .unwrap_err();
        assert!(error.to_string().contains("float division by zero"));
    }
}
#[test]
fn scalar_and_shared_postings_match_original() {
    let mut counts = [0, 0];
    for c in fixture().cases {
        if c.kind == "bm25f" {
            counts[0] += 1;
            let i: Scalar = serde_json::from_str(c.input.get()).unwrap();
            let actual = bm25f_score(
                &i.frequencies,
                &i.lengths,
                &i.averages,
                i.document_frequency,
                i.documents,
                i.k1,
                i.weights.as_ref(),
            );
            if c.error.is_some() {
                assert!(actual.is_err())
            } else {
                close(
                    actual.unwrap(),
                    serde_json::from_str::<f64>(c.result.unwrap().get()).unwrap(),
                )
            }
        } else if c.kind == "postings" {
            counts[1] += 1;
            let i: Postings = serde_json::from_str(c.input.get()).unwrap();
            let rows: Vec<_> = i.rows.into_iter().map(Posting::from).collect();
            let actual = score_postings(&rows, i.documents, &i.averages).unwrap();
            let expected: BTreeMap<i64, BTreeMap<String, f64>> =
                serde_json::from_str(c.result.unwrap().get()).unwrap();
            assert_eq!(
                actual.keys().collect::<Vec<_>>(),
                expected.keys().collect::<Vec<_>>()
            );
            for (id, signals) in actual {
                assert_eq!(
                    signals.keys().collect::<Vec<_>>(),
                    expected[&id].keys().collect::<Vec<_>>()
                );
                for (k, v) in signals {
                    close(v, expected[&id][&k])
                }
            }
        }
    }
    assert_eq!(counts, [84, 60]);
}
fn db() -> (tempfile::TempDir, ProjectDatabase) {
    let root = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    db.connection()
        .execute(
            "INSERT INTO ci_files(path,content_hash,mtime,indexed_at)VALUES('auth.py',x'00',0,0)",
            [],
        )
        .unwrap();
    db.connection().execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end)VALUES(1,'function','release','release',1,7)",[]).unwrap();
    (root, db)
}
fn passages(body: &str) -> Vec<Passage> {
    (1..=7)
        .map(|n| Passage {
            entity: EntityKey {
                path: "auth.py".into(),
                kind: "function".into(),
                qualname: Some("release".into()),
                owner: None,
                definition_ordinal: 0,
            },
            span: Span::new(n, n).unwrap(),
            fields: PassageFields {
                identity: "function release".into(),
                signature: "def release():".into(),
                documentation: "".into(),
                body: format!("{body} line{n}").into(),
                path: "auth.py".into(),
            },
            source_hash: "a".repeat(64),
            entity_span: Span::new(1, 7).unwrap(),
            language: "python".into(),
            role: "definition".into(),
            split_reason: None,
            signals: BTreeMap::new(),
            implementation_start_line: Some(1),
        })
        .collect()
}
fn replace(db: &mut ProjectDatabase, values: &[Passage]) {
    let tx = db.immediate().unwrap();
    replace_file_passages(
        &tx,
        1,
        values,
        Some(&"a".repeat(64)),
        &PassagePolicy::default(),
    )
    .unwrap();
    tx.commit().unwrap()
}
#[test]
fn lexical_sql_observes_edits_deletes_and_owned_evidence_caps() {
    let (_root, mut db) = db();
    replace(&mut db, &passages("COOKIE_JAR_CONFLICT"));
    let request = SearchRequest::new("COOKIE_JAR_CONFLICT").unwrap();
    let results = lexical_candidates(db.connection(), &request, 100).unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].entity.qualname.as_deref(), Some("release"));
    assert_eq!(results[0].passages.len(), 4);
    assert!(results[0].signals["bm25f"] > 0.);
    assert_eq!(
        lexical_candidates(db.connection(), &request, -1)
            .unwrap()
            .len(),
        1
    );
    replace(&mut db, &passages("new current source"));
    assert!(
        lexical_candidates(db.connection(), &request, 100)
            .unwrap()
            .is_empty()
    );
    replace(&mut db, &passages("COOKIE_JAR_CONFLICT"));
    db.connection().execute("DELETE FROM ci_files", []).unwrap();
    assert!(
        lexical_candidates(db.connection(), &request, 100)
            .unwrap()
            .is_empty()
    );
}
#[test]
fn lexical_statistics_do_not_cross_databases_or_rolled_back_generations() {
    let (_a, mut a) = db();
    let (_b, mut b) = db();
    replace(&mut a, &passages("COOKIE_JAR_CONFLICT"));
    replace(&mut b, &passages("other source"));
    let q = SearchRequest::new("COOKIE_JAR_CONFLICT").unwrap();
    assert!(
        !lexical_candidates(a.connection(), &q, 100)
            .unwrap()
            .is_empty()
    );
    assert!(
        lexical_candidates(b.connection(), &q, 100)
            .unwrap()
            .is_empty()
    );
    let epoch = generation(a.connection()).unwrap();
    let tx = a.immediate().unwrap();
    replace_file_passages(
        &tx,
        1,
        &passages("temporary different words"),
        Some(&"a".repeat(64)),
        &PassagePolicy::default(),
    )
    .unwrap();
    let reused = generation(tx.connection()).unwrap();
    assert!(reused > epoch);
    assert!(
        lexical_candidates(tx.connection(), &q, 100)
            .unwrap()
            .is_empty()
    );
    drop(tx);
    assert_eq!(generation(a.connection()).unwrap(), epoch);
    assert!(
        !lexical_candidates(a.connection(), &q, 100)
            .unwrap()
            .is_empty()
    );
    replace(&mut a, &passages("COOKIE_JAR_CONFLICT changed"));
    assert_eq!(generation(a.connection()).unwrap(), reused);
    assert!(
        !lexical_candidates(a.connection(), &q, 100)
            .unwrap()
            .is_empty()
    );
}
#[test]
fn isolated_surrogates_split_lexical_words_and_scalar_astrals_remain_words() {
    use ken_text::PythonText;
    let p = PythonText::from_codepoints(vec![114, 101, 97, 100, 0xd800, 119, 114, 105, 116, 101])
        .unwrap();
    assert_eq!(
        ken_retrieval::vocabulary::code_tokens_python(&p),
        vec!["read", "write"]
    );
    assert_eq!(
        ken_retrieval::vocabulary::code_tokens_python(&"𐐀Word".into()),
        ken_retrieval::vocabulary::code_tokens("𐐀Word")
    );
}
