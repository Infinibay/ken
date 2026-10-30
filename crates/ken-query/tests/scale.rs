//! Allocation work at the public preparation boundary, independent of wall time.
use ken_query::{ParseLimits, expand_indexed_alternatives, parse};
use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
};

struct CountedSystem;
thread_local! {
    static ALLOCATIONS: Cell<Option<usize>> = const { Cell::new(None) };
}
fn allocated() {
    let _ = ALLOCATIONS.try_with(|count| {
        if let Some(n) = count.get() {
            count.set(Some(n + 1));
        }
    });
}
// Keep the system allocator's safety contract; only count requests on this test
// thread while expansion runs. Input parsing and assertions are outside the scope.
unsafe impl GlobalAlloc for CountedSystem {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        allocated();
        unsafe { System.alloc(layout) }
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        allocated();
        unsafe { System.alloc_zeroed(layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        allocated();
        unsafe { System.realloc(ptr, layout, size) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
}
#[global_allocator]
static ALLOCATOR: CountedSystem = CountedSystem;

#[test]
fn flat_expansion_allocations_scale_with_output_after_branching() {
    let clauses = 512;
    for alternatives in [1, 2] {
        let branch = if alternatives == 2 {
            "either {} or {}"
        } else {
            ""
        };
        let text = format!(
            "language \"kql/2\";module flat;query q{{{branch}{}select 1;}}",
            "where true;".repeat(clauses)
        );
        let input = parse(&text, "flat", ParseLimits::default()).unwrap();
        ALLOCATIONS.with(|count| count.set(Some(0)));
        let expanded = expand_indexed_alternatives(&input, None);
        let allocations = ALLOCATIONS.with(|count| count.replace(None).unwrap());
        let expanded = expanded.unwrap();
        assert_eq!(expanded.len(), alternatives);
        for tree in expanded {
            assert_eq!(tree.declarations.last().unwrap().clauses.len(), clauses + 1);
        }
        // A generous output-size bound tolerates allocator/capacity changes while
        // excluding repeated copies of the whole accumulated prefix.
        assert!(
            allocations < clauses * alternatives * 64,
            "{alternatives} alternatives used {allocations} allocations"
        );
        eprintln!("{alternatives} alternatives: {allocations} allocations");
    }
}

#[test]
fn rejected_pattern_expansion_does_not_allocate_the_whole_pipeline() {
    use ken_query::{ParseLimits, compile_indexed, parse};
    let text = format!(
        "language \"kql/2\";module bounded;pattern P(){{{}}}query q{{{}select 1;}}",
        "where true;".repeat(512),
        "use P();".repeat(512)
    );
    let tree = parse(&text, "bounded", ParseLimits::default()).unwrap();
    ALLOCATIONS.with(|count| count.set(Some(0)));
    let result = compile_indexed(&tree, None);
    let allocations = ALLOCATIONS.with(|count| count.replace(None).unwrap());
    assert_eq!(result.unwrap_err().code, "resource_limit");
    assert!(
        allocations < 200000,
        "rejected expansion performed {allocations} allocations"
    );
    eprintln!("rejected expansion: {allocations} allocations");
}

#[test]
fn wide_gap_forbidden_targets_do_not_repeat_allocations() {
    use ken_query::{ParseLimits, compile_body, parse};
    use std::collections::BTreeMap;
    let text = format!(
        "language \"kql/2\";module gap;pattern P(){{body{{call $f{{}};gap until next{{{}}}call $f{{}};}}}}",
        "forbid call($f);".repeat(512)
    );
    let tree = parse(&text, "gap", ParseLimits::default()).unwrap();
    let mut roles = BTreeMap::from([("f".into(), "callable".into())]);
    ALLOCATIONS.with(|count| count.set(Some(0)));
    let result = compile_body(
        &tree.declarations[0].clauses[0],
        "owner",
        &BTreeMap::new(),
        &mut roles,
        None,
    );
    let allocations = ALLOCATIONS.with(|count| count.replace(None).unwrap());
    let plan = result.unwrap();
    assert_eq!(plan.clauses.len(), 3);
    assert!(
        allocations < 50000,
        "wide gap performed {allocations} allocations"
    );
    eprintln!("wide gap: {allocations} allocations");
}
