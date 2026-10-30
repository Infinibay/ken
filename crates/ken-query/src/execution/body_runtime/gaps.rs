use super::*;
use context::*;
pub(super) fn restrictions(clause: &Clause, terminal: bool) -> Result<(Vec<String>, Vec<String>)> {
    let mut protected = vec![];
    let mut forbidden = vec![];
    for c in block(clause) {
        if c.kind == "property" && c.name == "paths" && !terminal {
            let e = op(c, 0)?;
            if e.value().trim_matches('"') == "all" {
                continue;
            }
            return Err(invalid("this gap requires paths: all"));
        }
        if c.kind != "forbid" {
            return Err(invalid(if terminal {
                "terminal gap supports forbid assign(binding(...))"
            } else {
                "unsupported interval effect"
            }));
        }
        let effect = op(c, 0)?;
        if !terminal && effect.kind() == "call" && effect.value() == "call" {
            let a = arg(effect, 0)?;
            let role = arg(a, 0)?;
            if !a.value().is_empty() || role.kind() != "role" || effect.len() > 2 {
                return Err(invalid("forbid call requires a bound Callable"));
            }
            if effect.len() == 2 {
                let mode = arg(effect, 1)?;
                if mode.value() != "through" || arg(mode, 0)?.value().trim_matches('"') != "direct"
                {
                    return Err(invalid("forbid call currently requires through: direct"));
                }
            }
            forbidden.push(role.value().into());
            continue;
        }
        if effect.kind() != "call"
            || effect.value() != if terminal { "assign" } else { "write" }
            || effect.len() != 1
        {
            return Err(invalid("gap requires a binding assignment restriction"));
        }
        let a = arg(effect, 0)?;
        let place = arg(a, 0)?;
        if !a.value().is_empty()
            || place.kind() != "call"
            || place.value() != "binding"
            || place.len() != 1
        {
            return Err(invalid("write requires an explicit binding"));
        }
        let b = arg(place, 0)?;
        let role = arg(b, 0)?;
        if !b.value().is_empty() || role.kind() != "role" {
            return Err(invalid("write requires an explicit binding"));
        }
        protected.push(role.value().into());
    }
    if terminal && protected.is_empty() {
        return Err(invalid("terminal gap requires an assignment restriction"));
    }
    Ok((protected, forbidden))
}
impl Context<'_> {
    pub fn interval_ok(
        &mut self,
        state: &State,
        pattern: &BodyPattern,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let Some(start) = &state.last else {
            return Ok(truth(true));
        };
        if state.protected.is_empty()
            && state.forbidden.is_empty()
            && !state.adjacent
            && !pattern.adjacent
        {
            return Ok(truth(true));
        }
        if start == &state.group {
            return Ok(
                if !state.protected.is_empty() || !state.forbidden.is_empty() {
                    unknown("intra_statement_effects_unresolved")
                } else {
                    truth(true)
                },
            );
        }
        let mut forward = BTreeSet::new();
        let mut reverse = BTreeMap::<String, BTreeSet<String>>::new();
        let mut todo = self.successors(start, s)?;
        let mut connected = false;
        while let Some(point) = todo.pop() {
            s.check()?;
            if point == state.group {
                connected = true;
                continue;
            }
            if !forward.insert(point.clone()) {
                continue;
            }
            for child in self.successors(&point, s)? {
                reverse
                    .entry(child.clone())
                    .or_default()
                    .insert(point.clone());
                todo.push(child);
            }
        }
        let mut back = BTreeSet::new();
        let mut todo = vec![state.group.clone()];
        while let Some(point) = todo.pop() {
            s.check()?;
            if back.insert(point.clone()) {
                todo.extend(reverse.get(&point).into_iter().flatten().cloned());
            }
        }
        if !connected {
            return Ok(truth(false));
        }
        let intermediate = forward
            .intersection(&back)
            .cloned()
            .collect::<BTreeSet<_>>();
        if intermediate.contains(start) {
            return Ok(unknown("iteration_context_unresolved"));
        }
        if (state.adjacent || pattern.adjacent) && !intermediate.is_empty() {
            return Ok(truth(false));
        }
        let mut calls_known = truth(true);
        for role in &state.forbidden {
            let Some(target) = node(&state.bindings, role) else {
                calls_known = unknown("forbidden_call_target_unknown");
                continue;
            };
            for group in &intermediate {
                for op in self.parts(group, s)? {
                    if op.kind != "CALL" {
                        continue;
                    }
                    let call = self.call(&op);
                    let targets = if let Some(call) = &call {
                        self.ids("TARGET", &call.id, s)?
                    } else {
                        BTreeSet::new()
                    };
                    let possible = if let Some(call) = &call {
                        self.ids("MAY_TARGET", &call.id, s)?
                    } else {
                        BTreeSet::new()
                    };
                    if targets == BTreeSet::from([target.local_id.clone()])
                        && possible.is_subset(&targets)
                    {
                        return Ok(truth(false));
                    }
                    if targets.len() != 1 || !possible.is_subset(&targets) {
                        calls_known = unknown("intermediate_call_target_incomplete");
                    }
                }
            }
        }
        for role in &state.protected {
            let Some(binding) = node(&state.bindings, role) else {
                return Ok(unknown("protected_binding_unknown"));
            };
            for group in &intermediate {
                for op in self.parts(group, s)? {
                    if self.has("ASSIGNMENT_TARGET", &op.id, &binding.local_id, s)?
                        || self.has("ITERATION_BINDING", &op.id, &binding.local_id, s)?
                    {
                        return Ok(truth(false));
                    }
                }
            }
            if !supported(&self.rows("STORAGE_WRITE_STATUS", Some(&binding.local_id), None, s)?) {
                return Ok(unknown("write_inventory_incomplete"));
            }
            if binding.owner.as_deref() != Some(&self.owner.local_id)
                || !matches!(binding.kind.as_str(), "STORAGE" | "PARAMETER")
            {
                return Ok(unknown("nonlocal_slot_aliases_unresolved"));
            }
            if self.locals.iter().any(|n| n.kind == "CALLABLE") {
                return Ok(unknown("closure_escape_unresolved"));
            }
            for op in self.operations.values() {
                let tokens = strings(&op.attrs, "tokens")?;
                if tokens
                    .iter()
                    .any(|t| matches!(t.as_str(), "&" | "ref" | "out"))
                    || op.native_kind.contains("reference")
                {
                    return Ok(unknown("slot_reference_escape_unresolved"));
                }
            }
        }
        Ok(calls_known)
    }
    pub fn completed_linear_arm(
        &mut self,
        group: &str,
        item: &Clause,
        linear: bool,
        s: &mut dyn BodyServices,
    ) -> Result<bool> {
        if !linear || item.kind == "return" {
            return Ok(true);
        }
        let mut frontier = self.successors(group, s)?;
        let mut seen = BTreeSet::new();
        while let Some(point) = frontier.pop() {
            s.check()?;
            if !seen.insert(point.clone()) {
                return Ok(false);
            }
            if self.parts(&point, s)?.iter().any(|o| {
                matches!(
                    o.kind.as_str(),
                    "BRANCH"
                        | "LOOP"
                        | "TRY"
                        | "SWITCH"
                        | "RETURN"
                        | "THROW"
                        | "BREAK"
                        | "CONTINUE"
                        | "YIELD"
                )
            }) {
                return Ok(false);
            }
            frontier.extend(self.successors(&point, s)?);
        }
        Ok(true)
    }
    pub fn terminal_ok(
        &mut self,
        state: &State,
        item: &Clause,
        pattern: &BodyPattern,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let (roles, _) = restrictions(item, true)?;
        let restricted = roles
            .iter()
            .filter_map(|r| node(&state.bindings, r).map(|n| n.local_id.clone()))
            .collect::<BTreeSet<_>>();
        for id in &restricted {
            if !supported(&self.rows("STORAGE_WRITE_STATUS", Some(id), None, s)?) {
                return Ok(unknown("terminal_write_inventory_unknown"));
            }
        }
        if let Some(last) = &state.last {
            for op in self.parts(last, s)? {
                if matches!(op.kind.as_str(), "ASSIGN" | "UPDATE")
                    && !state.used.contains(&op.id)
                    && !self
                        .ids("ASSIGNMENT_TARGET", &op.id, s)?
                        .is_disjoint(&restricted)
                {
                    return Ok(truth(false));
                }
            }
        }
        let mut frontier = if let Some(last) = &state.last {
            self.successors(last, s)?
        } else {
            vec![state.group.clone()]
        };
        let mut seen = BTreeSet::new();
        while let Some(point) = frontier.pop() {
            s.check()?;
            if !seen.insert(point.clone()) {
                continue;
            }
            for op in self.parts(&point, s)? {
                if !matches!(
                    op.kind.as_str(),
                    "ASSIGN" | "UPDATE" | "BRANCH" | "LOOP" | "TRY" | "SWITCH"
                ) {
                    continue;
                }
                if pattern.linear
                    && matches!(op.kind.as_str(), "BRANCH" | "LOOP" | "TRY" | "SWITCH")
                {
                    return Ok(truth(false));
                }
                if !self
                    .ids("ASSIGNMENT_TARGET", &op.id, s)?
                    .is_disjoint(&restricted)
                {
                    return Ok(truth(false));
                }
            }
            frontier.extend(self.successors(&point, s)?);
        }
        Ok(truth(true))
    }
}
