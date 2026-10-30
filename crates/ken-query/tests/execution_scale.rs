//! Measure rejected metadata allocation, excluding the caller-owned input.
use ken_query::{
    execution::{Execution, MemoryGraph},
    relational::{PlanValue, RelationalNode, RelationalQuery},
};
use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
    sync::Arc,
};
struct Counted;
thread_local! {static BYTES:Cell<Option<usize>>=const{Cell::new(None)};}
fn add(n: usize) {
    let _ = BYTES.try_with(|v| {
        if let Some(old) = v.get() {
            v.set(Some(old.saturating_add(n)))
        }
    });
}
unsafe impl GlobalAlloc for Counted {
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        add(l.size());
        unsafe { System.alloc(l) }
    }
    unsafe fn alloc_zeroed(&self, l: Layout) -> *mut u8 {
        add(l.size());
        unsafe { System.alloc_zeroed(l) }
    }
    unsafe fn realloc(&self, p: *mut u8, l: Layout, n: usize) -> *mut u8 {
        add(n);
        unsafe { System.realloc(p, l, n) }
    }
    unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
        unsafe { System.dealloc(p, l) }
    }
}
#[global_allocator]
static ALLOC: Counted = Counted;
#[test]
fn operation_region_discovery_can_stop_before_allocating_snapshot_or_subtree() {
    use ken_query::execution::{ExecutionError, GraphRead, OperationProbe};
    for descendants in [false, true] {
        let mut ir=ken_program::StructuralIr::from_json(r#"{"path":"scale","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":[]}"#).unwrap();
        for i in 0..50000 {
            ir.operations.push(ken_program::Operation {
                id: format!("o{i}"),
                kind: "EXPRESSION".into(),
                native_kind: "expression".into(),
                parent: if descendants && i > 0 {
                    Some("o0".into())
                } else {
                    None
                },
                role: String::new(),
                start: i,
                end: i + 1,
                line: 1,
                owner: "owner".into(),
                attrs: Default::default(),
            });
        }
        let graph = MemoryGraph::new(&ir).unwrap();
        let probe = OperationProbe {
            region: Some("o0".into()),
            ..Default::default()
        };
        let mut polls = 0;
        let mut delivered = 0;
        BYTES.with(|b| b.set(Some(0)));
        let result = graph.operations_checked(
            &probe,
            &mut || {
                polls += 1;
                if polls == 2 {
                    Err(ExecutionError::Exhausted("cancelled"))
                } else {
                    Ok(())
                }
            },
            &mut |_| {
                delivered += 1;
                Ok(())
            },
        );
        let bytes = BYTES.with(|b| b.replace(None).unwrap());
        assert!(matches!(
            result,
            Err(ExecutionError::Exhausted("cancelled"))
        ));
        assert_eq!(polls, 2);
        assert_eq!(delivered, 0);
        assert!(
            bytes < 32 * 1024,
            "descendants={descendants}, discovery allocated {bytes} before cancellation"
        );
    }
}
#[test]
fn rejected_wide_metadata_does_not_allocate_a_queue_for_every_child() {
    let ir=ken_program::StructuralIr::from_json(r#"{"path":"scale","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":[]}"#).unwrap();
    let graph = MemoryGraph::new(&ir).unwrap();
    let mut q = RelationalQuery {
        name: "wide".into(),
        nodes: Arc::new(vec![]),
        exports: Default::default(),
        definitions: Default::default(),
    };
    Execution::new(Default::default())
        .unwrap()
        .execute(&graph, &q)
        .unwrap();
    q.nodes = Arc::new(vec![RelationalNode {
        kind: "where".into(),
        value: PlanValue::Tuple(vec![PlanValue::None; 150000]),
        children: vec![],
    }]);
    BYTES.with(|b| b.set(Some(0)));
    let result = Execution::new(Default::default())
        .unwrap()
        .execute(&graph, &q);
    let bytes = BYTES.with(|b| b.replace(None).unwrap());
    assert!(result.is_err());
    eprintln!("rejected metadata allocated {bytes} bytes");
    assert!(bytes < 512 * 1024, "{bytes}");
}
