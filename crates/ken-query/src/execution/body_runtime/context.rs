use super::super::{
    FactProbe, OperationProbe, SourceProbe,
    source::{Knowledge, SourceCache, SourceRuntime},
};
use super::*;
use ken_program::{Entity, Fact, Operation, value::GraphValue as S};

pub(super) type Op = Arc<Operation>;
type FactQuery = (String, Option<String>, Option<String>);
type FactsByQuery = BTreeMap<FactQuery, Vec<Arc<Fact>>>;
pub(super) fn text(attrs: &ken_program::Attributes, key: &str) -> Result<String> {
    Ok(super::super::source::attr(attrs, key)?
        .string()
        .unwrap_or_default())
}
pub(super) fn attr(attrs: &ken_program::Attributes, key: &str) -> Result<S> {
    super::super::source::attr(attrs, key)
}
pub(super) fn number(attrs: &ken_program::Attributes, key: &str) -> Result<Option<i64>> {
    Ok(match attr(attrs, key)? {
        S::Int(v) => v.parse().ok(),
        _ => None,
    })
}
pub(super) fn strings(attrs: &ken_program::Attributes, key: &str) -> Result<Vec<String>> {
    Ok(match attr(attrs, key)? {
        S::List(v) | S::Tuple(v) => v.iter().filter_map(S::string).collect(),
        _ => vec![],
    })
}
pub(super) fn op(c: &Clause, i: usize) -> Result<O<'_>> {
    c.expressions
        .get(i)
        .map(O::from)
        .ok_or_else(|| invalid("missing BODY operand"))
}
pub(super) fn arg(e: O<'_>, i: usize) -> Result<O<'_>> {
    e.arg(i)
        .ok_or_else(|| invalid("missing BODY expression operand"))
}
pub(super) fn block(c: &Clause) -> &[Clause] {
    c.blocks.first().map_or(&[], Vec::as_slice)
}
pub(super) fn flag(c: &Clause, name: &str) -> bool {
    c.flags.iter().any(|f| f == name)
}
pub(super) fn query(e: O<'_>) -> Expr {
    crate::with_stack(|| match e {
        O::Query(e) => e.clone(),
        O::Source(e) => Expr {
            kind: e.kind.clone(),
            span: e.span.clone(),
            value: e.value.clone(),
            args: e.args.iter().map(|e| query(O::from(e))).collect(),
            parameters: vec![],
            depth: 1,
        },
    })
}
pub(super) fn literal(e: O<'_>) -> Result<Value> {
    Value::literal(e.value())
}
pub(super) fn node(bindings: &Bindings, name: &str) -> Option<Arc<SourceNode>> {
    if let Some(Value::Node(n)) = bindings.get(name) {
        Some(n.clone())
    } else {
        None
    }
}
pub(super) fn id_value(bindings: &Bindings, name: &str) -> Option<String> {
    bindings
        .get(name)
        .and_then(Value::local_id)
        .map(str::to_owned)
}
pub(super) fn truth(v: bool) -> Value {
    Value::boolean(v)
}
pub(super) fn unknown(reason: &str) -> Value {
    Value::unknown(reason)
}
pub(super) fn objects(rows: &[Arc<Fact>]) -> BTreeSet<String> {
    rows.iter().map(|f| f.object.clone()).collect()
}
pub(super) fn supported(rows: &[Arc<Fact>]) -> bool {
    !rows.is_empty() && rows.iter().all(|f| f.object == "supported")
}

pub(super) struct Context<'a> {
    pub graph: &'a dyn GraphRead,
    pub owner: Arc<SourceNode>,
    pub region: Option<Op>,
    pub operations: BTreeMap<String, Op>,
    pub ordered: Vec<Op>,
    pub children: BTreeMap<String, Vec<Op>>,
    pub locals: Vec<Arc<SourceNode>>,
    pub entities: BTreeMap<String, Arc<Entity>>,
    pub calls: BTreeMap<(i64, i64), Arc<Entity>>,
    pub spans: BTreeMap<(i64, i64), Op>,
    pub foreign: BTreeSet<String>,
    pub entries: Vec<String>,
    pub events: BTreeMap<String, ken_program::Attributes>,
    pub gaps: BTreeSet<String>,
    pub implied: Option<Op>,
    pub producers: BTreeMap<String, String>,
    pub iteration: BTreeMap<String, (Op, String)>,
    pub keyed: BTreeSet<String>,
    pub path_enabled: bool,
    pub initial: Option<Snapshot>,
    pub deferred: BTreeSet<String>,
    pub region_entry_incomplete: bool,
    facts: FactsByQuery,
    parts: BTreeMap<String, Vec<Op>>,
    source: SourceCache,
}
impl<'a> Context<'a> {
    pub fn bare(
        graph: &'a dyn GraphRead,
        owner: Arc<SourceNode>,
        region: Option<Op>,
        iteration: BTreeMap<String, (Op, String)>,
        keyed: BTreeSet<String>,
    ) -> Self {
        Self {
            graph,
            owner,
            region,
            operations: BTreeMap::new(),
            ordered: vec![],
            children: BTreeMap::new(),
            locals: vec![],
            entities: BTreeMap::new(),
            calls: BTreeMap::new(),
            spans: BTreeMap::new(),
            foreign: BTreeSet::new(),
            entries: vec![],
            events: BTreeMap::new(),
            gaps: BTreeSet::new(),
            implied: None,
            producers: BTreeMap::new(),
            iteration,
            keyed,
            path_enabled: false,
            initial: None,
            deferred: BTreeSet::new(),
            region_entry_incomplete: false,
            facts: BTreeMap::new(),
            parts: BTreeMap::new(),
            source: SourceCache::default(),
        }
    }
    pub fn new(
        graph: &'a dyn GraphRead,
        owner: Arc<SourceNode>,
        region: Option<Op>,
        pattern: &BodyPattern,
        iteration: BTreeMap<String, (Op, String)>,
        keyed: BTreeSet<String>,
        services: &mut dyn BodyServices,
    ) -> Result<Option<Self>> {
        services.check()?;
        let mut c = Self::bare(graph, owner, region, iteration, keyed);
        let owner_id = c.owner.local_id.clone();
        let statuses = c.rows("CFG_STATUS", Some(&owner_id), None, services)?;
        let entries = c.rows("CFG_ENTRY", Some(&owner_id), None, services)?;
        if entries.is_empty() || !coverage(&statuses, pattern)? {
            return Ok(None);
        }
        c.entries = entries.iter().map(|f| f.object.clone()).collect();
        for fact in &statuses {
            c.gaps.extend(strings(&fact.attrs, "gaps")?);
        }
        let dispatch = statuses
            .iter()
            .map(|f| strings(&f.attrs, "reasons"))
            .collect::<Result<Vec<_>>>()?
            .iter()
            .flatten()
            .any(|r| matches!(r.as_str(), "exception-dispatch" | "generator-resumption"));
        let probe = OperationProbe {
            owner: Some(owner_id.clone()),
            ..Default::default()
        };
        graph.operations_checked(&probe, &mut || services.check(), &mut |operation| {
            if operation.owner == owner_id {
                c.ordered.push(operation);
            }
            Ok(())
        })?;
        let source_probe = SourceProbe {
            owner: Some((c.owner.unit, owner_id.clone())),
            ..Default::default()
        };
        graph.source_scan(&source_probe, &mut || services.check(), &mut |n| {
            if source_probe.matches(&n) {
                c.locals.push(n);
            }
            Ok(())
        })?;
        for n in &c.locals {
            services.check()?;
            if let Some(e) = graph.entity(&n.local_id)? {
                c.entities.insert(e.id.clone(), e);
            }
        }
        // SourceView attaches unowned literal values only through direct semantic
        // uses whose subject is an entity in this owner. Path snapshots must use
        // that same small entity view rather than expanding arbitrary global values.
        let subjects = c.entities.keys().cloned().collect::<Vec<_>>();
        for subject in subjects {
            for relation in ["ARGUMENT", "ASSIGNMENT_VALUE", "RETURN_OPERAND", "OPERAND"] {
                let probe = FactProbe {
                    relation: relation.into(),
                    subject: Some(subject.clone()),
                    object: None,
                    attribute: None,
                };
                let mut links = vec![];
                graph.facts(&probe, &mut |f| {
                    services.check()?;
                    if f.relation == relation && f.subject == subject {
                        links.push(f);
                    }
                    Ok(())
                })?;
                for link in links {
                    for value in c.rows("VALUE", Some(&link.object), None, services)? {
                        if let Some(entity) = graph.entity(&value.object)? {
                            c.entities.insert(entity.id.clone(), entity);
                        }
                    }
                }
            }
        }
        // Calls are owner-local semantic occurrences. Query snapshots expose literal
        // argument values as separate entities; load those only on demand.
        for entity in c.entities.values() {
            if entity.kind == "CALL" {
                let start = number(&entity.attrs, "start_byte")?;
                let end = number(&entity.attrs, "end_byte")?;
                if let (Some(start), Some(end)) = (start, end) {
                    c.calls.insert((start, end), entity.clone());
                }
            }
        }
        for operation in &c.ordered {
            if c.region
                .as_ref()
                .is_none_or(|r| r.start <= operation.start && operation.end <= r.end)
            {
                c.operations.insert(operation.id.clone(), operation.clone());
            }
        }
        if dispatch {
            for f in c.rows("CFG_DISPATCH", Some(&owner_id), None, services)? {
                let source = text(&f.attrs, "operation")?;
                if let Some(statement) = c.operations.get(&source).cloned()
                    && f.object != source
                {
                    let op = Arc::new(Operation {
                        id: f.object.clone(),
                        kind: "DISPATCH".into(),
                        native_kind: "exception_dispatch".into(),
                        parent: statement.parent.clone(),
                        role: String::new(),
                        start: statement.start,
                        end: statement.start,
                        line: statement.line,
                        owner: owner_id.clone(),
                        attrs: f.attrs.clone(),
                    });
                    c.operations.insert(op.id.clone(), op);
                }
                c.events.insert(f.object.clone(), f.attrs.clone());
                if text(&f.attrs, "action")? == "return-eval" {
                    c.deferred.insert(source);
                }
            }
        }
        for op in &c.ordered {
            if c.operations.contains_key(&op.id) {
                c.children
                    .entry(op.parent.clone().unwrap_or_default())
                    .or_default()
                    .push(op.clone());
            }
        }
        for op in c.operations.values() {
            if op.kind == "DISPATCH" {
                c.children
                    .entry(op.parent.clone().unwrap_or_default())
                    .or_default()
                    .push(op.clone());
            }
        }
        for op in &c.ordered {
            if c.operations.contains_key(&op.id) {
                c.spans.insert((op.start, op.end), op.clone());
                if op.kind != "CALL" && c.calls.contains_key(&(op.start, op.end)) {
                    c.foreign.insert(op.id.clone());
                }
            }
        }
        if !c
            .rows("BODY_VALUE", Some(&owner_id), None, services)?
            .is_empty()
        {
            let roots: Vec<_> = c
                .operations
                .values()
                .filter(|o| {
                    o.role == "body"
                        && o.parent
                            .as_ref()
                            .and_then(|p| c.operations.get(p))
                            .is_none_or(|p| p.kind == "FUNCTION")
                })
                .cloned()
                .collect();
            if roots.len() == 1 {
                let root = &roots[0];
                let implied = Arc::new(Operation {
                    id: format!("{owner_id}::implicit-return"),
                    kind: "RETURN".into(),
                    native_kind: "implicit_return".into(),
                    parent: root.parent.clone(),
                    role: "body".into(),
                    start: root.start,
                    end: root.end,
                    line: root.line,
                    owner: owner_id.clone(),
                    attrs: Default::default(),
                });
                c.children.insert(implied.id.clone(), vec![root.clone()]);
                c.implied = Some(implied);
            }
        }
        if let Some(region) = c.region.clone() {
            let parent = region.parent.clone().unwrap_or_default();
            let starts = c
                .rows("CFG_NEXT", Some(&parent), None, services)?
                .iter()
                .filter(|f| c.operations.contains_key(&f.object))
                .map(|f| f.object.clone())
                .collect::<Vec<_>>();
            c.entries = if starts.is_empty() && c.operations.contains_key(&region.id) {
                vec![region.id.clone()]
            } else {
                starts
            };
            if c.entries.is_empty() {
                c.region_entry_incomplete = !c.operations.is_empty();
            }
        }
        c.path_enabled = c.owner.language == "python"
            && pattern.clauses.iter().all(|cl| {
                matches!(
                    cl.kind.as_str(),
                    "call" | "let" | "return" | "yield" | "resume"
                )
            })
            && (pattern
                .clauses
                .iter()
                .any(|cl| matches!(cl.kind.as_str(), "return" | "yield"))
                || dispatch)
            && !c.operations.values().any(|op| {
                matches!(
                    op.native_kind.as_str(),
                    "global_statement"
                        | "nonlocal_statement"
                        | "named_expression"
                        | "delete_statement"
                        | "import_statement"
                        | "import_from_statement"
                        | "with_statement"
                        | "ERROR"
                )
            })
            && !c
                .locals
                .iter()
                .any(|n| matches!(n.kind.as_str(), "CALLABLE" | "CLASS"));
        if c.path_enabled {
            let calls: Vec<_> = c.calls.values().map(|e| e.id.clone()).collect();
            for call in calls {
                if c.rows("CALLEE_NAME", Some(&call), None, services)?
                    .iter()
                    .any(|f| {
                        matches!(
                            f.object.as_str(),
                            "eval" | "exec" | "locals" | "globals" | "_getframe" | "currentframe"
                        )
                    })
                {
                    c.path_enabled = false;
                    break;
                }
            }
        }
        if c.path_enabled {
            c.initial = Some(
                c.locals
                    .iter()
                    .filter(|n| n.kind == "PARAMETER")
                    .map(|n| (n.local_id.clone(), Some(n.local_id.clone())))
                    .collect(),
            );
        }
        Ok(Some(c))
    }
    pub fn rows(
        &mut self,
        relation: &str,
        subject: Option<&str>,
        object: Option<&str>,
        services: &mut dyn BodyServices,
    ) -> Result<Vec<Arc<Fact>>> {
        services.check()?;
        let key = (
            relation.to_owned(),
            subject.map(str::to_owned),
            object.map(str::to_owned),
        );
        if let Some(rows) = self.facts.get(&key) {
            return Ok(rows.clone());
        }
        let probe = FactProbe {
            relation: relation.into(),
            subject: subject.map(str::to_owned),
            object: object.map(str::to_owned),
            attribute: None,
        };
        let mut result = vec![];
        self.graph.facts(&probe, &mut |f| {
            services.check()?;
            if f.relation == relation
                && subject.is_none_or(|s| s == f.subject)
                && object.is_none_or(|o| o == f.object)
            {
                result.push(f);
            }
            Ok(())
        })?;
        if relation == "ARGUMENT" && subject.is_some() {
            let mut raw = vec![];
            for argument in result {
                let metadata = self.rows("ENTITY", Some(&argument.object), None, services)?;
                let occurrence = metadata.iter().any(|f| f.object == "ARGUMENT");
                if !occurrence {
                    raw.push(argument);
                    continue;
                }
                let attrs = metadata
                    .first()
                    .map(|f| f.attrs.clone())
                    .unwrap_or_default();
                for value in self.rows("VALUE", Some(&argument.object), None, services)? {
                    let loads = self.rows("LOADED_FROM", Some(&value.object), None, services)?;
                    let entity = self.entity(&value.object, services)?;
                    let origin = entity
                        .as_ref()
                        .map(|e| text(&e.attrs, "origin"))
                        .transpose()?
                        .unwrap_or_default();
                    let value_id = if loads.len() == 1 {
                        loads[0].object.clone()
                    } else if !origin.is_empty() && self.graph.entity(&origin)?.is_some() {
                        origin
                    } else {
                        value.object.clone()
                    };
                    raw.push(Arc::new(Fact {
                        subject: argument.subject.clone(),
                        relation: relation.into(),
                        object: value_id,
                        attrs: attrs.clone(),
                        evidence: argument.evidence.clone(),
                    }));
                }
            }
            result = raw;
        }
        if self.facts.len() > 4096 {
            self.facts.clear();
        }
        self.facts.insert(key, result.clone());
        Ok(result)
    }
    pub fn ids(
        &mut self,
        r: &str,
        s: &str,
        services: &mut dyn BodyServices,
    ) -> Result<BTreeSet<String>> {
        Ok(objects(&self.rows(r, Some(s), None, services)?))
    }
    pub fn has(
        &mut self,
        r: &str,
        s: &str,
        o: &str,
        services: &mut dyn BodyServices,
    ) -> Result<bool> {
        Ok(!self.rows(r, Some(s), Some(o), services)?.is_empty())
    }
    pub fn entity(
        &mut self,
        id: &str,
        services: &mut dyn BodyServices,
    ) -> Result<Option<Arc<Entity>>> {
        services.check()?;
        if let Some(e) = self.entities.get(id) {
            return Ok(Some(e.clone()));
        }
        self.graph.entity(id)
    }
    pub fn operation(&mut self, id: &str, services: &mut dyn BodyServices) -> Result<Option<Op>> {
        if let Some(o) = self.operations.get(id) {
            return Ok(Some(o.clone()));
        }
        let mut result = None;
        let p = OperationProbe {
            id: Some(id.into()),
            ..Default::default()
        };
        self.graph
            .operations_checked(&p, &mut || services.check(), &mut |o| {
                if o.id == id {
                    result = Some(o);
                }
                Ok(())
            })?;
        Ok(result)
    }
    pub fn value_node(&self, id: impl Into<String>, kind: &str) -> Value {
        Value::Node(Arc::new(SourceNode {
            id: 0,
            unit: self.owner.unit,
            local_id: id.into(),
            kind: kind.into(),
            name: Some(String::new()),
            owner: Some(self.owner.local_id.clone()),
            line: self.owner.line,
            end_line: self.owner.end_line,
            path: self.owner.path.clone(),
            language: self.owner.language.clone(),
        }))
    }
    pub fn reference(&self, op: &Operation) -> Value {
        Value::Operation(Arc::new(OperationValue {
            snapshot: self.graph.source_snapshot_id(),
            local_id: op.id.clone(),
            kind: op.kind.to_lowercase(),
            native_kind: op.native_kind.clone(),
            path: self.owner.path.clone(),
            line: op.line,
            owner: op.owner.clone(),
            language: self.owner.language.clone(),
            execution: text(&op.attrs, "execution")
                .ok()
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| "unknown".into()),
        }))
    }
    pub fn call(&self, op: &Operation) -> Option<Arc<Entity>> {
        self.calls.get(&(op.start, op.end)).cloned()
    }
    pub fn successors(
        &mut self,
        group: &str,
        services: &mut dyn BodyServices,
    ) -> Result<Vec<String>> {
        let mut edges = self.rows("CFG_NEXT", Some(group), None, services)?;
        if self
            .operations
            .get(group)
            .is_some_and(|o| o.kind == "BRANCH")
        {
            let condition = self.rows("CONTROL_CONDITION", Some(group), None, services)?;
            if condition.len() == 1
                && let Some(op) = self.operations.get(&condition[0].object)
                && let Some(value) = self.literal_boolean(op)
            {
                let rejected = if value { "false" } else { "true" };
                edges.retain(|f| text(&f.attrs, "kind").ok().as_deref() != Some(rejected));
            }
        }
        Ok(edges
            .into_iter()
            .filter(|f| self.region.is_none() || self.operations.contains_key(&f.object))
            .map(|f| f.object.clone())
            .collect())
    }
    pub fn parts(&mut self, group: &str, services: &mut dyn BodyServices) -> Result<Vec<Op>> {
        services.check()?;
        if let Some(parts) = self.parts.get(group) {
            return Ok(parts.clone());
        }
        let event = self.events.get(group).cloned().unwrap_or_default();
        let complete = text(&event, "action")? == "return-complete";
        let id = if complete {
            text(&event, "operation")?
        } else {
            group.into()
        };
        let mut todo = self
            .operations
            .get(&id)
            .cloned()
            .into_iter()
            .collect::<Vec<_>>();
        let mut result = vec![];
        let mut seen = BTreeSet::new();
        while let Some(op) = todo.pop() {
            services.check()?;
            if !seen.insert(op.id.clone()) {
                continue;
            }
            result.push(op.clone());
            if !complete {
                for child in self.children.get(&op.id).cloned().unwrap_or_default() {
                    if self.successors(&child.id, services)?.is_empty() {
                        todo.push(child);
                    }
                }
            }
        }
        self.parts.insert(group.into(), result.clone());
        Ok(result)
    }
    pub fn literal_boolean(&self, operation: &Operation) -> Option<bool> {
        let mut op = operation;
        let mut seen = BTreeSet::new();
        while matches!(
            op.native_kind.as_str(),
            "parenthesized_expression" | "condition_clause"
        ) && seen.insert(op.id.clone())
        {
            let children: Vec<_> = self
                .children
                .get(&op.id)?
                .iter()
                .filter(|o| !o.native_kind.contains("comment"))
                .collect();
            if children.len() != 1 {
                return None;
            }
            op = children[0];
        }
        match text(&op.attrs, "text").ok()?.as_str() {
            "True" | "true" => Some(true),
            "False" | "false" => Some(false),
            _ => None,
        }
    }
    pub fn matches_type(
        &mut self,
        id: &str,
        expected: O<'_>,
        services: &mut dyn BodyServices,
    ) -> Result<Value> {
        let mut runtime = SourceRuntime {
            graph: self.graph,
            cache: &mut self.source,
            tick: &mut || services.check(),
        };
        let actual = runtime.type_of(id, false)?;
        let truth = runtime.matches(&actual, &query(expected))?;
        Ok(match truth {
            Knowledge::Known(v) => Value::boolean(v),
            Knowledge::Unknown(r) => Value::unknown(r),
        })
    }
    pub fn type_known(&mut self, id: &str, services: &mut dyn BodyServices) -> Result<bool> {
        let mut runtime = SourceRuntime {
            graph: self.graph,
            cache: &mut self.source,
            tick: &mut || services.check(),
        };
        Ok(matches!(runtime.type_of(id, false)?, Knowledge::Known(_)))
    }
}
fn covered(statuses: &[Arc<Fact>], allowed: &[&str]) -> Result<bool> {
    if statuses.is_empty() {
        return Ok(false);
    }
    for f in statuses {
        if f.object == "structured" {
            continue;
        }
        let reasons = strings(&f.attrs, "reasons")?;
        if f.object != "partial"
            || reasons.is_empty()
            || reasons.iter().any(|r| !allowed.contains(&r.as_str()))
        {
            return Ok(false);
        }
    }
    Ok(true)
}
fn coverage(statuses: &[Arc<Fact>], pattern: &BodyPattern) -> Result<bool> {
    let suspension = ["await", "await_expression"];
    let abrupt = ["raise_statement", "throw_statement"];
    let route = [
        "await",
        "await_expression",
        "raise_statement",
        "throw_statement",
        "yield",
        "yield_expression",
        "yield_statement",
        "exception-dispatch",
        "completion-dispatch",
        "exception-group",
        "generator-resumption",
    ];
    if covered(statuses, &suspension)? || covered(statuses, &abrupt)? {
        return Ok(true);
    }
    let witness = pattern.clauses.iter().all(|c| {
        matches!(
            c.kind.as_str(),
            "call" | "let" | "return" | "yield" | "resume"
        )
    }) && statuses
        .iter()
        .all(|f| text(&f.attrs, "language").ok().as_deref() == Some("python"))
        && covered(statuses, &route)?;
    let local = !statuses.is_empty()
        && statuses.iter().all(|f| {
            f.object == "structured"
                || (f.object == "partial"
                    && text(&f.attrs, "analysis").ok().as_deref() == Some("structured-cfg/2")
                    && strings(&f.attrs, "gaps").is_ok_and(|g| !g.is_empty())
                    && strings(&f.attrs, "reasons").is_ok_and(|r| {
                        r.iter().all(|r| {
                            [
                                "await",
                                "await_expression",
                                "raise_statement",
                                "throw_statement",
                                "yield",
                                "yield_expression",
                                "yield_statement",
                                "try_statement",
                                "exception-dispatch",
                            ]
                            .contains(&r.as_str())
                        })
                    }))
        });
    Ok(witness
        || local
        || (pattern.clauses.len() == 1
            && pattern.clauses[0].kind == "yield"
            && covered(
                statuses,
                &[
                    "await",
                    "await_expression",
                    "yield",
                    "yield_expression",
                    "yield_statement",
                ],
            )?))
}
