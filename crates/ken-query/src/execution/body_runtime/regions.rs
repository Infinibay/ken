use super::*;
use context::*;
use ken_program::Operation;
struct Branch {
    layers: Vec<(Arc<BodyPattern>, Vec<Op>)>,
    seed: Bindings,
    base: Bindings,
    overrides: Bindings,
    unknown: bool,
    operation: String,
    iteration: BTreeMap<String, (Op, String)>,
    keyed: BTreeSet<String>,
    linear_arm: bool,
    outputs: BTreeSet<String>,
}
enum Task<'a> {
    Start {
        branch: Arc<Branch>,
        index: usize,
        bindings: Bindings,
        unknown: bool,
    },
    Child {
        branch: Arc<Branch>,
        index: usize,
        bindings: Bindings,
        unknown: bool,
        cursor: Box<BodyCursor<'a>>,
    },
}
pub(super) struct Nesting<'a> {
    graph: &'a dyn GraphRead,
    pending: Vec<Task<'a>>,
}
impl<'a> Nesting<'a> {
    fn new(graph: &'a dyn GraphRead, branches: Vec<Branch>) -> Self {
        let pending = branches
            .into_iter()
            .rev()
            .map(|b| {
                let b = Arc::new(b);
                Task::Start {
                    bindings: b.seed.clone(),
                    unknown: b.unknown,
                    branch: b,
                    index: 0,
                }
            })
            .collect();
        Self { graph, pending }
    }
    pub fn next(&mut self, s: &mut dyn BodyServices) -> Result<Option<Witness>> {
        while let Some(task) = self.pending.pop() {
            s.check()?;
            match task {
                Task::Start {
                    branch,
                    index,
                    bindings,
                    unknown,
                } => {
                    if index == branch.layers.len() {
                        let mut result = branch.base.clone();
                        for name in &branch.outputs {
                            if let Some(value) = bindings.get(name) {
                                result.insert(name.clone(), value.clone());
                            }
                        }
                        result.extend(branch.overrides.clone());
                        return Ok(Some(Witness {
                            bindings: result,
                            unknown,
                            operation: branch.operation.clone(),
                        }));
                    }
                    let (pattern, regions) = &branch.layers[index];
                    for region in regions.iter().rev() {
                        let cursor = BodyCursor::nested(
                            self.graph,
                            pattern.clone(),
                            bindings.clone(),
                            Some(region.clone()),
                            branch.linear_arm,
                            branch.iteration.clone(),
                            branch.keyed.clone(),
                        );
                        self.pending.push(Task::Child {
                            branch: branch.clone(),
                            index,
                            bindings: bindings.clone(),
                            unknown,
                            cursor: Box::new(cursor),
                        });
                    }
                }
                Task::Child {
                    branch,
                    index,
                    bindings,
                    unknown,
                    mut cursor,
                } => {
                    if let Some(matched) = cursor.next(s)? {
                        let mut next = bindings.clone();
                        for name in &branch.layers[index].0.outputs {
                            if branch.outputs.contains(name)
                                && let Some(value) = matched.bindings.get(name)
                            {
                                next.insert(name.clone(), value.clone());
                            }
                        }
                        self.pending.push(Task::Child {
                            branch: branch.clone(),
                            index,
                            bindings,
                            unknown,
                            cursor,
                        });
                        self.pending.push(Task::Start {
                            branch,
                            index: index + 1,
                            bindings: next,
                            unknown: unknown || matched.unknown,
                        });
                    }
                }
            }
        }
        Ok(None)
    }
}
impl<'a> Context<'a> {
    pub fn region_matches(
        &mut self,
        item: &Clause,
        operation: &Operation,
        current: &Bindings,
        pattern: &BodyPattern,
        s: &mut dyn BodyServices,
    ) -> Result<Option<Nesting<'a>>> {
        if item.kind == "if" && operation.kind == "BRANCH" {
            let tests = self.rows("CONTROL_CONDITION", Some(&operation.id), None, s)?;
            if tests.len() != 1 {
                return Ok(None);
            }
            let Some(condition) = self.operations.get(&tests[0].object).cloned() else {
                return Ok(None);
            };
            let expected = op(item, 0)?;
            let mut updated = current.clone();
            let mut result = self.source_matches(expected, &condition, &mut updated, None, s)?;
            if expected.kind() == "binary"
                && matches!(expected.value(), "==" | "!=")
                && expected.len() == 2
            {
                let left = arg(expected, 0)?;
                let right = arg(expected, 1)?;
                if left.kind() == "role"
                    && right.kind() == "literal"
                    && right.value() == "null"
                    && let Some(binding) = node(current, left.value()).filter(|n| n.kind != "VALUE")
                {
                    let mut tests =
                        self.rows("NULL_TEST", Some(&operation.id), Some(&binding.local_id), s)?;
                    tests.extend(self.rows(
                        "UNDEFINED_TEST",
                        Some(&operation.id),
                        Some(&binding.local_id),
                        s,
                    )?);
                    if !tests.is_empty() {
                        let wanted = expected.value() == "==";
                        let mut matched = false;
                        for f in tests {
                            let actual = attr(&f.attrs, "when")?;
                            matched |= actual == ken_program::value::GraphValue::Bool(wanted)
                                || actual.string().as_deref()
                                    == Some(if wanted { "true" } else { "false" });
                        }
                        result = truth(matched);
                    }
                }
            }
            if result.is_false() {
                return Ok(None);
            }
            let controls = pattern
                .controls
                .iter()
                .find(|(c, _)| c == item)
                .map(|(_, p)| p)
                .ok_or_else(|| invalid("BODY conditional has no prepared arm patterns"))?;
            let mut layers = vec![];
            for (position, arm) in controls.iter().enumerate() {
                let role = if position == 0 {
                    "consequence"
                } else {
                    "alternative"
                };
                let regions = self
                    .children
                    .get(&operation.id)
                    .into_iter()
                    .flatten()
                    .filter(|o| o.role == role)
                    .cloned()
                    .collect();
                layers.push((Arc::new(arm.clone()), regions));
            }
            let b = Branch {
                layers,
                seed: updated.clone(),
                base: updated,
                overrides: Bindings::new(),
                unknown: result.is_unknown(),
                operation: operation.id.clone(),
                iteration: self.iteration.clone(),
                keyed: self.keyed.clone(),
                linear_arm: pattern.linear,
                outputs: pattern.outputs.iter().cloned().collect(),
            };
            return Ok(Some(Nesting::new(self.graph, vec![b])));
        }
        if item.kind != "iterate" || operation.kind != "LOOP" {
            return Ok(None);
        }
        let expected = op(item, 0)?;
        let container = if expected.kind() == "index" {
            arg(expected, 0)?
        } else {
            expected
        };
        let mut collection = node(current, container.value());
        let loop_key = if expected.kind() == "index" {
            let key = arg(expected, 1)?;
            if key.kind() == "role" {
                node(current, key.value())
            } else {
                None
            }
        } else {
            None
        };
        let unbound = collection.is_none();
        if unbound && expected.kind() != "role" {
            return Ok(None);
        }
        let constraints = block(item)
            .iter()
            .filter(|c| c.kind == "property")
            .collect::<Vec<_>>();
        for c in &constraints {
            if c.name == "async"
                && attr(&operation.attrs, "async")?.truthy() != (op(c, 0)?.value() == "true")
            {
                return Ok(None);
            }
        }
        if flag(item, "keys") {
            let Some(collection) = &collection else {
                return Ok(None);
            };
            let owner = self.owner.local_id.clone();
            if !self.has("ITERATES_KEYS_CALLS", &owner, &collection.local_id, s)? {
                return Ok(None);
            }
        }
        let mut sources = self.ids("ITERATION_SOURCE", &operation.id, s)?;
        let mut accessed = BTreeSet::new();
        if let Some(collection) = &collection
            && expected.kind() != "index"
        {
            for source in &sources {
                if source != &collection.local_id
                    && self.has("RECEIVER", source, &collection.local_id, s)?
                {
                    accessed.insert(source.clone());
                }
            }
            if !accessed.is_empty() {
                sources = accessed.clone();
            }
        }
        if unbound {
            if sources.len() != 1 {
                return Ok(None);
            }
            let Value::Node(n) = self.value_node(sources.iter().next().unwrap(), "STORAGE") else {
                unreachable!()
            };
            collection = Some(n);
        }
        let collection = collection.unwrap();
        if flag(item, "copy") {
            let mut snapshots = BTreeSet::new();
            for copy in self.ids("ITERATION_SNAPSHOT", &operation.id, s)? {
                if self.has("COLLECTION_SNAPSHOT_OF", &copy, &collection.local_id, s)? {
                    snapshots.insert(copy);
                }
            }
            let mut derived = snapshots;
            for _ in 0..4 {
                let mut reached = BTreeSet::new();
                for value in &derived {
                    for f in self.rows("ASSIGNED_FROM", None, Some(value), s)? {
                        if !derived.contains(&f.subject) {
                            reached.insert(f.subject.clone());
                        }
                    }
                }
                if reached.is_empty() {
                    break;
                }
                derived.extend(reached);
            }
            sources = sources.intersection(&derived).cloned().collect();
            if sources.is_empty() {
                return Ok(None);
            }
        }
        let origin = constraints.iter().find(|c| c.name == "origin");
        let mut actual_collection = collection.clone();
        let mut source_id = if let Some(origin) = origin {
            let Some(origin) = node(current, op(origin, 0)?.value()) else {
                return Ok(None);
            };
            if !self.has("ITERATION_ORIGIN", &operation.id, &origin.local_id, s)?
                || sources.len() != 1
            {
                return Ok(None);
            }
            if collection.kind == "VALUE"
                && self
                    .producers
                    .get(&collection.local_id)
                    .unwrap_or(&collection.local_id)
                    != &origin.local_id
            {
                return Ok(None);
            }
            let id = sources.iter().next().unwrap().clone();
            let Value::Node(n) = self.value_node(&id, "STORAGE") else {
                unreachable!()
            };
            actual_collection = n;
            id
        } else if (flag(item, "copy") || !accessed.is_empty()) && sources.len() == 1 {
            sources.iter().next().unwrap().clone()
        } else if collection.kind == "VALUE" {
            self.producers
                .get(&collection.local_id)
                .unwrap_or(&collection.local_id)
                .clone()
        } else {
            collection.local_id.clone()
        };
        if origin.is_none()
            && !flag(item, "copy")
            && expected.kind() != "index"
            && self.has("ENTITY", &source_id, "STORAGE", s)?
            && !self.has("ITERATION_ENTRY_SOURCE", &operation.id, &source_id, s)?
        {
            return Ok(None);
        }
        if !sources.contains(&source_id) {
            let mut bucket = None;
            for candidate in &sources {
                if !self.has("CONTAINER", candidate, &collection.local_id, s)? {
                    continue;
                }
                if let Some(key) = &loop_key
                    && !self.has("INDEX", candidate, &key.local_id, s)?
                {
                    continue;
                }
                bucket = Some(candidate.clone());
                break;
            }
            let Some(bucket) = bucket else {
                return Ok(None);
            };
            source_id = bucket;
        }
        let _ = source_id;
        let nested = pattern
            .nested
            .iter()
            .find(|(c, _)| c == item)
            .map(|(_, p)| Arc::new(p.clone()))
            .ok_or_else(|| invalid("BODY iteration has no prepared nested pattern"))?;
        let mut branches = vec![];
        for element in self.rows("ITERATION_BINDING", Some(&operation.id), None, s)? {
            let role = text(&element.attrs, "role")?;
            if (flag(item, "keys") && !matches!(role.as_str(), "first" | "key"))
                || (!flag(item, "keys") && role != "value")
            {
                continue;
            }
            let Some(binding) = self
                .locals
                .iter()
                .find(|n| n.local_id == element.object)
                .cloned()
            else {
                continue;
            };
            for body in self.rows("ITERATION_BODY", Some(&operation.id), None, s)? {
                let Some(region) = self.operations.get(&body.object).cloned() else {
                    continue;
                };
                let value_id = format!("{}/iteration-value/{}", operation.id, element.object);
                let mut iteration = self.iteration.clone();
                iteration.insert(
                    value_id.clone(),
                    (Arc::new(operation.clone()), element.object.clone()),
                );
                let mut keyed = self.keyed.clone();
                if flag(item, "keys") {
                    keyed.insert(operation.id.clone());
                }
                let mut seed = current.clone();
                seed.insert(item.role.clone(), self.value_node(value_id, "VALUE"));
                let mut overrides = Bindings::new();
                if !item.alias.is_empty() {
                    let reference = self.reference(operation);
                    seed.insert(item.alias.clone(), reference.clone());
                    overrides.insert(item.alias.clone(), reference);
                }
                if let Some(body) = constraints.iter().find(|c| c.name == "body") {
                    overrides.insert(op(body, 0)?.value().into(), self.reference(&region));
                }
                if unbound {
                    overrides.insert(
                        expected.value().into(),
                        Value::Node(actual_collection.clone()),
                    );
                }
                if pattern.outputs.contains(&item.role) {
                    overrides.insert(item.role.clone(), Value::Node(binding.clone()));
                }
                branches.push(Branch {
                    layers: vec![(nested.clone(), vec![region])],
                    seed,
                    base: current.clone(),
                    overrides,
                    unknown: false,
                    operation: operation.id.clone(),
                    iteration,
                    keyed,
                    linear_arm: false,
                    outputs: pattern.outputs.iter().cloned().collect(),
                });
            }
        }
        Ok(Some(Nesting::new(self.graph, branches)))
    }
}
