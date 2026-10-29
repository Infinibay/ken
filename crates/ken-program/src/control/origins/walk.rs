//! Work-bounded evaluation snapshots and correlated path states.
use super::*;
impl Owner<'_, '_> {
    pub(super) fn snapshot(
        &mut self,
        value: &str,
        environment: &Environment,
        depth: usize,
    ) -> std::result::Result<Cases, &'static str> {
        self.work += 1;
        if self.work > 100000 {
            return Err("expression-work");
        }
        if depth > 32 {
            return Err("expression-depth");
        }
        if self.locals.contains(value) {
            return Ok(environment
                .get(&Slot::Binding(value.into()))
                .cloned()
                .unwrap_or_else(unknown));
        }
        for (position, operand) in self
            .input
            .expressions
            .get(value)
            .cloned()
            .unwrap_or_default()
        {
            if !self.expression_pending.contains_key(value) {
                self.expression_order.push(value.into());
            }
            self.expression_pending
                .entry(value.into())
                .or_default()
                .entry(position)
                .or_default();
            let cases = self.snapshot(&operand, environment, depth + 1)?;
            self.expression_pending
                .get_mut(value)
                .unwrap()
                .get_mut(&position)
                .unwrap()
                .extend(cases);
        }
        if self
            .input
            .ctx
            .entities
            .get(value)
            .is_some_and(|e| matches!(e.kind.as_str(), "STORAGE" | "MEMBER"))
        {
            return Ok(unknown());
        }
        Ok([(Some(value.into()), None)].into_iter().collect())
    }
    pub(super) fn walk(
        &mut self,
        region: &str,
        environment: Environment,
        depth: usize,
    ) -> std::result::Result<Vec<Environment>, &'static str> {
        if depth > 32 {
            return Err("branch-depth");
        }
        let mut states = vec![environment];
        for i in self.events.get(region).cloned().unwrap_or_default() {
            self.work += states.len();
            if self.work > 100000 {
                return Err("flow-work");
            }
            let op = self.input.ctx.op(i);
            let mut continuing = Vec::new();
            if let Some(arms) = self.arms.get(&op.id).cloned() {
                for state in states {
                    for (read, binding) in self.conditions.get(&op.id).cloned().unwrap_or_default()
                    {
                        if !self.read_pending.contains_key(&read) {
                            self.read_order.push(read.clone());
                        }
                        self.read_pending.entry(read.clone()).or_default();
                        let cases = self.snapshot(&binding, &state, 0)?;
                        self.read_pending.get_mut(&read).unwrap().extend(cases);
                    }
                    continuing.extend(self.walk(&arms["consequence"], state.clone(), depth + 1)?);
                    continuing.extend(if let Some(alternative) = arms.get("alternative") {
                        self.walk(alternative, state, depth + 1)?
                    } else {
                        vec![state]
                    });
                    if continuing.len() > 256 {
                        return Err("flow-states");
                    }
                }
                if !continuing.is_empty() && self.member_writes.is_empty() {
                    let bindings = continuing
                        .iter()
                        .flat_map(|state| state.keys().cloned())
                        .collect::<BTreeSet<_>>();
                    let mut merged = Environment::new();
                    for binding in bindings {
                        let cases = continuing
                            .iter()
                            .flat_map(|state| state.get(&binding).cloned().unwrap_or_else(unknown))
                            .collect::<Cases>();
                        self.work += cases.len();
                        if cases.len() > 256 || self.work > 100000 {
                            return Err("flow-work");
                        }
                        merged.insert(binding, cases);
                    }
                    continuing = vec![merged];
                }
            } else if op.kind == "THROW" {
                return Ok(Vec::new());
            } else if let Some(target) = self.input.targets.get(&op.id).cloned() {
                for mut state in states {
                    let value = self.input.values[&op.id].clone();
                    let rhs = self.snapshot(&value, &state, 0)?;
                    if !self.assignment_pending.contains_key(&op.id) {
                        self.assignment_order.push(op.id.clone());
                    }
                    self.assignment_pending
                        .entry(op.id.clone())
                        .or_default()
                        .extend(rhs.clone());
                    if self.member_writes.contains_key(&op.id) {
                        let member = self.input.members[&target].clone();
                        for (origin, _) in self.snapshot(&member, &state, 0)? {
                            if let Some(origin) =
                                origin.filter(|origin| self.input.allocations.contains(origin))
                            {
                                state.insert(
                                    Slot::Field(
                                        origin,
                                        self.input.ctx.entities[target.as_str()].name.clone(),
                                    ),
                                    [(Some(value.clone()), Some(op.id.clone()))]
                                        .into_iter()
                                        .collect(),
                                );
                            }
                        }
                    } else {
                        state.insert(
                            Slot::Binding(target.clone()),
                            rhs.into_iter()
                                .map(|(value, _)| (value, Some(op.id.clone())))
                                .collect(),
                        );
                    }
                    continuing.push(state);
                }
            } else {
                for state in states {
                    if let Some(returned) = self.input.returns.get(&op.id).cloned() {
                        *self.return_states.entry(op.id.clone()).or_default() += 1;
                        let cases = self.snapshot(&returned, &state, 0)?;
                        self.pending
                            .entry(op.id.clone())
                            .or_default()
                            .extend(cases.clone());
                        let origins = cases
                            .into_iter()
                            .filter_map(|(value, _)| {
                                value.filter(|v| {
                                    self.input.allocations.contains(v) && !self.escaped.contains(v)
                                })
                            })
                            .collect::<BTreeSet<_>>();
                        for (slot, writes) in &state {
                            if let Slot::Field(origin, field) = slot
                                && origins.contains(origin)
                            {
                                for (_, write) in writes {
                                    if let Some(write) = write {
                                        *self
                                            .field_returns
                                            .entry((
                                                op.id.clone(),
                                                origin.clone(),
                                                field.clone(),
                                                write.clone(),
                                            ))
                                            .or_default() += 1;
                                    }
                                }
                            }
                        }
                    } else if self.input.arguments.contains_key(&op.id)
                        || self.input.receiver_reads.contains_key(&op.id)
                    {
                        for (position, storage) in self
                            .input
                            .arguments
                            .get(&op.id)
                            .cloned()
                            .unwrap_or_default()
                        {
                            let cases = self.snapshot(&storage, &state, 0)?;
                            if !self.arg_pending.contains_key(&op.id) {
                                self.arg_order.push(op.id.clone());
                            }
                            self.arg_pending
                                .entry(op.id.clone())
                                .or_default()
                                .entry((position, storage))
                                .or_default()
                                .extend(cases);
                        }
                        for (read, binding) in self
                            .input
                            .receiver_reads
                            .get(&op.id)
                            .cloned()
                            .unwrap_or_default()
                        {
                            if !self.read_pending.contains_key(&read) {
                                self.read_order.push(read.clone());
                            }
                            self.read_pending.entry(read.clone()).or_default();
                            let cases = self.snapshot(&binding, &state, 0)?;
                            self.read_pending.get_mut(&read).unwrap().extend(cases);
                        }
                        continuing.push(state);
                    }
                }
            }
            states = continuing;
            if states.is_empty() {
                break;
            }
        }
        Ok(states)
    }
}
