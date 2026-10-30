//! Read-only schema15 adapter. Query policy and counters live in ken-query.
use ken_program::{Entity, Fact};
use ken_query::{
    execution::{
        Execution, ExecutionError, ExecutionOptions, FactProbe, GraphRead, Interruption,
        QueryOutcome, Result,
    },
    relational::RelationalQuery,
};
use ken_store::structural::{
    StructuralError,
    graph::{EntityFilter, FactFilter, GraphExecution, GraphIndex},
};
use std::{collections::BTreeSet, sync::Arc};

/// Execute while the graph's lease and exclusive SQLite progress scope are live.
/// Neither a statement nor a deferred evidence handle escapes the returned value.
pub fn execute_query(
    index: &mut GraphIndex<'_>,
    query: &RelationalQuery,
    options: ExecutionOptions,
) -> Result<QueryOutcome> {
    let execution = Execution::new(options)?;
    let interruption = execution.interruption();
    let poll = interruption.clone();
    let mut initial = true;
    // GraphIndex polls once before installing the callback. Validation/execution
    // owns the initial interruption check, so even a pre-cancelled call returns a
    // typed incomplete result and still validates malformed plans consistently.
    let scope = index
        .execution(move || {
            if std::mem::take(&mut initial) {
                false
            } else {
                poll.interrupted()
            }
        })
        .map_err(|e| storage(e, &interruption))?;
    let snapshot = GraphSnapshot::new(&scope, interruption);
    execution.execute(&snapshot, query)
}
/// Low-level adapter for one invocation that already owns a GraphExecution scope.
/// Use the same Interruption in the callback and adapter; construct a new adapter
/// for each run rather than mixing independent controls in a batch.
/// Prefer execute_query to install interruption and clean it up automatically.
pub struct GraphSnapshot<'a, 'store> {
    index: &'a GraphIndex<'store>,
    interruption: Interruption,
}
impl<'a, 'store> GraphSnapshot<'a, 'store> {
    pub fn new(index: &'a GraphExecution<'_, 'store>, interruption: Interruption) -> Self {
        Self {
            index,
            interruption,
        }
    }
}
fn storage(error: StructuralError, interruption: &Interruption) -> ExecutionError {
    let interrupted = matches!(&error,StructuralError::Sql(rusqlite::Error::SqliteFailure(code,_)) if code.code==rusqlite::ErrorCode::OperationInterrupted)
        || matches!(
            &error,
            StructuralError::Invalid("query execution interrupted")
        );
    if interrupted && let Some(reason) = interruption.reason() {
        ExecutionError::Exhausted(reason)
    } else {
        ExecutionError::Storage(error.to_string())
    }
}
fn filter(p: &FactProbe) -> FactFilter {
    FactFilter {
        relation: p.relation.clone(),
        subject: p.subject.clone(),
        object: p.object.clone(),
        attribute: p.attribute.clone(),
    }
}
impl GraphRead for GraphSnapshot<'_, '_> {
    fn facts(&self, p: &FactProbe, visit: &mut dyn FnMut(Arc<Fact>) -> Result<()>) -> Result<()> {
        self.interruption.check()?;
        let mut scan = self
            .index
            .facts(&filter(p))
            .map_err(|e| storage(e, &self.interruption))?;
        let rows = scan
            .rows_checked(|| {
                if self.interruption.interrupted() {
                    Err(StructuralError::Invalid("query execution interrupted"))
                } else {
                    Ok(())
                }
            })
            .map_err(|e| storage(e, &self.interruption))?;
        for f in rows {
            self.interruption.check()?;
            visit(Arc::new(f.map_err(|e| storage(e, &self.interruption))?))?;
        }
        self.interruption.check()
    }
    fn first(&self, p: &FactProbe) -> Result<Option<Arc<Fact>>> {
        self.interruption.check()?;
        let mut scan = self
            .index
            .facts(&filter(p))
            .map_err(|e| storage(e, &self.interruption))?;
        let first = scan
            .rows()
            .map_err(|e| storage(e, &self.interruption))?
            .next()
            .transpose()
            .map_err(|e| storage(e, &self.interruption))?;
        self.interruption.check()?;
        Ok(first.map(Arc::new))
    }
    fn count(&self, p: &FactProbe) -> Result<u64> {
        self.interruption.check()?;
        let count = self
            .index
            .count(&filter(p))
            .map_err(|e| storage(e, &self.interruption))?;
        self.interruption.check()?;
        Ok(count)
    }
    fn entity(&self, id: &str) -> Result<Option<Arc<Entity>>> {
        self.interruption.check()?;
        let mut scan = self
            .index
            .entities(&EntityFilter {
                local_id: Some(id.into()),
                ..Default::default()
            })
            .map_err(|e| storage(e, &self.interruption))?;
        let first = scan
            .rows()
            .map_err(|e| storage(e, &self.interruption))?
            .next()
            .transpose()
            .map_err(|e| storage(e, &self.interruption))?;
        self.interruption.check()?;
        Ok(first.map(Arc::new))
    }
    fn entity_ids(&self, visit: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
        self.interruption.check()?;
        let mut scan = self
            .index
            .entities(&EntityFilter::default())
            .map_err(|e| storage(e, &self.interruption))?;
        for e in scan.rows().map_err(|e| storage(e, &self.interruption))? {
            self.interruption.check()?;
            visit(&e.map_err(|e| storage(e, &self.interruption))?.id)?;
        }
        Ok(())
    }
    fn capabilities(&self) -> &BTreeSet<String> {
        &self.index.capabilities
    }
    fn relations(&self) -> &BTreeSet<String> {
        &self.index.relations
    }
}
