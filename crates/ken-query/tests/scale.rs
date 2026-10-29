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
