//! Read-only schema15 adapter. Query policy and counters live in ken-query.
use ken_program::{Entity, Fact, Operation};
use ken_query::{
    execution::{
        Execution, ExecutionError, ExecutionOptions, FactProbe, GraphRead, Interruption,
        OperationProbe, QueryOutcome, Result, SourceProbe, values::SourceNode,
    },
    relational::RelationalQuery,
};
use ken_store::structural::{
    NodeFilter, Scalar, StoredNode, StructuralError,
    graph::{EntityFilter, FactFilter, GraphExecution, GraphIndex, OperationFilter},
};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

/// Execute while the graph's lease and exclusive SQLite progress scope are live.
/// Neither a statement nor a deferred evidence handle escapes the returned value.
pub fn execute_query(
    index: &mut GraphIndex<'_>,
    query: &RelationalQuery,
    options: ExecutionOptions,
) -> Result<QueryOutcome> {
    execute_query_with(index, query, options, |graph, execution, query| {
        execution.execute(graph, query)
    })
}
/// Adapt only the physical reader while the original execution/lease scope is held.
pub(crate) fn execute_query_with(
    index: &mut GraphIndex<'_>,
    query: &RelationalQuery,
    options: ExecutionOptions,
    adapt: impl FnOnce(&dyn GraphRead, Execution, &RelationalQuery) -> Result<QueryOutcome>,
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
    adapt(&snapshot, execution, query)
}
/// Low-level adapter for one invocation that already owns a GraphExecution scope.
/// Use the same Interruption in the callback and adapter; construct a new adapter
/// for each run rather than mixing independent controls in a batch.
/// Prefer execute_query to install interruption and clean it up automatically.
pub struct GraphSnapshot<'a, 'store> {
    index: &'a GraphIndex<'store>,
    interruption: Interruption,
    indexed_source: bool,
    coverage: Option<bool>,
}
impl<'a, 'store> GraphSnapshot<'a, 'store> {
    pub fn new(index: &'a GraphExecution<'_, 'store>, interruption: Interruption) -> Self {
        Self {
            index,
            interruption,
            indexed_source: false,
            coverage: None,
        }
    }
    /// Current capture omissions can make a reused storage snapshot incomplete.
    pub fn with_coverage(mut self, coverage: bool) -> Self {
        self.coverage = Some(coverage);
        self
    }
    /// Indexed KQL2 uses persistent source node IDs/units, while BODY selectors on
    /// a relational graph use the graph's source view. Both share semantic facts.
    pub fn indexed(index: &'a GraphExecution<'_, 'store>, interruption: Interruption) -> Self {
        Self {
            index,
            interruption,
            indexed_source: true,
            coverage: None,
        }
    }
}
fn node_value(node: StoredNode) -> Arc<SourceNode> {
    Arc::new(SourceNode {
        id: node.id,
        unit: node.unit,
        local_id: node.local_id,
        kind: node.kind,
        name: node.name,
        owner: node.owner,
        line: node.line,
        end_line: node.end_line,
        path: node.path,
        language: node.language,
    })
}
fn stored_node(node: &SourceNode) -> StoredNode {
    StoredNode {
        id: node.id,
        unit: node.unit,
        local_id: node.local_id.clone(),
        kind: node.kind.clone(),
        name: node.name.clone(),
        owner: node.owner.clone(),
        line: node.line,
        end_line: node.end_line,
        path: node.path.clone(),
        language: node.language.clone(),
    }
}
fn storage(error: StructuralError, interruption: &Interruption) -> ExecutionError {
    if matches!(error, StructuralError::Expired) {
        return ExecutionError::Exhausted("snapshot_expired");
    }
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
    fn check_snapshot(&self) -> Result<()> {
        self.interruption.check()?;
        self.index
            .check_snapshot()
            .map_err(|e| storage(e, &self.interruption))
    }
    fn source_snapshot_id(&self) -> i64 {
        if self.indexed_source {
            self.index.snapshot_id()
        } else {
            1
        }
    }
    fn source_units(
        &self,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(i64) -> Result<()>,
    ) -> Result<()> {
        self.interruption.check()?;
        check()?;
        let mut failure = None;
        let result =
            self.index
                .source_store()
                .snapshot_units_checked(self.index.snapshot_id(), |unit| {
                    if let Err(error) = self
                        .interruption
                        .check()
                        .and_then(|_| check())
                        .and_then(|_| visit(unit))
                    {
                        failure = Some(error);
                        return Err(StructuralError::Invalid("query execution interrupted"));
                    }
                    Ok(())
                });
        if let Some(error) = failure {
            return Err(error);
        }
        result.map_err(|e| storage(e, &self.interruption))?;
        self.interruption.check()
    }
    fn source_node(&self, id: &str) -> Result<Option<Arc<SourceNode>>> {
        self.interruption.check()?;
        let node = if self.indexed_source {
            self.index
                .source_store()
                .node_by_local_id(self.index.snapshot_id(), id)
        } else {
            self.index.source_view().node(id)
        }
        .map_err(|e| storage(e, &self.interruption))?;
        self.interruption.check()?;
        Ok(node.map(node_value))
    }
    fn source_scan(
        &self,
        p: &SourceProbe,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(Arc<SourceNode>) -> Result<()>,
    ) -> Result<u64> {
        self.interruption.check()?;
        check()?;
        if self.indexed_source {
            let store = self.index.source_store();
            let before = store.scanned();
            let mut scan = store
                .prepare_scan(
                    self.index.snapshot_id(),
                    NodeFilter {
                        kind: p.kind.clone(),
                        name: p.name.clone(),
                        owner: p.owner.clone(),
                        node_id: p.node_id,
                        reference: p.reference,
                    },
                )
                .map_err(|e| storage(e, &self.interruption))?;
            for node in scan
                .rows_checked(|| {
                    if self.interruption.interrupted() {
                        Err(StructuralError::Invalid("query execution interrupted"))
                    } else {
                        Ok(())
                    }
                })
                .map_err(|e| storage(e, &self.interruption))?
            {
                check()?;
                visit(node_value(
                    node.map_err(|e| storage(e, &self.interruption))?,
                ))?;
            }
            self.interruption.check()?;
            Ok(store.scanned() - before)
        } else {
            let mut scan = self
                .index
                .entities(&EntityFilter {
                    kind: if p.reference { None } else { p.kind.clone() },
                    source_owner: if p.reference {
                        None
                    } else {
                        p.owner.as_ref().map(|(_, owner)| owner.clone())
                    },
                    ..Default::default()
                })
                .map_err(|e| storage(e, &self.interruption))?;
            let mut scanned = 0;
            for entity in scan
                .rows_checked(|| {
                    if self.interruption.interrupted() {
                        Err(StructuralError::Invalid("query execution interrupted"))
                    } else {
                        Ok(())
                    }
                })
                .map_err(|e| storage(e, &self.interruption))?
            {
                check()?;
                scanned += 1;
                let entity = entity.map_err(|e| storage(e, &self.interruption))?;
                if let Some(node) = self
                    .index
                    .source_view()
                    .node(&entity.id)
                    .map_err(|e| storage(e, &self.interruption))?
                {
                    let node = node_value(node);
                    if p.matches(&node) {
                        visit(node)?;
                    }
                }
            }
            self.interruption.check()?;
            Ok(scanned)
        }
    }
    fn source_properties(
        &self,
        node: &SourceNode,
    ) -> Result<BTreeMap<String, ken_program::value::GraphValue>> {
        use ken_program::value::GraphValue as V;
        self.interruption.check()?;
        if self.indexed_source {
            let props = self
                .index
                .source_store()
                .properties(&stored_node(node))
                .map_err(|e| storage(e, &self.interruption))?;
            let props = props
                .into_iter()
                .map(|(k, v)| {
                    (
                        k,
                        match v {
                            Scalar::String(v) => V::String(v.into()),
                            Scalar::Int(v) => V::Int(v),
                            Scalar::Float(v) => V::Float(v),
                            Scalar::Bool(v) => V::Bool(v),
                            Scalar::Null => V::Null,
                        },
                    )
                })
                .collect();
            self.check_snapshot()?;
            return Ok(props);
        }
        let mut props = if let Some(entity) = self.entity(&node.local_id)? {
            entity
                .attrs
                .iter()
                .map(|(k, v)| Ok((k.clone(), V::parse(v)?)))
                .collect::<Result<BTreeMap<_, _>>>()?
        } else {
            BTreeMap::new()
        };
        props.insert(
            "name".into(),
            node.name
                .as_ref()
                .map_or(V::Null, |v| V::String(v.as_str().into())),
        );
        props.insert("path".into(), V::String(node.path.as_str().into()));
        props.insert("language".into(), V::String(node.language.as_str().into()));
        self.interruption.check()?;
        Ok(props)
    }
    fn source_program(&self, unit: i64) -> Result<Option<Arc<ken_program::Program>>> {
        self.interruption.check()?;
        let result = self
            .index
            .source_store()
            .read_snapshot_program(self.index.snapshot_id(), unit)
            .map_err(|e| storage(e, &self.interruption))?;
        self.interruption.check()?;
        Ok(result.map(Arc::new))
    }
    fn source_coverage(&self) -> Result<bool> {
        self.interruption.check()?;
        if let Some(coverage) = self.coverage {
            return Ok(coverage);
        }
        self.index
            .source_store()
            .snapshot_coverage(self.index.snapshot_id())
            .map_err(|e| storage(e, &self.interruption))
    }
    fn operations(
        &self,
        p: &OperationProbe,
        visit: &mut dyn FnMut(Arc<Operation>) -> Result<()>,
    ) -> Result<()> {
        self.interruption.check()?;
        let mut scan = self
            .index
            .operations(&OperationFilter {
                local_id: p.id.clone(),
                owner: p.owner.clone(),
                kind: p.kind.clone(),
                region: p.region.clone(),
                ..Default::default()
            })
            .map_err(|e| storage(e, &self.interruption))?;
        for op in scan
            .rows_checked(|| {
                if self.interruption.interrupted() {
                    Err(StructuralError::Invalid("query execution interrupted"))
                } else {
                    Ok(())
                }
            })
            .map_err(|e| storage(e, &self.interruption))?
        {
            self.interruption.check()?;
            visit(Arc::new(op.map_err(|e| storage(e, &self.interruption))?))?;
        }
        self.interruption.check()
    }
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
