use flate2::read::GzDecoder;
use ken_program::{StructuralIr, value::GraphValue as V};
use ken_query::execution::{
    Cancellation, Execution, ExecutionOptions, MemoryGraph, Planning, QueryOutcome,
};
use ken_store::structural::{
    StructuralStore,
    graph::{GraphIndex, publish_graph},
};
use ken_structural::{GraphSnapshot, execute_query};
use serde_json::{Value, json};
use std::{collections::BTreeMap, io::Read};
#[path = "../../ken-query/tests/support/execution_fixture.rs"]
mod fixture;
fn corpus() -> Value {
    let mut s = String::new();
    GzDecoder::new(
        &include_bytes!("../../ken-query/tests/fixtures/execution-reference.json.gz")[..],
    )
    .read_to_string(&mut s)
    .unwrap();
    let mut corpus: Value = serde_json::from_str(&s).unwrap();
    s.clear();
    GzDecoder::new(&include_bytes!("../../ken-query/tests/fixtures/execution-boundaries-reference.json.gz")[..]).read_to_string(&mut s).unwrap();
    let extra: Value = serde_json::from_str(&s).unwrap();
    corpus["cases"]
        .as_array_mut()
        .unwrap()
        .extend(extra["cases"].as_array().unwrap().iter().cloned());
    corpus
}
#[test]
fn source_operators_match_original_on_indexed_sqlite_reads() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let mut graphs = BTreeMap::new();
    let mut errors = vec![];
    for bytes in [
        &include_bytes!("../../ken-query/tests/fixtures/source-runtime-reference.json.gz")[..],
        &include_bytes!("../../ken-query/tests/fixtures/source-operations-reference.json.gz")[..],
    ] {
        let mut text = String::new();
        GzDecoder::new(bytes).read_to_string(&mut text).unwrap();
        let data: Value = serde_json::from_str(&text).unwrap();
        for c in data["cases"].as_array().unwrap() {
            let key = c["graph"].to_string();
            let ir = StructuralIr::from_json(&key).unwrap();
            let id = if let Some(id) = graphs.get(&key) {
                *id
            } else {
                let id = publish(&mut store, &format!("source{}", graphs.len()), &ir);
                graphs.insert(key, id);
                id
            };
            let mut index = GraphIndex::open(&mut store, id).unwrap();
            let options: ExecutionOptions = serde_json::from_value(c["options"].clone()).unwrap();
            match execute_query(&mut index, &fixture::query(&c["query"]), options) {
                Ok(result) => {
                    let mut got = serde_json::to_value(result).unwrap();
                    got.as_object_mut().unwrap().remove("stats");
                    if got != c["expected"] {
                        errors.push(format!("{}: {got} != {}", c["name"], c["expected"]));
                    }
                }
                Err(e) => errors.push(format!("{}: {e}", c["name"])),
            }
        }
    }
    assert!(
        errors.is_empty(),
        "{} failures: {}",
        errors.len(),
        errors
            .iter()
            .take(12)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}
fn publish(store: &mut StructuralStore, key: &str, ir: &StructuralIr) -> i64 {
    let snapshot = store
        .publish(&[], store.current().unwrap(), key, true)
        .unwrap();
    let metadata = V::parse(
        &serde_json::value::RawValue::from_string(json!({"relations":ir.relations}).to_string())
            .unwrap(),
    )
    .unwrap();
    publish_graph(store, snapshot, key, ir, &metadata, &mut || Ok(())).unwrap()
}
fn detached(outcome: QueryOutcome) -> Value {
    let mut v = serde_json::to_value(outcome).unwrap();
    v["stats"].as_object_mut().unwrap().remove("elapsed_ms");
    v
}
#[test]
fn persisted_snapshot_executor_matches_memory_and_original_evidence() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("execution.sqlite");
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    let f = corpus();
    let mut graphs = BTreeMap::new();
    for c in f["cases"].as_array().unwrap() {
        let key = c["graph"].to_string();
        let ir = StructuralIr::from_json(&key).unwrap();
        let id = if let Some(id) = graphs.get(&key) {
            *id
        } else {
            let id = publish(&mut store, &format!("graph{}", graphs.len()), &ir);
            graphs.insert(key, id);
            id
        };
        let mut options: ExecutionOptions = serde_json::from_value(c["options"].clone()).unwrap();
        if c["options"].get("planning").is_none() {
            options.planning = Planning::AuthorOrder;
        }
        let q = fixture::query(&c["query"]);
        let mut index = GraphIndex::open(&mut store, id).unwrap();
        let actual = execute_query(&mut index, &q, options).unwrap();
        let mut got = detached(actual);
        let mut want = fixture::expected(c);
        if c["options"]["planning"] == "selective" {
            for k in ["states", "rows_examined"] {
                got["stats"].as_object_mut().unwrap().remove(k);
                want["stats"].as_object_mut().unwrap().remove(k);
            }
        }
        assert_eq!(got, want, "{}", c["name"]);
    }
    drop(store);
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    let id = *graphs.values().next().unwrap();
    let mut index = GraphIndex::open(&mut store, id).unwrap();
    let q = fixture::query(&json!({"name":"again","nodes":[],"exports":{},"definitions":{}}));
    let result = execute_query(&mut index, &q, Default::default()).unwrap();
    assert!(result.complete);
    drop(index);
    drop(store);
    assert_eq!(result.matches.len(), 1);
}
#[test]
fn cancellation_and_sql_vm_interruption_do_not_escape_or_poison_later_queries() {
    let f = corpus();
    let mut ir = StructuralIr::from_json(&f["cases"][0]["graph"].to_string()).unwrap();
    ir.facts.extend((0..5000).map(|n| ken_program::Fact {
        subject: "f".into(),
        relation: "TYPE".into(),
        object: format!("v{n}"),
        attrs: Default::default(),
        evidence: vec![],
    }));
    ir.relations.insert("TYPE".into());
    let dir = tempfile::tempdir().unwrap();
    let mut store =
        StructuralStore::open(Some(&dir.path().join("interrupt.sqlite")), None).unwrap();
    let id = publish(&mut store, "interrupt", &ir);
    let mut index = GraphIndex::open(&mut store, id).unwrap();
    let tree = ken_query::parse(
        "language \"kql/2\";module vm;query q{edge TYPE($x,$y);select $x,$y;}",
        "vm",
        Default::default(),
    )
    .unwrap();
    let compiled = ken_query::compile_relational(&tree, None).unwrap();
    let q = compiled.relational.unwrap();
    let token = Cancellation::default();
    token.cancel();
    let options = ExecutionOptions {
        cancellation: token,
        ..Default::default()
    };
    let result = execute_query(&mut index, &q, options).unwrap();
    assert!(!result.complete);
    assert_eq!(result.unknown, ["budget:cancelled"]);
    let token = Cancellation::default();
    let execution = Execution::new(ExecutionOptions {
        cancellation: token.clone(),
        ..Default::default()
    })
    .unwrap();
    let interruption = execution.interruption();
    let result = {
        let mut initial = true;
        let scope = index
            .execution(move || {
                if std::mem::take(&mut initial) {
                    false
                } else {
                    token.cancel();
                    true
                }
            })
            .unwrap();
        let graph = GraphSnapshot::new(&scope, interruption);
        execution.execute(&graph, &q).unwrap()
    };
    assert!(!result.complete);
    assert_eq!(result.unknown, ["budget:cancelled"]);
    let empty = fixture::query(&json!({"name":"empty","nodes":[],"exports":{},"definitions":{}}));
    assert!(
        execute_query(&mut index, &empty, Default::default())
            .unwrap()
            .complete
    );
    let mut options = ExecutionOptions::default();
    options.budget.max_matches = Some(1);
    let result = execute_query(&mut index, &q, options).unwrap();
    assert!(!result.complete);
    assert_eq!(result.matches.len(), 1);
    assert_eq!(result.unknown, ["budget:max_matches"]);
    let memory = MemoryGraph::new(&ir).unwrap();
    let mut options = ExecutionOptions::default();
    options.budget.max_matches = Some(1);
    assert_eq!(
        detached(
            Execution::new(options)
                .unwrap()
                .execute(&memory, &q)
                .unwrap()
        ),
        detached(result)
    );
}

#[test]
fn live_python_acquisition_compilation_and_query_execution_form_one_native_path() {
    use ken_core::project::{DiscoveryContext, ProjectPaths};
    use ken_store::artifact_cache::ArtifactCache;
    use ken_structural::{NativeFrontend, ProjectAcquisition, ProjectBuilder, ScanLimits};
    use std::path::{Path, PathBuf};
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::write(root.join("service.py"),"class Service:\n    def ping(self):\n        return 1\n    def other(self):\n        return 2\n").unwrap();
    let catalog = ken_syntax::GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap();
    let frontend = NativeFrontend::new(&catalog);
    let context = DiscoveryContext {
        cwd: root.into(),
        forced_root: None,
        home: None,
    };
    let mut builder = ProjectBuilder::new(
        ProjectPaths::at(root, &context).unwrap(),
        context,
        &frontend,
        ArtifactCache::open(&root.join(".ken/source-cache.sqlite"), 500.).unwrap(),
    );
    let db = root.join(".ken/queries.sqlite");
    let mut acquired = ProjectAcquisition::new(&mut builder, &db, true)
        .acquire(Path::new("."), ScanLimits::default(), || Ok(()))
        .unwrap();
    let tree = ken_query::parse(
        "language \"kql/2\";module live;query q{class $c{method $m{name:\"ping\";}}select $c,$m;}",
        "live",
        Default::default(),
    )
    .unwrap();
    let compiled = ken_query::compile(
        &tree,
        None,
        &BTreeMap::new(),
        ken_query::BackendPreference::Relational,
    )
    .unwrap();
    let mut index = acquired.index().unwrap();
    let result = execute_query(
        &mut index,
        compiled.relational.as_ref().unwrap(),
        Default::default(),
    )
    .unwrap();
    assert!(result.complete);
    assert!(result.unknown.is_empty());
    assert_eq!(result.matches.len(), 1);
    assert_eq!(result.matches[0].status, "structural_match");
    assert!(result.matches[0].bindings.contains_key("$c"));
    assert!(result.matches[0].bindings.contains_key("$m"));
}

#[test]
fn typed_numeric_boolean_and_whitespace_attributes_match_in_sql_facts_and_where() {
    let mut ir = StructuralIr::from_json(&corpus()["cases"][0]["graph"].to_string()).unwrap();
    ir.entities.clear();
    ir.facts.clear();
    for (id, raw) in [
        ("boolean", "true"),
        ("space", "\" 11.5 \""),
        ("decimal", "\"١١.٥\""),
        ("underscore", "\"1_1.5\""),
    ] {
        ir.facts.push(ken_program::Fact {
            subject: id.into(),
            relation: "ENTITY".into(),
            object: "CLASS".into(),
            attrs: BTreeMap::from([(
                "number".into(),
                serde_json::value::RawValue::from_string(raw.into()).unwrap(),
            )]),
            evidence: vec![],
        });
    }
    let dir = tempfile::tempdir().unwrap();
    let mut store = StructuralStore::open(Some(&dir.path().join("numeric.sqlite")), None).unwrap();
    let id = publish(&mut store, "numeric", &ir);
    let mut index = GraphIndex::open(&mut store, id).unwrap();
    for is_where in [false, true] {
        let mut nodes = vec![
            json!({"kind":"fact","value":{"subject":"$x","relation":"ENTITY","object":{"literal":"CLASS"},"attrs":if is_where{json!([])}else{json!([["number",">","0"]])}},"children":[]}),
        ];
        if is_where {
            nodes.push(json!({"kind":"where","value":["$x.number",">","0"],"children":[]}));
        }
        let q = fixture::query(
            &json!({"name":"numeric","nodes":nodes,"exports":{"x":"$x"},"definitions":{}}),
        );
        let result = execute_query(&mut index, &q, Default::default()).unwrap();
        assert!(result.complete);
        assert_eq!(result.matches.len(), 4);
    }
}
