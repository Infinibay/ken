use flate2::read::GzDecoder;
use ken_program::{
    StructuralIr,
    query_view::normalize_query_graph,
    value::{GraphValue as V, parse_float_hex},
};
use ken_store::structural::{
    StructuralError, StructuralStore,
    graph::{
        EntityFilter, FactFilter, GraphIndex, GraphValues, OperationFilter, publish_graph,
        publish_graph_owned,
    },
};
use serde_json::{Value, json};
use sha2::Digest;
use std::io::Read;
fn reference() -> Value {
    let bytes = include_bytes!("fixtures/query-graph-reference.json.gz");
    assert_eq!(bytes.len(), 1622826);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "730db94ed79125323cfe497fbef50503b6c62f8bba0c665f25ba8cf5695554a7"
    );
    let mut text = String::new();
    GzDecoder::new(&include_bytes!("fixtures/query-graph-reference.json.gz")[..])
        .read_to_string(&mut text)
        .unwrap();
    serde_json::from_str(&text).unwrap()
}
fn queries() -> Vec<StructuralIr> {
    #[derive(serde::Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    #[derive(serde::Deserialize)]
    struct Case {
        query: StructuralIr,
    }
    let mut text = String::new();
    GzDecoder::new(&include_bytes!("fixtures/query-graph-reference.json.gz")[..])
        .read_to_string(&mut text)
        .unwrap();
    serde_json::from_str::<Corpus>(&text)
        .unwrap()
        .cases
        .into_iter()
        .map(|c| c.query)
        .collect()
}
fn ir(v: &Value) -> StructuralIr {
    StructuralIr::from_json(&v.to_string()).unwrap()
}
fn sorted_facts(v: &mut Value) {
    v["facts"]
        .as_array_mut()
        .unwrap()
        .sort_by_key(Value::to_string);
}
fn empty() -> StructuralIr {
    ir(
        &json!({"path":"<values>","language":"mixed","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":[],"version":ken_program::IR_VERSION,"view":"query"}),
    )
}
fn publish(store: &mut StructuralStore, key: &str, ir: &StructuralIr) -> i64 {
    let snapshot = store
        .publish(
            &[],
            store.current().unwrap(),
            key,
            ir.diagnostics.is_empty(),
        )
        .unwrap();
    publish_graph(store, snapshot, key, ir, &V::Dict(vec![]), &mut || Ok(())).unwrap()
}
#[test]
fn query_normalization_matches_79_original_graphs() {
    for case in reference()["cases"].as_array().unwrap() {
        let source = ir(&case["input"]);
        let before = serde_json::to_string(&source).unwrap();
        let query = normalize_query_graph(&source).unwrap();
        assert_eq!(before, serde_json::to_string(&source).unwrap());
        let mut got = serde_json::to_value(&query).unwrap();
        let mut want = case["query"].clone();
        sorted_facts(&mut got);
        sorted_facts(&mut want);
        assert_eq!(got, want, "{}", case["name"]);
        assert_eq!(
            serde_json::to_value(normalize_query_graph(&query).unwrap()).unwrap(),
            serde_json::to_value(query).unwrap()
        );
    }
}
fn assert_index(index: &GraphIndex<'_>, case: &Value) {
    let entities = index
        .entities(&EntityFilter::default())
        .unwrap()
        .rows()
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(
        serde_json::to_value(entities).unwrap(),
        case["entities"],
        "entities {}",
        case["name"]
    );
    let operations = index
        .operations(&OperationFilter::default())
        .unwrap()
        .rows()
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(
        serde_json::to_value(operations).unwrap(),
        case["operations"],
        "operations {}",
        case["name"]
    );
    assert_eq!(
        serde_json::to_value(&index.capabilities).unwrap(),
        case["capabilities"]
    );
    assert_eq!(
        serde_json::to_value(&index.relations).unwrap(),
        case["relations"]
    );
    for row in case["observations"].as_array().unwrap() {
        let filter = FactFilter {
            relation: row["relation"].as_str().unwrap().into(),
            subject: row["subject"].as_str().map(str::to_owned),
            object: row["object"].as_str().map(str::to_owned),
            attribute: None,
        };
        let count = row["count"].as_u64().unwrap();
        assert_eq!(index.count(&filter).unwrap(), count);
        assert_eq!(index.exists(&filter).unwrap(), count != 0);
        let got = index
            .facts(&filter)
            .unwrap()
            .rows()
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        assert_eq!(
            serde_json::to_value(got).unwrap(),
            row["facts"],
            "facts {} {}",
            case["name"],
            row["relation"]
        );
    }
    for row in case["bounds"].as_array().unwrap() {
        assert_eq!(
            serde_json::to_value(index.syntax_bounds(row[0].as_str().unwrap()).unwrap()).unwrap(),
            row[1]
        );
    }
}
#[test]
fn native_publication_preserves_original_index_results() {
    let mut store = StructuralStore::open(None, None).unwrap();
    for (case, query) in reference()["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(queries())
        .filter(|(c, _)| c.get("graph").is_some())
    {
        let id = publish(&mut store, case["name"].as_str().unwrap(), &query);
        let index = GraphIndex::open(&mut store, id).unwrap();
        assert_index(&index, case);
    }
}
#[test]
fn opens_original_sqlite_with_overlays_and_native_columns() {
    let temp = tempfile::tempdir().unwrap();
    let db = temp.path().join("original.sqlite");
    assert_eq!(
        format!(
            "{:x}",
            sha2::Sha256::digest(include_bytes!("fixtures/query-graph-original.sqlite.gz"))
        ),
        "d3f667dd971d0470f3a31e06f30f7c83d87ef269c67ca98ab07054c5367570a4"
    );
    let mut bytes = Vec::new();
    GzDecoder::new(&include_bytes!("fixtures/query-graph-original.sqlite.gz")[..])
        .read_to_end(&mut bytes)
        .unwrap();
    std::fs::write(&db, bytes).unwrap();
    let mut store = StructuralStore::open(Some(&db), None).unwrap();
    for case in reference()["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c.get("graph").is_some())
    {
        let index = GraphIndex::open(&mut store, case["graph"].as_i64().unwrap()).unwrap();
        assert_index(&index, case);
    }
}
fn tagged(v: &Value) -> V {
    match v["tag"].as_str().unwrap() {
        "NoneType" => V::Null,
        "bool" => V::Bool(v["value"].as_bool().unwrap()),
        "int" => V::Int(v["decimal"].as_str().unwrap().into()),
        "float" => V::Float(parse_float_hex(v["hex"].as_str().unwrap()).unwrap()),
        "str" => V::String(v["value"].as_str().unwrap().into()),
        "dict" => V::Dict(
            v["items"]
                .as_array()
                .unwrap()
                .iter()
                .map(|p| (p[0].as_str().unwrap().into(), tagged(&p[1])))
                .collect(),
        ),
        "list" => V::List(v["items"].as_array().unwrap().iter().map(tagged).collect()),
        "tuple" => V::Tuple(v["items"].as_array().unwrap().iter().map(tagged).collect()),
        "set" => V::Set(v["items"].as_array().unwrap().iter().map(tagged).collect()),
        _ => panic!(),
    }
}
#[test]
fn typed_values_match_original_signatures_and_float_strings() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let graph = publish(&mut store, "values", &empty());
    let values = GraphValues::new(store.connection(), graph);
    for case in reference()["values"]["cases"].as_array().unwrap() {
        let value = tagged(&case["input"]);
        let id = values.put(&value).unwrap();
        assert_eq!(id, case["id"].as_i64().unwrap(), "{value:?}");
        let signature:String=store.connection().query_row("SELECT lower(hex(signature)) FROM k2_graph_values WHERE graph_id=?1 AND value_id=?2",[graph,id],|r|r.get(0)).unwrap();
        assert_eq!(signature, case["signature"].as_str().unwrap(), "{value:?}");
        let got = values.get(id).unwrap();
        if !matches!(&value, V::Set(_)) {
            assert_eq!(
                got.comparison(),
                case["comparison"].as_str().unwrap(),
                "{value:?}"
            );
        }
        if matches!(value,V::Float(v)if v.is_nan()) {
            assert!(matches!(got,V::Float(v)if v.is_nan()));
        } else {
            assert_eq!(got, value);
        }
    }
}
#[test]
fn cancellation_discards_partial_graph_and_reuses_ready_revision() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let snapshot = store.publish(&[], None, "test", true).unwrap();
    let mut calls = 0;
    let err = publish_graph_owned(
        &mut store,
        snapshot,
        "broken",
        empty(),
        &V::Null,
        &mut || {
            calls += 1;
            if calls == 3 {
                Err(StructuralError::Invalid("cancelled"))
            } else {
                Ok(())
            }
        },
    )
    .unwrap_err();
    assert!(err.to_string().contains("cancelled"));
    assert_eq!(
        store
            .connection()
            .query_row("SELECT count(*) FROM k2_graphs", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        0
    );
    let id = publish_graph(
        &mut store,
        snapshot,
        "ready",
        &empty(),
        &V::Null,
        &mut || Ok(()),
    )
    .unwrap();
    assert_eq!(
        publish_graph_owned(
            &mut store,
            snapshot,
            "ready",
            empty(),
            &V::Null,
            &mut || Ok(())
        )
        .unwrap(),
        id
    );
}
#[test]
fn value_keys_preserve_big_integers_surrogates_and_dictionary_order() {
    let raw=serde_json::value::RawValue::from_string(r#"{"z":1267650600228229401496703205376,"a":"\ud834\udd1e","lone":"\ud800","z":-1267650600228229401496703205376}"#.into()).unwrap();
    let value = V::parse(&raw).unwrap();
    assert!(
        value
            .repr()
            .starts_with("{'z': -1267650600228229401496703205376, 'a': '𝄞'")
    );
    assert!(value.repr().contains("\\ud800"));
    assert_eq!(V::parse(&value.to_raw().unwrap()).unwrap(), value);
}
#[test]
fn indexed_attribute_and_owner_candidates_match_full_records() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let corpus = reference();
    let queries = queries();
    for (case, query) in corpus["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(queries)
        .filter(|(c, _)| c.get("graph").is_some())
    {
        let graph = publish(&mut store, case["name"].as_str().unwrap(), &query);
        let index = GraphIndex::open(&mut store, graph).unwrap();
        // Representative keys exercise ordinary values and operation column overlays.
        for relation in ["ENTITY", "OPERATION", "ARGUMENT", "VALUE_FLOW"] {
            for key in [
                "kind",
                "native_kind",
                "owner",
                "role",
                "start_byte",
                "end_byte",
                "type",
                "method",
                "position",
                "modality",
                "tokens",
            ] {
                let mut keys = std::collections::BTreeSet::new();
                for f in query.facts.iter().filter(|f| f.relation == relation) {
                    if let Some(value) = f.attrs.get(key) {
                        keys.insert(V::parse(value).unwrap().comparison());
                    }
                }
                for comparison in keys {
                    let filter = FactFilter {
                        attribute: Some((key.into(), comparison.clone())),
                        ..FactFilter::relation(relation)
                    };
                    let got = index
                        .facts(&filter)
                        .unwrap()
                        .rows()
                        .unwrap()
                        .collect::<Result<Vec<_>, _>>()
                        .unwrap();
                    let want: Vec<_> = query
                        .facts
                        .iter()
                        .filter(|f| {
                            f.relation == relation
                                && f.attrs.get(key).is_some_and(|r| {
                                    V::parse(r).unwrap().comparison() == comparison
                                })
                        })
                        .cloned()
                        .collect();
                    assert_eq!(
                        serde_json::to_value(got).unwrap(),
                        serde_json::to_value(&want).unwrap(),
                        "{} {relation} {key} {comparison}",
                        case["name"]
                    );
                    assert_eq!(index.count(&filter).unwrap(), want.len() as u64);
                }
            }
        }
        for (_, e) in query.entities.iter().take(8) {
            let got = index
                .entities(&EntityFilter {
                    local_id: Some(e.id.clone()),
                    ..Default::default()
                })
                .unwrap()
                .rows()
                .unwrap()
                .collect::<Result<Vec<_>, _>>()
                .unwrap();
            assert_eq!(serde_json::to_value(got).unwrap(), json!([e]));
        }
        for o in query.operations.iter().take(8) {
            let bounds = index.syntax_bounds(&o.id).unwrap().unwrap();
            let got = index
                .operations(&OperationFilter {
                    region: Some(o.id.clone()),
                    ..Default::default()
                })
                .unwrap()
                .rows()
                .unwrap()
                .collect::<Result<Vec<_>, _>>()
                .unwrap();
            let want: Vec<_> = query
                .operations
                .iter()
                .filter(|op| {
                    index
                        .syntax_bounds(&op.id)
                        .unwrap()
                        .is_some_and(|(start, _, _)| start >= bounds.0 && start < bounds.1)
                })
                .cloned()
                .collect();
            assert_eq!(
                serde_json::to_value(got).unwrap(),
                serde_json::to_value(&want).unwrap()
            );
        }
    }
}
#[test]
fn publication_rejects_cycles_and_isolated_sqlite_surrogates() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let snapshot = store.publish(&[], None, "invalid", true).unwrap();
    let mut query = empty();
    query.operations.push(ken_program::Operation {
        id: "cycle".into(),
        kind: "BLOCK".into(),
        native_kind: "block".into(),
        parent: Some("cycle".into()),
        role: "".into(),
        start: 0,
        end: 0,
        line: 0,
        owner: "owner".into(),
        attrs: Default::default(),
    });
    assert!(
        publish_graph(&mut store, snapshot, "cycle", &query, &V::Null, &mut || Ok(
            ()
        ))
        .unwrap_err()
        .to_string()
        .contains("cyclic")
    );
    let raw = serde_json::value::RawValue::from_string(r#""\ud800""#.into()).unwrap();
    query.operations.clear();
    query.facts.push(ken_program::Fact {
        subject: "s".into(),
        relation: "R".into(),
        object: "o".into(),
        attrs: [("bad".into(), raw)].into(),
        evidence: vec![],
    });
    assert!(
        publish_graph(
            &mut store,
            snapshot,
            "surrogate",
            &query,
            &V::Null,
            &mut || Ok(())
        )
        .unwrap_err()
        .to_string()
        .contains("surrogate")
    );
    assert_eq!(
        store
            .connection()
            .query_row("SELECT count(*) FROM k2_graphs", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn incomplete_graphs_are_invisible_live_writers_conflict_and_stale_writers_replace() {
    let temp = tempfile::tempdir().unwrap();
    let db = temp.path().join("graphs.sqlite");
    let mut store = StructuralStore::open(Some(&db), None).unwrap();
    let snapshot = store.publish(&[], None, "stale", true).unwrap();
    store.connection().execute("INSERT INTO k2_graphs(snapshot_id,fingerprint,path,language,version,view,metadata)VALUES(?1,'key','x','mixed',?2,'query',0)",rusqlite::params![snapshot,ken_program::IR_VERSION]).unwrap();
    let old = store.connection().last_insert_rowid();
    store
        .connection()
        .execute(
            "INSERT INTO k2_graph_publications VALUES(?1,0,?2)",
            rusqlite::params![old, store.lease_id()],
        )
        .unwrap();
    assert!(GraphIndex::open(&mut store, old).is_err());
    assert!(
        publish_graph(&mut store, snapshot, "key", &empty(), &V::Null, &mut || Ok(
            ()
        ))
        .unwrap_err()
        .to_string()
        .contains("progress")
    );
    store
        .connection()
        .execute(
            "UPDATE k2_graph_publications SET lease_id='abandoned' WHERE graph_id=?1",
            [old],
        )
        .unwrap();
    let graph = publish_graph(&mut store, snapshot, "key", &empty(), &V::Null, &mut || {
        Ok(())
    })
    .unwrap();
    assert!(GraphIndex::open(&mut store, graph).is_ok());
}
#[test]
fn bounded_batches_commit_then_cancel_without_ready_or_dictionary_orphans() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let snapshot = store.publish(&[], None, "large", true).unwrap();
    let mut query = empty();
    query.facts = (0..40000)
        .map(|i| ken_program::Fact {
            subject: format!("s{i}"),
            relation: "R".into(),
            object: "o".into(),
            attrs: Default::default(),
            evidence: vec![],
        })
        .collect();
    let mut checks = 0;
    let result = publish_graph_owned(&mut store, snapshot, "large", query, &V::Null, &mut || {
        checks += 1;
        if checks == 75 {
            Err(StructuralError::Invalid("cancel after batch"))
        } else {
            Ok(())
        }
    });
    assert!(result.unwrap_err().to_string().contains("cancel"));
    assert!(checks >= 75);
    for table in [
        "k2_graphs",
        "k2_graph_terms",
        "k2_graph_values",
        "k2_graph_members",
        "k2_graph_facts",
    ] {
        assert_eq!(
            store
                .connection()
                .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
}
#[test]
fn a_reader_pin_protects_old_snapshots_and_missing_lookups_are_indexed() {
    let temp = tempfile::tempdir().unwrap();
    let db = temp.path().join("pin.sqlite");
    let mut reader = StructuralStore::open(Some(&db), None).unwrap();
    let graph = publish(&mut reader, "old", &empty());
    let index = GraphIndex::open(&mut reader, graph).unwrap();
    let mut writer = StructuralStore::open(Some(&db), None).unwrap();
    publish(&mut writer, "new", &empty());
    assert_eq!(writer.collect(1, &[]).unwrap().snapshots, 0);
    assert_eq!(index.count(&FactFilter::relation("missing")).unwrap(), 0);
    drop(index);
    reader.close().unwrap();
    assert_eq!(writer.collect(1, &[]).unwrap().snapshots, 1);
}
#[test]
fn source_views_coverage_and_call_pruning_match_original() {
    let mut text = String::new();
    let fixture = include_bytes!("fixtures/query-source-reference.json.gz");
    assert_eq!(fixture.len(), 30196);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(fixture)),
        "5ac2bb971e5bda46b6417b227b0fe9185a6aa89ff0edcdf7698dabd18c0a58ed"
    );
    GzDecoder::new(&fixture[..])
        .read_to_string(&mut text)
        .unwrap();
    let data: Value = serde_json::from_str(&text).unwrap();
    let queries = queries();
    let refs = reference();
    let mut store = StructuralStore::open(None, None).unwrap();
    for case in data["cases"].as_array().unwrap() {
        let n = refs["cases"]
            .as_array()
            .unwrap()
            .iter()
            .position(|r| r["name"] == case["name"])
            .unwrap();
        let graph = publish(&mut store, case["name"].as_str().unwrap(), &queries[n]);
        let index = GraphIndex::open(&mut store, graph).unwrap();
        let source = index.source_view();
        for row in case["nodes"].as_array().unwrap() {
            let node = source.node(row["id"].as_str().unwrap()).unwrap();
            assert_eq!(
                serde_json::to_value(&node).unwrap(),
                row["node"],
                "node {} {}",
                case["name"],
                row["id"]
            );
            let properties = node.as_ref().map(|n| source.properties(n).unwrap());
            assert_eq!(
                serde_json::to_value(properties).unwrap(),
                row["properties"],
                "properties {} {}",
                case["name"],
                row["id"]
            );
        }
        for row in case["owners"].as_array().unwrap() {
            let owner = row["owner"].as_str().unwrap();
            assert_eq!(
                serde_json::to_value(source.owner_nodes(owner).unwrap()).unwrap(),
                row["nodes"]
            );
            assert_eq!(
                serde_json::to_value(source.owner_entities(owner).unwrap()).unwrap(),
                row["entities"]
            );
        }
        for row in case["witnesses"].as_array().unwrap() {
            let names = serde_json::from_value(row["names"].clone()).unwrap();
            let (matches, missing) = index.call_witnesses(&names).unwrap();
            assert_eq!(serde_json::to_value(matches).unwrap(), row["matches"]);
            assert_eq!(serde_json::to_value(missing).unwrap(), row["missing"]);
        }
        for row in case["operation_owners"].as_array().unwrap() {
            assert_eq!(
                serde_json::to_value(
                    index
                        .operation_owners(&serde_json::from_value(row["kinds"].clone()).unwrap())
                        .unwrap()
                )
                .unwrap(),
                row["owners"]
            );
        }
        for (general, key) in [(false, "coverage"), (true, "general_coverage")] {
            let got = index.source_coverage(general).unwrap();
            assert_eq!(json!([got.universe, got.covered, got.uncovered]), case[key]);
        }
    }
}
#[test]
fn indexed_lookups_and_member_projection_have_bounded_sql_work() {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let mut query = empty();
    for i in 0..10000 {
        let mut attrs = ken_program::Attributes::new();
        for (k, v) in [
            ("kind", json!("call")),
            (
                "native_kind",
                json!(if i == 9999 {
                    "needle"
                } else {
                    "call_expression"
                }),
            ),
            ("owner", json!("owner")),
            ("role", json!("value")),
            ("start_byte", json!(i)),
            ("end_byte", json!(i + 1)),
        ] {
            attrs.insert(k.into(), serde_json::value::to_raw_value(&v).unwrap());
        }
        query.operations.push(ken_program::Operation {
            id: format!("op{i}"),
            kind: "CALL".into(),
            native_kind: if i == 9999 {
                "needle"
            } else {
                "call_expression"
            }
            .into(),
            parent: None,
            role: "value".into(),
            start: i,
            end: i + 1,
            line: 1,
            owner: "owner".into(),
            attrs: Default::default(),
        });
        query.facts.push(ken_program::Fact {
            subject: format!("op{i}"),
            relation: "OPERATION".into(),
            object: "CALL".into(),
            attrs,
            evidence: vec![],
        });
    }
    let mut store = StructuralStore::open(None, None).unwrap();
    let graph = publish(&mut store, "indexed", &query);
    let ticks = Arc::new(AtomicUsize::new(0));
    let count = ticks.clone();
    store
        .connection()
        .progress_handler(
            100,
            Some(move || {
                count.fetch_add(1, Ordering::Relaxed);
                false
            }),
        )
        .unwrap();
    let index = GraphIndex::open(&mut store, graph).unwrap();
    ticks.store(0, Ordering::Relaxed);
    // A broad relation count must use its maintained count, not count every fact.
    assert_eq!(
        index.count(&FactFilter::relation("OPERATION")).unwrap(),
        10000
    );
    assert!(ticks.swap(0, Ordering::Relaxed) < 200);
    let filter = FactFilter {
        subject: Some("op9999".into()),
        ..FactFilter::relation("OPERATION")
    };
    assert_eq!(index.facts(&filter).unwrap().rows().unwrap().count(), 1);
    assert!(ticks.swap(0, Ordering::Relaxed) < 200);
    let endpoint = FactFilter {
        subject: Some("op9999".into()),
        attribute: Some(("start_byte".into(), "9999".into())),
        ..FactFilter::relation("OPERATION")
    };
    assert_eq!(index.facts(&endpoint).unwrap().rows().unwrap().count(), 1);
    assert!(
        ticks.swap(0, Ordering::Relaxed) < 200,
        "endpoint attribute query scanned the graph"
    );
    let filter = FactFilter {
        attribute: Some(("native_kind".into(), "needle".into())),
        ..FactFilter::relation("OPERATION")
    };
    assert_eq!(index.facts(&filter).unwrap().rows().unwrap().count(), 1);
    assert!(
        ticks.swap(0, Ordering::Relaxed) < 200,
        "overlay lookup scanned the graph"
    );
    assert_eq!(
        index
            .operations(&OperationFilter {
                local_id: Some("op9999".into()),
                ..Default::default()
            })
            .unwrap()
            .rows()
            .unwrap()
            .count(),
        1
    );
    assert!(ticks.swap(0, Ordering::Relaxed) < 200);
    drop(index);
    store
        .connection()
        .progress_handler(0, None::<fn() -> bool>)
        .unwrap();
    let values = GraphValues::new(store.connection(), graph);
    let value = V::Dict(vec![
        ("needed".into(), V::Int("3".into())),
        (
            "unrelated".into(),
            V::List((0..10000).map(|i| V::Int(i.to_string())).collect()),
        ),
    ]);
    let id = values.put(&value).unwrap();
    let count = ticks.clone();
    store
        .connection()
        .progress_handler(
            100,
            Some(move || {
                count.fetch_add(1, Ordering::Relaxed);
                false
            }),
        )
        .unwrap();
    assert_eq!(
        values.member(id, "needed").unwrap(),
        Some(V::Int("3".into()))
    );
    assert!(ticks.load(Ordering::Relaxed) < 200);
    store
        .connection()
        .progress_handler(0, None::<fn() -> bool>)
        .unwrap();
}
#[test]
fn checked_scans_stop_before_decoding_and_fuse_after_cancellation() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let mut q = empty();
    q.facts = (0..3)
        .map(|i| ken_program::Fact {
            subject: i.to_string(),
            relation: "R".into(),
            object: "o".into(),
            attrs: Default::default(),
            evidence: vec![],
        })
        .collect();
    let graph = publish(&mut store, "scan-check", &q);
    let index = GraphIndex::open(&mut store, graph).unwrap();
    let mut scan = index.facts(&FactFilter::relation("R")).unwrap();
    let mut calls = 0;
    let mut rows = scan
        .rows_checked(|| {
            calls += 1;
            if calls > 1 {
                Err(StructuralError::Invalid("stop"))
            } else {
                Ok(())
            }
        })
        .unwrap();
    assert!(rows.next().unwrap().is_ok());
    assert!(
        rows.next()
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("stop")
    );
    assert!(rows.next().is_none());
}
#[test]
fn sqlite_execution_scope_interrupts_work_and_restores_connection() {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    let mut store = StructuralStore::open(None, None).unwrap();
    let mut query = empty();
    query.facts = (0..10000)
        .map(|i| ken_program::Fact {
            subject: i.to_string(),
            relation: "R".into(),
            object: "o".into(),
            attrs: [("x".into(), serde_json::value::to_raw_value(&1).unwrap())].into(),
            evidence: vec![],
        })
        .collect();
    let graph = publish(&mut store, "interruption", &query);
    let mut index = GraphIndex::open(&mut store, graph).unwrap();
    let ticks = Arc::new(AtomicUsize::new(0));
    let count = ticks.clone();
    {
        let execution = index
            .execution(move || count.fetch_add(1, Ordering::Relaxed) > 0)
            .unwrap();
        let filter = FactFilter {
            object: Some("o".into()),
            ..FactFilter::relation("R")
        };
        let error = execution.count(&filter).unwrap_err();
        assert!(
            matches!(error,StructuralError::Sql(ref e)if e.sqlite_error_code()==Some(rusqlite::ErrorCode::OperationInterrupted))
        );
    }
    assert!(ticks.load(Ordering::Relaxed) > 1);
    assert_eq!(index.count(&FactFilter::relation("R")).unwrap(), 10000);
}
#[test]
fn raw_values_preserve_deep_containers_and_float_boundaries() {
    for value in [
        -0.,
        f64::from_bits(1),
        f64::MIN_POSITIVE,
        f64::MAX,
        f64::from_bits(0x8000000000000001),
    ] {
        let text = ken_program::value::float_hex(value);
        assert_eq!(parse_float_hex(&text).unwrap().to_bits(), value.to_bits());
    }
    let raw = serde_json::value::RawValue::from_string(format!(
        "{}1267650600228229401496703205376{}",
        "[".repeat(150),
        "]".repeat(150)
    ))
    .unwrap();
    let value = V::parse(&raw).unwrap();
    let mut store = StructuralStore::open(None, None).unwrap();
    let graph = publish(&mut store, "deep", &empty());
    let values = GraphValues::new(store.connection(), graph);
    let id = values.put(&value).unwrap();
    assert_eq!(values.get(id).unwrap(), value);
    assert_eq!(V::parse(&value.to_raw().unwrap()).unwrap(), value);
}
#[test]
fn normalization_keeps_scalar_families_and_exact_python_position_keys() {
    #[derive(serde::Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    #[derive(serde::Deserialize)]
    struct Case {
        name: String,
        input: StructuralIr,
        query: StructuralIr,
    }
    let mut text = String::new();
    let bytes = include_bytes!("fixtures/query-edge-reference.json.gz");
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "955a923fe182646e8f7964c59dee4a38a58be72341a3b3e74391f5b343018fa8"
    );
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let data: Corpus = serde_json::from_str(&text).unwrap();
    assert_eq!(data.cases.len(), 13);
    for case in data.cases {
        let mut got = serde_json::to_value(normalize_query_graph(&case.input).unwrap()).unwrap();
        let mut want = serde_json::to_value(case.query).unwrap();
        sorted_facts(&mut got);
        sorted_facts(&mut want);
        assert_eq!(got, want, "{}", case.name);
    }
}
#[test]
fn missing_owner_fallbacks_do_not_become_false_ownership_cycles() {
    let mut q = empty();
    q.operations.push(ken_program::Operation {
        id: "orphan".into(),
        kind: "CALL".into(),
        native_kind: "call".into(),
        parent: None,
        role: "value".into(),
        start: 0,
        end: 1,
        line: 1,
        owner: "missing".into(),
        attrs: Default::default(),
    });
    q.facts.push(ken_program::Fact {
        subject: "missing".into(),
        relation: "INSTANCE_RECEIVER".into(),
        object: "orphan".into(),
        attrs: Default::default(),
        evidence: vec![],
    });
    let mut store = StructuralStore::open(None, None).unwrap();
    let graph = publish(&mut store, "orphan-owner", &q);
    let index = GraphIndex::open(&mut store, graph).unwrap();
    assert_eq!(index.source_view().node("orphan").unwrap(), None);
}
#[test]
fn review_long_reader_survives_busy_snapshot_renewal_after_writer_commit() {
    let temp = tempfile::tempdir().unwrap();
    let db = temp.path().join("reader-renewal.sqlite");
    let mut reader = StructuralStore::open(Some(&db), None).unwrap();
    let mut q = empty();
    q.facts = (0..3)
        .map(|i| ken_program::Fact {
            subject: i.to_string(),
            relation: "R".into(),
            object: "o".into(),
            attrs: Default::default(),
            evidence: vec![],
        })
        .collect();
    let graph = publish(&mut reader, "reader", &q);
    let mut writer = StructuralStore::open(Some(&db), None).unwrap();
    let index = GraphIndex::open(&mut reader, graph).unwrap();
    let mut scan = index.facts(&FactFilter::relation("R")).unwrap();
    let mut rows = scan.rows().unwrap();
    assert!(rows.next().unwrap().is_ok());
    publish(&mut writer, "concurrent", &empty());
    std::thread::sleep(std::time::Duration::from_millis(15100));
    let next = rows.next().unwrap();
    assert!(
        next.is_ok(),
        "reader lease renewal must defer a WAL snapshot upgrade: {next:?}"
    );
    assert!(rows.next().unwrap().is_ok());
    assert!(rows.next().is_none());
    drop(rows);
    drop(scan);
    drop(index);
    reader.renew(true).unwrap();
    reader
        .connection()
        .execute(
            "UPDATE k2_leases SET expires_ns=0 WHERE lease_id=?1",
            [reader.lease_id().unwrap()],
        )
        .unwrap();
    assert!(matches!(reader.renew(true), Err(StructuralError::Expired)));
}
#[test]
fn review_operation_overlay_publication_sql_work_scales_linearly() {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    fn measure(size: i64) -> usize {
        let mut q = empty();
        for i in 0..size {
            q.operations.push(ken_program::Operation {
                id: format!("op{i}"),
                kind: "CALL".into(),
                native_kind: "call_expression".into(),
                parent: None,
                role: "value".into(),
                start: i,
                end: i + 1,
                line: 1,
                owner: "owner".into(),
                attrs: Default::default(),
            });
            let mut attrs = ken_program::Attributes::new();
            for (k, v) in [
                ("kind", json!("call")),
                ("native_kind", json!("call_expression")),
                ("owner", json!("owner")),
                ("role", json!("value")),
                ("start_byte", json!(i)),
                ("end_byte", json!(i + 1)),
            ] {
                attrs.insert(k.into(), serde_json::value::to_raw_value(&v).unwrap());
            }
            q.facts.push(ken_program::Fact {
                subject: format!("op{i}"),
                relation: "OPERATION".into(),
                object: "CALL".into(),
                attrs,
                evidence: vec![],
            });
        }
        let mut store = StructuralStore::open(None, None).unwrap();
        let ticks = Arc::new(AtomicUsize::new(0));
        let count = ticks.clone();
        store
            .connection()
            .progress_handler(
                100,
                Some(move || {
                    count.fetch_add(1, Ordering::Relaxed);
                    false
                }),
            )
            .unwrap();
        publish(&mut store, "scale", &q);
        store
            .connection()
            .progress_handler(0, None::<fn() -> bool>)
            .unwrap();
        ticks.load(Ordering::Relaxed)
    }
    let small = measure(1500);
    let large = measure(3000);
    eprintln!("publication SQL ticks (100 instructions): {small} -> {large}");
    assert!(small > 0);
    assert!(
        large < small * 3,
        "doubling operation count must stay below quadratic work: {small} -> {large}"
    );
}
#[test]
fn review_syntax_publication_is_cancellable_between_bounded_commits() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("syntax-batches.sqlite");
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    let snapshot = store.publish(&[], None, "syntax", true).unwrap();
    let observer = rusqlite::Connection::open(&path).unwrap();
    let mut q = empty();
    q.operations = (0..40000)
        .map(|i| ken_program::Operation {
            id: format!("syntax{i}"),
            kind: "BLOCK".into(),
            native_kind: "block".into(),
            parent: None,
            role: "body".into(),
            start: i,
            end: i + 1,
            line: 1,
            owner: "owner".into(),
            attrs: Default::default(),
        })
        .collect();
    let mut observed = 0;
    let result = publish_graph_owned(&mut store, snapshot, "syntax", q, &V::Null, &mut || {
        let count: i64 =
            observer.query_row("SELECT count(*) FROM k2_graph_syntax", [], |r| r.get(0))?;
        observed = observed.max(count);
        if count > 0 {
            Err(StructuralError::Invalid("cancel syntax construction"))
        } else {
            Ok(())
        }
    });
    assert!(result.unwrap_err().to_string().contains("cancel syntax"));
    assert!(observed > 0);
    assert!(
        observed <= 32768,
        "one syntax transaction published {observed} rows before cancellation"
    );
    for table in ["k2_graphs", "k2_graph_syntax_ready", "k2_graph_syntax"] {
        assert_eq!(
            store
                .connection()
                .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
}
#[test]
fn review_capability_and_relation_inventories_respect_publication_batches() {
    let mut maxima = Vec::new();
    for table in ["k2_graph_capabilities", "k2_graph_relations"] {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("inventories.sqlite");
        let mut store = StructuralStore::open(Some(&path), None).unwrap();
        let snapshot = store.publish(&[], None, "inventory", true).unwrap();
        let observer = rusqlite::Connection::open(&path).unwrap();
        let mut q = empty();
        if table == "k2_graph_capabilities" {
            q.capabilities = (0..40000)
                .map(|i| format!("complete:owner{i}:HAS_CALL"))
                .collect();
        } else {
            q.facts = (0..40000)
                .map(|i| ken_program::Fact {
                    subject: "s".into(),
                    relation: format!("R{i}"),
                    object: "o".into(),
                    attrs: Default::default(),
                    evidence: vec![],
                })
                .collect();
        }
        let mut observed = 0;
        let result = publish_graph_owned(
            &mut store,
            snapshot,
            "inventories",
            q,
            &V::Null,
            &mut || {
                let count: i64 =
                    observer
                        .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))?;
                observed = observed.max(count);
                if count > 0 {
                    Err(StructuralError::Invalid("cancel inventory"))
                } else {
                    Ok(())
                }
            },
        );
        assert!(result.unwrap_err().to_string().contains("cancel inventory"));
        assert!(observed > 0);
        maxima.push((table, observed));
        assert_eq!(
            store
                .connection()
                .query_row("SELECT count(*) FROM k2_graphs", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
    assert!(
        maxima.iter().all(|(_, n)| *n <= 32768),
        "inventory rows in one transaction: {maxima:?}"
    );
}
#[test]
fn review_minimum_overlay_identity_reports_missing_instead_of_overflowing() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let graph = publish(&mut store, "minimum-overlay", &empty());
    let values = GraphValues::new(store.connection(), graph);
    assert!(values.get(i64::MIN).is_err());
}
#[test]
fn review_legacy_syntax_preparation_is_atomic_and_checks_cancellation() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let mut q = empty();
    q.operations = (0..2000)
        .map(|i| ken_program::Operation {
            id: format!("node{i}"),
            kind: "BLOCK".into(),
            native_kind: "block".into(),
            parent: (i > 0).then(|| format!("node{}", i - 1)),
            role: "body".into(),
            start: 0,
            end: 1,
            line: 1,
            owner: "owner".into(),
            attrs: Default::default(),
        })
        .collect();
    let graph = publish(&mut store, "legacy-syntax", &q);
    store
        .connection()
        .execute(
            "DELETE FROM k2_graph_syntax_ready WHERE graph_id=?1",
            [graph],
        )
        .unwrap();
    let mut checks = 0;
    let result = GraphIndex::open_with_check(&mut store, graph, || {
        checks += 1;
        if checks == 13 {
            Err(StructuralError::Invalid("cancel legacy syntax"))
        } else {
            Ok(())
        }
    });
    assert!(matches!(
        result,
        Err(StructuralError::Invalid("cancel legacy syntax"))
    ));
    assert_eq!(checks, 13);
    assert_eq!(
        store
            .connection()
            .query_row("SELECT count(*) FROM k2_graph_syntax_ready", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
    assert_eq!(
        store
            .connection()
            .query_row(
                "SELECT ready FROM k2_graph_publications WHERE graph_id=?1",
                [graph],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        1
    );
    let index = GraphIndex::open(&mut store, graph).unwrap();
    assert_eq!(
        index.syntax_bounds("node0").unwrap(),
        Some((0, 2000, "node1999".into()))
    );
}
