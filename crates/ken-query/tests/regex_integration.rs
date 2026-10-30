//! Qualified matcher behavior through the actual indexed, graph and BODY owners.
use flate2::read::GzDecoder;
use ken_program::{StructuralIr, value::GraphValue};
use ken_query::{
    BodyPattern,
    ast::Expr,
    execution::{
        Execution, ExecutionOptions, MemoryGraph,
        body_runtime::{BodyCursor, BodyServices},
        indexed_runtime::{IndexedExecution, IndexedOptions},
        regex_runtime::{Dialect, Pattern},
        values::{Bindings, SourceNode, Value},
    },
    relational::{PlanValue, RelationalEdge, RelationalNode, RelationalQuery, Term},
};
use serde_json::{Value as Json, json};
use std::{collections::BTreeMap, io::Read, sync::Arc};
fn empty() -> MemoryGraph {
    MemoryGraph::new(&StructuralIr::from_json(r#"{"path":"empty","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":[]}"#).unwrap()).unwrap()
}
fn indexed(
    source: &str,
    options: IndexedOptions,
) -> ken_query::execution::Result<ken_query::execution::indexed_runtime::IndexedOutcome> {
    let tree = ken_query::parse(source, "regex-context", Default::default()).unwrap();
    let p = ken_query::compile_indexed(&tree, None).unwrap();
    IndexedExecution::new(options)?.execute(&empty(), &p)
}
#[test]
fn indexed_public_matches_uses_regex_dialect_and_lossless_text() {
    let source = r#"language "kql/2";module regex_context;query q{select "b" matches /a{e<=1}/,"aa" matches /a++a/,"ab" matches /(?:ab|a)b/,"٣" matches /\d/,"ı" matches /i/i,"İ" matches /i/i,"\ud800" matches /./,"\ud800" matches /\ud800/,"" matches /a{1000000000}/;}"#;
    let out = indexed(source, Default::default()).unwrap();
    assert!(out.complete);
    assert_eq!(
        out.rows,
        vec![
            vec![true, false, true, true, false, true, true, true, false]
                .into_iter()
                .map(Value::boolean)
                .collect::<Vec<_>>()
        ]
    );
    let options = IndexedOptions::default();
    options.cancellation.cancel();
    let out = indexed(source, options).unwrap();
    assert!(!out.complete);
    assert_eq!(out.reason.as_deref(), Some("cancelled"));
    assert!(out.rows.is_empty());
}
fn graph_query(pattern: &str) -> RelationalQuery {
    RelationalQuery {
        name: "regex".into(),
        nodes: Arc::new(vec![RelationalNode {
            kind: "fact".into(),
            value: PlanValue::Edge(RelationalEdge {
                mode: "require".into(),
                subject: Term::Text("$x".into()),
                relation: "ENTITY".into(),
                object: Term::Text("_".into()),
                attrs: vec![("name".into(), "regex".into(), pattern.into())],
            }),
            children: vec![],
        }]),
        exports: [("x".into(), "$x".into())].into_iter().collect(),
        definitions: Default::default(),
    }
}
fn named_graph(raw_text: &str) -> MemoryGraph {
    let raw = format!(
        r#"{{"path":"names","language":"mixed","version":"1.88.0","view":"query","entities":{{}},"operations":[],"facts":[{{"subject":"node","relation":"ENTITY","object":"CLASS","attrs":{{"name":{raw_text}}},"evidence":[]}}],"capabilities":[],"diagnostics":[],"relations":["ENTITY"]}}"#
    );
    MemoryGraph::new(&StructuralIr::from_json(&raw).unwrap()).unwrap()
}
#[test]
fn graph_comparison_supports_accepted_backtracking_unicode_fuzzy_and_surrogates() {
    for (pattern, raw, want) in [
        ("a{e<=1}", r#""b""#, true),
        ("a++a", r#""aa""#, false),
        ("(?>ab|a)b", r#""ab""#, false),
        ("(?iV1)ss", r#""ß""#, true),
        ("(?r)foo", r#""foo""#, true),
        (r"\p{Cs}", r#""\ud800""#, true),
    ] {
        let result = Execution::new(Default::default())
            .unwrap()
            .execute(&named_graph(raw), &graph_query(pattern))
            .unwrap();
        assert!(result.complete, "{pattern}");
        assert_eq!(!result.matches.is_empty(), want, "{pattern}");
    }
    let options = ExecutionOptions::default();
    options.cancellation.cancel();
    let result = Execution::new(options)
        .unwrap()
        .execute(&named_graph(r#""a""#), &graph_query("a"))
        .unwrap();
    assert!(!result.complete);
    assert!(result.matches.is_empty());
}
fn body_fixture() -> Json {
    let mut text = String::new();
    GzDecoder::new(&include_bytes!("fixtures/body-runtime-reference.json.gz")[..])
        .read_to_string(&mut text)
        .unwrap();
    serde_json::from_str(&text).unwrap()
}
struct Services;
impl BodyServices for Services {
    fn check(&mut self) -> ken_query::execution::Result<()> {
        Ok(())
    }
    fn evaluate(&mut self, e: &Expr, b: &Bindings) -> ken_query::execution::Result<Value> {
        if e.kind == "role" {
            Ok(b.get(&e.value)
                .cloned()
                .unwrap_or_else(|| Value::unknown("unbound")))
        } else {
            Value::literal(&e.value)
        }
    }
    fn regex(&mut self, text: &str, e: &Expr) -> ken_query::execution::Result<bool> {
        let (pattern, flags) = e
            .value
            .strip_prefix('/')
            .and_then(|s| s.rsplit_once('/'))
            .unwrap();
        Pattern::compile(pattern, flags, Dialect::Regex, &mut || self.check())?
            .is_match(&text.into(), &mut || self.check())
    }
}
#[test]
fn body_call_name_has_its_own_stdlib_hook_and_only_i_flag() {
    let fixture = body_fixture();
    let case = fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "straight/body-direct/22/0/0")
        .unwrap();
    for (raw, name, want) in [
        ("/i/i", "ı", true),
        ("/./s", "\n", false),
        ("/^a$/m", "x\na\nx", false),
    ] {
        let mut record = fixture["graphs"][case["graph"].as_u64().unwrap() as usize].clone();
        let id = case["bindings"]["f"]["value"]["local_id"].as_str().unwrap();
        record["graph"]["entities"][id]["name"] = json!(name);
        record["graph"]["entities"][id]["attrs"]["name"] = json!(name);
        for fact in record["graph"]["facts"].as_array_mut().unwrap() {
            if fact["subject"] == id && fact["relation"] == "ENTITY" {
                fact["attrs"]["name"] = json!(name);
            }
        }
        for node in record["nodes"].as_array_mut().unwrap() {
            if node["local_id"] == id {
                node["name"] = json!(name);
            }
        }
        record["properties"][id]["name"] = json!(name);
        let ir = StructuralIr::from_json(&record["graph"].to_string()).unwrap();
        let nodes = serde_json::from_value::<Vec<SourceNode>>(record["nodes"].clone()).unwrap();
        let properties = record["properties"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(id, values)| {
                (
                    id.clone(),
                    values
                        .as_object()
                        .unwrap()
                        .iter()
                        .map(|(key, value)| {
                            let raw = serde_json::value::RawValue::from_string(value.to_string())
                                .unwrap();
                            (key.clone(), GraphValue::parse(&raw).unwrap())
                        })
                        .collect(),
                )
            })
            .collect();
        let graph = MemoryGraph::new(&ir).unwrap().with_source_nodes(
            nodes,
            properties,
            BTreeMap::new(),
            true,
        );
        let mut pattern = case["pattern"].clone();
        pattern["clauses"][0]["blocks"][0][0]["expressions"][0]["value"] = json!(raw);
        let pattern: BodyPattern = serde_json::from_value(pattern).unwrap();
        let bindings = case["bindings"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(role, value)| {
                (
                    role.clone(),
                    Value::Node(Arc::new(
                        serde_json::from_value(value["value"].clone()).unwrap(),
                    )),
                )
            })
            .collect();
        let mut cursor = BodyCursor::new(&graph, Arc::new(pattern), bindings);
        let first = cursor.next(&mut Services).unwrap();
        assert_eq!(first.is_some(), want, "{raw} on {name:?}");
        if let Some(hit) = first {
            assert!(!hit.unknown);
        }
    }
}
