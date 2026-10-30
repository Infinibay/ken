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
