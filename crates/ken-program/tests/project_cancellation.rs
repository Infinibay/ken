//! Cancellation before acquisition must not copy an already rejected unit payload.
use ken_program::{ProgramError, StructuralIr, project::link_nominal_with_check};
use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
};
thread_local! {static ALLOCATED:Cell<usize>=const{Cell::new(0)};}
struct AllocationCounter;
#[global_allocator]
static ALLOCATOR: AllocationCounter = AllocationCounter;
unsafe impl GlobalAlloc for AllocationCounter {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let _ = ALLOCATED.try_with(|count| count.set(count.get().saturating_add(layout.size())));
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        let _ = ALLOCATED.try_with(|count| count.set(count.get().saturating_add(size)));
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
