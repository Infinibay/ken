//! Scoped SQLite interruption. Query-language budgets stay with their executor.
use super::{GraphIndex, Result, StructuralError};
use std::ops::Deref;
/// Installs a progress callback for one exclusive execution scope and removes it
/// on drop, including error/unwind. The callback must not call SQLite itself.
/// The scope exposes read access only, so callbacks cannot be nested accidentally.
pub struct GraphExecution<'a, 'b> {
    index: &'a mut GraphIndex<'b>,
}
impl<'b> GraphIndex<'b> {
    /// Poll interruption every 1000 VM instructions, including candidate counts
    /// and sorts that have not produced a row yet. Use rows_checked for typed
    /// cancellation at individual result boundaries as well.
    pub fn execution<'a>(
        &'a mut self,
        mut interrupt_if: impl FnMut() -> bool + Send + 'static,
    ) -> Result<GraphExecution<'a, 'b>> {
        self.store.renew_reader()?;
        if interrupt_if() {
            return Err(StructuralError::Invalid("query execution cancelled"));
        }
        self.store
            .connection()
            .progress_handler(1000, Some(interrupt_if))?;
        Ok(GraphExecution { index: self })
    }
}
impl<'b> Deref for GraphExecution<'_, 'b> {
    type Target = GraphIndex<'b>;
    fn deref(&self) -> &Self::Target {
        self.index
    }
}
impl Drop for GraphExecution<'_, '_> {
    fn drop(&mut self) {
        let _ = self
            .index
            .store
            .connection()
            .progress_handler(0, None::<fn() -> bool>);
    }
}
