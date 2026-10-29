//! Cancellation before acquisition must not copy an already rejected unit payload.
use ken_program::{ProgramError, StructuralIr, project::link_nominal_with_check};
use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
};
thread_local! {static ALLOCATED:Cell<usize>=const{Cell::new(0)}; static ALLOCATIONS:Cell<usize>=const{Cell::new(0)};}
struct AllocationCounter;
#[global_allocator]
static ALLOCATOR: AllocationCounter = AllocationCounter;
unsafe impl GlobalAlloc for AllocationCounter {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let _ = ALLOCATED.try_with(|count| count.set(count.get().saturating_add(layout.size())));
        let _ = ALLOCATIONS.try_with(|count| count.set(count.get().saturating_add(1)));
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        let _ = ALLOCATED.try_with(|count| count.set(count.get().saturating_add(size)));
        let _ = ALLOCATIONS.try_with(|count| count.set(count.get().saturating_add(1)));
        unsafe { System.realloc(ptr, layout, size) }
    }
}
#[test]
fn first_cancel_checkpoint_precedes_unit_payload_copy() {
    let ir=StructuralIr::from_json(r#"{"path":"unit.py","language":"python","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"version":"1.88.0"}"#).unwrap();
    let mut ir = ir;
    ir.diagnostics.push("e".repeat(2 * 1024 * 1024));
    let units = [ir];
    let before = ALLOCATED.with(Cell::get);
    let mut at_check = 0;
    let result = link_nominal_with_check(&units, || {
        at_check = ALLOCATED.with(Cell::get);
        Err(ProgramError::Invalid("already cancelled"))
    });
    assert!(result.is_err());
    assert!(
        at_check - before < 1024,
        "copied {} bytes before first cancellation checkpoint",
        at_check - before
    );
}

fn receiver_rebinding_unit(count: usize) -> StructuralIr {
    use ken_program::{Entity, Fact, Operation};
    use serde_json::{json, value::to_raw_value};
    let mut unit = StructuralIr::from_json(r#"{"path":"versions.py","language":"python","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"version":"1.88.0"}"#).unwrap();
    let attrs = |v: serde_json::Value| {
        v.as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), to_raw_value(v).unwrap()))
            .collect()
    };
    for (id, kind) in [
        ("versions.py::module", "MODULE"),
        ("owner", "CALLABLE"),
        ("binding", "STORAGE"),
    ] {
        unit.entities.push((
            id.into(),
            Entity {
                id: id.into(),
                kind: kind.into(),
                name: id.into(),
                path: unit.path.clone(),
                line: 1,
                end_line: 1,
                attrs: attrs(json!({"language":"python","declared":true})),
            },
        ));
    }
    for (id, kind, native, parent, role) in [
        ("function", "FUNCTION", "function_definition", None, ""),
        ("body", "BLOCK", "block", Some("function"), "body"),
    ] {
        unit.operations.push(Operation {
            id: id.into(),
            kind: kind.into(),
            native_kind: native.into(),
            parent: parent.map(Into::into),
            role: role.into(),
            start: 0,
            end: count as i64 * 4 + 4,
            line: 1,
            owner: "owner".into(),
            attrs: Default::default(),
        });
    }
    unit.facts.push(Fact {
        subject: "owner".into(),
        relation: "DECLARES".into(),
        object: "binding".into(),
        attrs: Default::default(),
        evidence: vec![],
    });
    for i in 0..count {
        let write = format!("write-{i}");
        let call = format!("call-{i}");
        let start = i as i64 * 4;
        unit.operations.push(Operation {
            id: write.clone(),
            kind: "ASSIGN".into(),
            native_kind: "assignment".into(),
            parent: Some("body".into()),
            role: "".into(),
            start,
            end: start + 1,
            line: 1,
            owner: "owner".into(),
            attrs: attrs(json!({"tokens":["="],"execution":"possible"})),
        });
        unit.entities.push((call.clone(),Entity{id:call.clone(),kind:"CALL".into(),name:"touch".into(),path:unit.path.clone(),line:1,end_line:1,attrs:attrs(json!({"language":"python","name":"touch","owner":"owner","start_byte":start+2,"end_byte":start+3}))}));
        for (subject, relation, object) in [
            (write.as_str(), "ASSIGNMENT_TARGET", "binding"),
            (write.as_str(), "ASSIGNMENT_VALUE", "binding"),
            ("owner", "HAS_CALL", call.as_str()),
            (call.as_str(), "RECEIVER", "binding"),
            (call.as_str(), "CALLEE_NAME", "touch"),
        ] {
            unit.facts.push(Fact {
                subject: subject.into(),
                relation: relation.into(),
                object: object.into(),
                attrs: Default::default(),
                evidence: vec![],
            });
        }
    }
    unit
}
#[test]
fn receiver_write_versions_do_not_copy_the_entire_history_per_call() {
    let count = 2000;
    let unit = receiver_rebinding_unit(count);
    let before = ALLOCATIONS.with(Cell::get);
    let graph = ken_program::project::link_project_owned(vec![unit]).unwrap();
    let allocations = ALLOCATIONS.with(Cell::get) - before;
    assert!(
        allocations < count * 1000,
        "{allocations} allocations for {count} rebindings/calls; repeated history copies are quadratic"
    );
    let versions = graph
        .facts
        .iter()
        .filter(|f| f.relation == "RECEIVER_BINDING_VERSION")
        .collect::<Vec<_>>();
    assert_eq!(versions.len(), count);
    for i in 0..count {
        let call = format!("call-{i}");
        let write = format!("write-{i}");
        assert!(
            versions
                .iter()
                .any(|f| f.subject == call && f.object == write)
        );
    }
    assert!(
        !graph
            .facts
            .iter()
            .any(|f| f.relation == "RECEIVER_UNREPLACED")
    );
}

fn test_attrs(v: serde_json::Value) -> ken_program::Attributes {
    v.as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), serde_json::value::to_raw_value(v).unwrap()))
        .collect()
}
fn test_fact(
    unit: &mut StructuralIr,
    subject: &str,
    relation: &str,
    object: &str,
    attrs: serde_json::Value,
) {
    unit.facts.push(ken_program::Fact {
        subject: subject.into(),
        relation: relation.into(),
        object: object.into(),
        attrs: test_attrs(attrs),
        evidence: vec![],
    });
}
fn test_entity(
    unit: &mut StructuralIr,
    id: &str,
    kind: &str,
    name: &str,
    attrs: serde_json::Value,
) {
    unit.entities.push((
        id.into(),
        ken_program::Entity {
            id: id.into(),
            kind: kind.into(),
            name: name.into(),
            path: unit.path.clone(),
            line: 1,
            end_line: 1,
            attrs: test_attrs(attrs),
        },
    ));
}
#[test]
fn many_possible_contexts_do_not_copy_the_context_set_per_effect() {
    use serde_json::json;
    let count = 2000;
    let mut unit = receiver_rebinding_unit(0);
    test_entity(
        &mut unit,
        "threading",
        "STORAGE",
        "threading",
        json!({"language":"python","native_kind":"identifier"}),
    );
    test_fact(
        &mut unit,
        "versions.py::module",
        "IMPORT_SYNTAX",
        "import threading",
        json!({"language":"python"}),
    );
    for i in 0..count {
        let call = format!("thread-{i}");
        test_entity(
            &mut unit,
            &call,
            "CALL",
            "Thread",
            json!({"language":"python","owner":"owner","name":"Thread","start_byte":i+1}),
        );
        test_fact(&mut unit, "owner", "HAS_CALL", &call, json!({}));
        test_fact(&mut unit, &call, "CALLEE_NAME", "Thread", json!({}));
        test_fact(&mut unit, &call, "RECEIVER", "threading", json!({}));
        test_fact(&mut unit, "binding", "ASSIGNED_FROM", &call, json!({}));
    }
    test_entity(
        &mut unit,
        "join",
        "CALL",
        "join",
        json!({"language":"python","owner":"owner","name":"join","start_byte":count+2}),
    );
    test_fact(&mut unit, "owner", "HAS_CALL", "join", json!({}));
    test_fact(&mut unit, "join", "CALLEE_NAME", "join", json!({}));
    test_fact(&mut unit, "join", "RECEIVER", "binding", json!({}));
    let before = ALLOCATIONS.with(Cell::get);
    let graph = ken_program::project::link_project_owned(vec![unit]).unwrap();
    let allocations = ALLOCATIONS.with(Cell::get) - before;
    assert!(
        allocations < count * 1000,
        "{allocations} allocations for {count} possible contexts; repeated set copies are quadratic"
    );
    assert_eq!(
        graph
            .facts
            .iter()
            .filter(|f| f.relation == "CREATES_CONTEXT")
            .count(),
        count
    );
    let effects = graph
        .facts
        .iter()
        .filter(|f| f.relation == "MAY_WAITS_FOR" && f.subject == "join")
        .map(|f| f.object.as_str())
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(effects.len(), count);
    assert!(!graph.facts.iter().any(|f| f.relation == "WAITS_FOR"));
}
#[test]
fn wide_positional_and_named_calls_use_indexed_parameter_matching() {
    use serde_json::json;
    let count = 1500;
    let mut unit = receiver_rebinding_unit(0);
    test_entity(
        &mut unit,
        "target",
        "CALLABLE",
        "target",
        json!({"language":"python"}),
    );
    test_fact(&mut unit, "target", "OWNED_BY", "owner", json!({}));
    for (call, kind) in [("positional", "positional"), ("named", "named")] {
        test_entity(
            &mut unit,
            call,
            "CALL",
            call,
            json!({"language":"python","owner":"owner","name":"target","start_byte":3}),
        );
        test_fact(&mut unit, "owner", "HAS_CALL", call, json!({}));
        test_fact(&mut unit, call, "CALLEE_NAME", "target", json!({}));
        test_fact(&mut unit, call, "CALLEE_VALUE", "target", json!({}));
        for i in 0..count {
            test_fact(
                &mut unit,
                call,
                "ARGUMENT",
                "binding",
                json!({"kind":kind,"position":i,"name":format!("p{i}")}),
            );
        }
    }
    for i in 0..count {
        let parameter = format!("p{i}");
        test_entity(
            &mut unit,
            &parameter,
            "PARAMETER",
            &parameter,
            json!({"language":"python"}),
        );
        test_fact(
            &mut unit,
            "target",
            "HAS_PARAMETER",
            &parameter,
            json!({"receiver":false,"position":i,"kind":"positional","default":""}),
        );
    }
    let before = ALLOCATIONS.with(Cell::get);
    let graph = ken_program::project::link_project_owned(vec![unit]).unwrap();
    let allocations = ALLOCATIONS.with(Cell::get) - before;
    assert!(
        allocations < count * 1500,
        "{allocations} allocations for two {count}-argument calls; repeated matching is quadratic"
    );
    assert_eq!(
        graph
            .facts
            .iter()
            .filter(|f| f.relation == "BINDS_TO")
            .count(),
        2 * count
    );
    assert_eq!(
        graph
            .facts
            .iter()
            .filter(|f| f.relation == "CALL_BINDING")
            .count(),
        2 * count
    );
    assert!(
        graph
            .facts
            .iter()
            .filter(|f| f.relation == "BINDING_STATUS")
            .all(|f| f.object == "supported")
    );
}
