use flate2::read::GzDecoder;
use ken_program::value::GraphValue;
use ken_query::{
    Program,
    execution::{indexed_runtime::IndexedOutcome, values::Value as QueryValue},
};
use ken_structural::application::sessions::{
    QueryApplication, QueryOptions, QueryPhase, SessionError, SessionOptions, SourceProfile,
    query_response,
};
use serde_json::{Value, json};
use sha2::Digest;
use std::{
    collections::BTreeMap,
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
    time::Instant,
};
const QUERY: &str = r#"language "kql/2";module session_contract;query q{class $c{name:"SessionBeacon";}select $c.name,$c.path;}"#;
const LIB: &str = r#"language "kql/2";module ken.catalog.session_fixture;pattern Pick(out TypeDecl $c){class $c{name:"SessionBeacon";}}"#;
fn fixture() -> Value {
    let bytes = include_bytes!("fixtures/query-session-wrapper-reference.json.gz");
    assert_eq!(bytes.len(), 1889);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "5885ee76bddb38a1f7adc4b91efaff3eb7802346095707430ebb81015ba209dc"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    serde_json::from_str(&text).unwrap()
}
fn value(v: &Value) -> QueryValue {
    if let Some(points) = v.get("__session_string_codepoints__") {
        let token = format!(
            "\"{}\"",
            points
                .as_array()
                .unwrap()
                .iter()
                .map(|p| format!("\\u{:04x}", p.as_u64().unwrap()))
                .collect::<String>()
        );
        return QueryValue::Scalar(
            GraphValue::parse(&serde_json::value::RawValue::from_string(token).unwrap()).unwrap(),
        );
    }

    match v.get("__class__").and_then(Value::as_str) {
        Some("Unknown") => QueryValue::unknown(v["reason"].as_str().unwrap()),
        Some("Option") => QueryValue::Option {
            present: v["present"].as_bool().unwrap(),
            value: Box::new(value(&v["value"])),
        },
        Some("EnumValue") => QueryValue::Enum {
            r#type: v["type"].as_str().unwrap().into(),
            name: v["name"].as_str().unwrap().into(),
        },
        _ => QueryValue::Scalar(
            GraphValue::parse(&serde_json::value::RawValue::from_string(v.to_string()).unwrap())
                .unwrap(),
        ),
    }
}
fn canonical_lossless_json(text: &str) -> GraphValue {
    fn canonical(value: &mut GraphValue) {
        match value {
            GraphValue::Dict(items) => {
                for (_, value) in items.iter_mut() {
                    canonical(value);
                }
                items.sort_by(|a, b| a.0.codepoints().cmp(b.0.codepoints()));
            }
            GraphValue::List(items) => {
                for item in items {
                    canonical(item);
                }
            }
            _ => (),
        }
    }
    let mut value =
        GraphValue::parse(&serde_json::value::RawValue::from_string(text.to_owned()).unwrap())
            .unwrap();
    canonical(&mut value);
    value
}
#[test]
fn frozen_reporting_preserves_public_fields_big_integers_and_surrogates() {
    let f = fixture();
    for case in f["reporting"].as_array().unwrap() {
        let program: Program = serde_json::from_value(case["program"].clone()).unwrap();
        let o = &case["outcome"];
        let outcome = IndexedOutcome {
            rows: o["rows"]
                .as_array()
                .unwrap()
                .iter()
                .map(|r| r.as_array().unwrap().iter().map(value).collect())
                .collect(),
            complete: o["complete"].as_bool().unwrap(),
            results_truncated: o["results_truncated"].as_bool().unwrap(),
            unknown_candidates: o["unknown_candidates"].as_u64().unwrap(),
            reason: o["reason"].as_str().map(str::to_owned),
            plan: vec![],
            optional_evidence: o["optional_evidence"].as_array().unwrap().clone(),
            ..Default::default()
        };
        let response = query_response(&program, outcome, case["coverage"].as_bool().unwrap());
        let got = serde_json::to_string(&response).unwrap();
        let expected = case["response_json"].as_str().unwrap();
        if let (Ok(g), Ok(w)) = (
            serde_json::from_str::<Value>(&got),
            serde_json::from_str::<Value>(expected),
        ) {
            assert_eq!(g, w, "{}", case["name"]);
        } else {
            assert_eq!(
                canonical_lossless_json(&got),
                canonical_lossless_json(expected),
                "{}",
                case["name"]
            );
            assert!(response.to_json().is_err());
        }
    }
}
fn app(root: &Path) -> QueryApplication {
    let catalog = ken_syntax::GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("native grammar fixture manifest"),
    ))
    .unwrap();
    QueryApplication::new(
        root,
        Arc::new(catalog),
        BTreeMap::from([("ken.catalog.session_fixture".into(), LIB.into())]),
    )
    .unwrap()
}
fn options() -> SessionOptions {
    SessionOptions {
        cache_mb: 20.,
        ..Default::default()
    }
}
fn report(session: &mut ken_structural::application::sessions::QuerySession, query: &str) -> Value {
    session
        .search(Some(query), QueryOptions::default())
        .unwrap()
        .to_json()
        .unwrap()
}
#[test]
fn retained_session_never_recaptures_inside_query_and_refresh_is_explicit() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::write(root.join("a.py"), "class SessionBeacon: pass\n").unwrap();
    let application = app(root);
    let mut first = application.open(options()).unwrap();
    let mut second = application.open(options()).unwrap();
    let a = report(&mut first, QUERY);
    assert_eq!(a["rows"], json!([["SessionBeacon", "a.py"]]));
    assert_eq!(a["analysis"]["compilation_cache"]["status"], "miss");
    assert_eq!(
        report(&mut first, QUERY)["analysis"]["compilation_cache"]["status"],
        "memory"
    );
    std::fs::write(root.join("a.py"), "class SessionOther: pass\n").unwrap();
    assert_eq!(report(&mut first, QUERY)["rows"], a["rows"]);
    second.refresh().unwrap();
    assert!(
        report(&mut second, QUERY)["rows"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        report(&mut second, &QUERY.replace("SessionBeacon", "SessionOther"))["rows"],
        json!([["SessionOther", "a.py"]])
    );
    assert_eq!(
        report(&mut first, QUERY)["analysis"]["snapshot"],
        a["analysis"]["snapshot"]
    );
    first.refresh().unwrap();
    let changed = report(&mut first, QUERY);
    assert_ne!(changed["analysis"]["snapshot"], a["analysis"]["snapshot"]);
    assert_eq!(changed["analysis"]["freshness"], "captured_snapshot");
    assert_eq!(changed["analysis"]["parsed_units"], 0);
    assert_eq!(changed["analysis"]["result_cache"], "disabled");
    assert!(changed["analysis"]["manifest"].as_array().is_some());
    first.close().unwrap();
    second.close().unwrap();
}
#[test]
fn invalidation_is_thread_safe_and_failed_refresh_keeps_the_previous_reader() {
    let t = tempfile::tempdir().unwrap();
    std::fs::write(t.path().join("a.py"), "class SessionBeacon: pass\n").unwrap();
    let application = app(t.path());
    let mut session = application.open(options()).unwrap();
    let before = report(&mut session, QUERY)["analysis"]["reader_generation"].clone();
    let handle = session.invalidation_handle();
    std::thread::spawn(move || handle.invalidate())
        .join()
        .unwrap();
    assert!(matches!(
        session.search(Some(QUERY), Default::default()),
        Err(SessionError::SourcesChanged(_))
    ));
    session.refresh().unwrap();
    assert_eq!(
        report(&mut session, QUERY)["analysis"]["reader_generation"],
        before
    );
    let handle = session.invalidation_handle();
    let mut once = false;
    let error = session
        .refresh_checked(&mut || {
            if !once {
                once = true;
                handle.invalidate();
            }
            Ok(())
        })
        .unwrap_err();
    assert!(matches!(error, SessionError::SourcesChanged(_)));
    assert!(matches!(
        session.search(Some(QUERY), Default::default()),
        Err(SessionError::SourcesChanged(_))
    ));
    session.refresh().unwrap();
    assert_eq!(
        report(&mut session, QUERY)["analysis"]["reader_generation"],
        before
    );
    session.close().unwrap();
}
#[test]
fn budget_cancellation_and_delivery_checks_do_not_poison_later_queries() {
    let t = tempfile::tempdir().unwrap();
    std::fs::write(t.path().join("a.py"), "class SessionBeacon: pass\n").unwrap();
    let application = app(t.path());
    let mut session = application.open(options()).unwrap();
    for opt in [
        QueryOptions {
            timeout_ms: Some(-1.),
            ..Default::default()
        },
        QueryOptions {
            timeout_ms: Some(f64::NAN),
            ..Default::default()
        },
        QueryOptions {
            max_states: Some(0),
            ..Default::default()
        },
        QueryOptions {
            max_rows: Some(0),
            ..Default::default()
        },
    ] {
        assert!(matches!(
            session.search(Some(QUERY), opt),
            Err(SessionError::InvalidBudget)
        ));
    }
    for (opt, reason) in [
        (
            QueryOptions {
                timeout_ms: Some(0.),
                ..Default::default()
            },
            "timeout",
        ),
        (
            QueryOptions {
                deadline: Some(Instant::now()),
                ..Default::default()
            },
            "timeout",
        ),
        (
            QueryOptions {
                max_states: Some(1),
                ..Default::default()
            },
            "max_states",
        ),
    ] {
        let stopped = session.search(Some(QUERY), opt).unwrap().to_json().unwrap();
        assert_eq!(stopped["complete"], false);
        assert_eq!(stopped["reason"], reason);
        assert_eq!(report(&mut session, QUERY)["complete"], true);
    }
    let cancelled = QueryOptions::default();
    cancelled.cancellation.cancel();
    assert_eq!(
        session
            .search(Some(QUERY), cancelled)
            .unwrap()
            .to_json()
            .unwrap()["reason"],
        "cancelled"
    );
    assert_eq!(report(&mut session, QUERY)["complete"], true);
    for phase in [QueryPhase::Query, QueryPhase::Report, QueryPhase::Encoded] {
        let handle = session.invalidation_handle();
        let observer = Arc::new(move |seen| {
            if seen == phase {
                handle.invalidate();
            }
        });
        let options = QueryOptions {
            observer: Some(observer),
            ..Default::default()
        };
        let text = session.search_json(Some(QUERY), options).unwrap();
        let response: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(response["complete"], false);
        assert_eq!(response["reason"], "snapshot_invalidated");
        session.refresh().unwrap();
    }
    session.close().unwrap();
}
#[test]
fn session_guards_owner_close_and_expiry_without_reviving_a_dead_lease() {
    let t = tempfile::tempdir().unwrap();
    std::fs::write(t.path().join("a.py"), "class SessionBeacon: pass\n").unwrap();
    let application = app(t.path());
    let session = application.open(options()).unwrap();
    let (mut session, error) = std::thread::spawn(move || {
        let mut s = session;
        let error = s
            .search(Some(QUERY), Default::default())
            .unwrap_err()
            .to_string();
        (s, error)
    })
    .join()
    .unwrap();
    assert_eq!(
        error,
        "query sessions belong to their creating process and thread"
    );
    let before = report(&mut session, QUERY)["analysis"]["reader_generation"].clone();
    let database = t.path().join(".ken/structural/v2/store.sqlite");
    let writer = rusqlite::Connection::open(&database).unwrap();
    writer
        .execute("UPDATE k2_leases SET expires_ns=0", [])
        .unwrap();
    let expired = session
        .search(
            Some(QUERY),
            QueryOptions {
                include_entities: true,
                ..Default::default()
            },
        )
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(expired["entities"], json!({}));
    assert_eq!(expired["complete"], false);
    assert_eq!(expired["reason"], "snapshot_expired");
    assert!(expired["rows"].as_array().unwrap().is_empty());
    session.refresh().unwrap();
    assert_ne!(
        report(&mut session, QUERY)["analysis"]["reader_generation"],
        before
    );
    session.close().unwrap();
    session.close().unwrap();
    assert!(matches!(
        session.search(Some(QUERY), Default::default()),
        Err(SessionError::Closed)
    ));
    assert!(matches!(session.refresh(), Err(SessionError::Closed)));
    assert_eq!(
        writer
            .query_row("SELECT count(*) FROM k2_leases", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn explicit_scope_locations_profile_and_library_snapshots_are_preserved() {
    let t = tempfile::tempdir().unwrap();
    std::fs::write(
        t.path().join("a.py"),
        "class SessionBeacon: pass\ndef focused(): return 1\n",
    )
    .unwrap();
    std::fs::write(
        t.path().join("b.py"),
        "class SessionOther: pass\ndef unrelated(): return 2\n",
    )
    .unwrap();
    let application = app(t.path());
    let mut session = application
        .open(SessionOptions {
            source_paths: Some(vec!["a.py".into(), "a.py".into()]),
            ..options()
        })
        .unwrap();
    session.prepare_graph().unwrap();
    session.prepare_semantics().unwrap();
    session
        .prepare_query(Some(QUERY), QueryOptions::default())
        .unwrap();
    let q = r#"language "kql/2";module scoped;query q{edge ENTITY($f,"CALLABLE");select $f;}"#;
    let response = session
        .search(
            Some(q),
            QueryOptions {
                include_entities: true,
                profile: true,
                ..Default::default()
            },
        )
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(
        response["source_scope"],
        json!({"kind":"explicit_files","paths":["a.py"]})
    );
    assert_eq!(response["rows"].as_array().unwrap().len(), 1);
    let id = response["rows"][0][0].as_str().unwrap();
    assert_eq!(response["entities"][id]["name"], "focused");
    assert_eq!(response["entities"][id]["path"], "a.py");
    assert!(response["analysis"]["operator_profile"].is_array());
    assert_eq!(
        response["analysis"]["manifest"].as_array().unwrap().len(),
        1
    );
    let imported = r#"language "kql/2";module main;import ken.catalog.session_fixture;query q{use ken.catalog.session_fixture.Pick(c:$c);select $c.name;}"#;
    assert_eq!(
        report(&mut session, imported)["rows"],
        json!([["SessionBeacon"]])
    );
    application
        .replace_packaged_libraries(BTreeMap::from([(
            "ken.catalog.session_fixture".into(),
            LIB.replace("SessionBeacon", "SessionOther"),
        )]))
        .unwrap();
    assert_eq!(
        report(&mut session, imported)["rows"],
        json!([["SessionBeacon"]])
    );
    session.refresh().unwrap();
    assert!(
        report(&mut session, imported)["rows"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    session.close().unwrap();
    let mut limited = application
        .open(SessionOptions {
            source_profile: SourceProfile::LocalHazards,
            ..options()
        })
        .unwrap();
    assert!(matches!(
        limited.search(Some(QUERY), Default::default()),
        Err(SessionError::InvalidProfile)
    ));
    limited.close().unwrap();
    assert!(matches!(
        application.open(SessionOptions {
            cache_mb: 0.,
            ..Default::default()
        }),
        Err(SessionError::PersistentStorageRequired)
    ));
}
#[test]
fn json_transport_retains_surrogate_and_large_integer_values() {
    let t = tempfile::tempdir().unwrap();
    std::fs::write(t.path().join("a.py"), "class SessionBeacon: pass\n").unwrap();
    let application = app(t.path());
    let mut session = application.open(options()).unwrap();
    let integer = "9".repeat(500);
    let query =
        format!(r#"language "kql/2";module lossless;query q{{select {integer},"\ud800";}}"#);
    let response = session.search(Some(&query), Default::default()).unwrap();
    assert!(response.to_json().is_err());
    let text = session
        .search_json(Some(&query), Default::default())
        .unwrap();
    assert!(text.contains(&integer));
    assert!(text.contains("\\ud800"));
    assert_eq!(report(&mut session, QUERY)["complete"], true);
    session.close().unwrap();
}

#[test]
fn session_storage_paths_reject_metadata_symlinks_outside_project() {
    let project = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    std::fs::write(project.path().join("a.py"), "class SessionBeacon: pass\n").unwrap();
    std::os::unix::fs::symlink(outside.path(), project.path().join(".ken")).unwrap();
    let application = app(project.path());
    assert!(matches!(
        application.open(options()),
        Err(SessionError::Project(_))
    ));
    assert_eq!(std::fs::read_dir(outside.path()).unwrap().count(), 0);
}

#[test]
fn cancellation_at_report_and_encoded_delivery_never_returns_complete_success() {
    use ken_query::execution::Cancellation;
    let project = tempfile::tempdir().unwrap();
    std::fs::write(project.path().join("a.py"), "class SessionBeacon: pass\n").unwrap();
    let application = app(project.path());
    let mut session = application.open(options()).unwrap();
    for phase in [QueryPhase::Report, QueryPhase::Encoded] {
        let token = Cancellation::default();
        let cancelled = token.clone();
        let request = QueryOptions {
            cancellation: token,
            observer: Some(Arc::new(move |observed| {
                if observed == phase {
                    cancelled.cancel();
                }
            })),
            ..Default::default()
        };
        if phase == QueryPhase::Report {
            let response = session.search(Some(QUERY), request).unwrap();
            assert!(
                !response.complete,
                "cancelled report was delivered as complete"
            );
            assert_eq!(response.reason.as_deref(), Some("cancelled"));
        } else {
            let response: Value =
                serde_json::from_str(&session.search_json(Some(QUERY), request).unwrap()).unwrap();
            assert_eq!(response["complete"], false);
            assert_eq!(response["reason"], "cancelled");
        }
        assert_eq!(report(&mut session, QUERY)["complete"], true);
    }
    session.close().unwrap();
}
#[test]
fn transient_sessions_preserve_full_execution_and_refresh_without_any_persistent_cache() {
    use ken_structural::application::sessions::{QueryApplication, QueryOptions, SessionOptions};
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("a.py"), "class Alpha: pass\n").unwrap();
    let grammars = std::sync::Arc::new(
        ken_syntax::GrammarCatalog::prepared(&std::path::PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    );
    let catalog = ken_structural::application::catalog::Catalog::packaged().unwrap();
    let application =
        QueryApplication::new(root.path(), grammars, catalog.libraries().clone()).unwrap();
    let mut session = application
        .open_transient(SessionOptions::default())
        .unwrap();
    let source = "language \"kql/2\";module transient;query classes{class $c{}select $c;}";
    let first = session
        .search(Some(source), QueryOptions::default())
        .unwrap();
    assert!(first.complete);
    assert_eq!(first.rows.len(), 1);
    assert!(!root.path().join(".ken").exists());
    std::fs::write(
        root.path().join("a.py"),
        "class Beta: pass\nclass Gamma: pass\n",
    )
    .unwrap();
    session.refresh().unwrap();
    let second = session
        .search(Some(source), QueryOptions::default())
        .unwrap();
    assert!(second.complete);
    assert_eq!(second.rows.len(), 2);
    assert_ne!(first.rows, second.rows);
    assert!(!root.path().join(".ken").exists());
    let json = session
        .search_json(
            Some("language \"kql/2\";module transient;query literals{select \"\\ud800\";}"),
            QueryOptions::default(),
        )
        .unwrap();
    assert!(json.contains("\\ud800"));
    session.close().unwrap();
}
