//! One-iteration condition reads never flow across the loop back edge.
use super::*;
type Origins = BTreeSet<Option<String>>;
type State = BTreeMap<String, Origins>;
struct Iteration<'a, 'b, 'c> {
    owner: &'a Owner<'b, 'c>,
    children: &'a BTreeMap<String, Vec<usize>>,
    ids: &'a BTreeSet<String>,
    work: usize,
    pending: BTreeMap<String, Origins>,
    order: Vec<String>,
}
impl Iteration<'_, '_, '_> {
    fn snapshot(&self, value: &str, state: &State) -> Origins {
        if self.owner.locals.contains(value) {
            return state
                .get(value)
                .cloned()
                .unwrap_or_else(|| [None].into_iter().collect());
        }
        if self
            .owner
            .input
            .ctx
            .entities
            .get(value)
            .is_some_and(|e| matches!(e.kind.as_str(), "STORAGE" | "MEMBER"))
        {
            [None].into_iter().collect()
        } else {
            [Some(value.into())].into_iter().collect()
        }
    }
    fn walk(
        &mut self,
        i: usize,
        mut state: State,
        depth: usize,
    ) -> std::result::Result<Option<State>, ()> {
        self.work += 1;
        if self.work > 100000 || depth > 64 {
            return Err(());
        }
        let op = self.owner.input.ctx.op(i);
        if let Some(arms) = self.owner.arms.get(&op.id) {
            if !arms.contains_key("consequence") || arms.values().any(|arm| !self.ids.contains(arm))
            {
                return Err(());
            }
            for (read, binding) in self.owner.conditions.get(&op.id).into_iter().flatten() {
                if !self.pending.contains_key(read) {
                    self.order.push(read.clone());
                }
                let origins = self.snapshot(binding, &state);
                self.pending
                    .entry(read.clone())
                    .or_default()
                    .extend(origins);
            }
            let mut states = Vec::new();
            for role in ["consequence", "alternative"] {
                let branch = if let Some(id) = arms.get(role) {
                    self.walk(
                        self.owner.input.ctx.ids[id.as_str()],
                        state.clone(),
                        depth + 1,
                    )?
                } else {
                    Some(state.clone())
                };
                if let Some(branch) = branch {
                    states.push(branch);
                }
            }
            if states.is_empty() {
                return Ok(None);
            }
            let mut merged = State::new();
            for binding in states
                .iter()
                .flat_map(|state| state.keys().cloned())
                .collect::<BTreeSet<_>>()
            {
                let origins = states
                    .iter()
                    .flat_map(|state| {
                        state
                            .get(&binding)
                            .cloned()
                            .unwrap_or_else(|| [None].into_iter().collect())
                    })
                    .collect();
                merged.insert(binding, origins);
            }
            return Ok(Some(merged));
        }
        if let Some(target) = self.owner.input.targets.get(&op.id) {
            let value = &self.owner.input.values[&op.id];
            let origins = self.snapshot(value, &state);
            state.insert(target.clone(), origins);
            return Ok(Some(state));
        }
        if op.kind == "RETURN"
            || matches!(
                op.native_kind.as_str(),
                "break_statement"
                    | "continue_statement"
                    | "break_expression"
                    | "continue_expression"
            )
        {
            return Ok(None);
        }
        if CONTAINERS.contains(&op.native_kind.as_str())
            || matches!(
                op.native_kind.as_str(),
                "block" | "statement_block" | "compound_statement" | "else_clause"
            )
        {
            for &child in self.children.get(&op.id).into_iter().flatten() {
                let Some(next) = self.walk(child, state, depth + 1)? else {
                    return Ok(None);
                };
                state = next;
            }
            return Ok(Some(state));
        }
        let mut todo = self.children.get(&op.id).cloned().unwrap_or_default();
        let mut seen = BTreeSet::new();
        while let Some(i) = todo.pop() {
            let child = self.owner.input.ctx.op(i);
            if !seen.insert(child.id.as_str())
                || self.owner.input.targets.contains_key(&child.id)
                || self.owner.arms.contains_key(&child.id)
                || child.kind == "RETURN"
                || matches!(
                    child.native_kind.as_str(),
                    "break_statement"
                        | "continue_statement"
                        | "break_expression"
                        | "continue_expression"
                )
            {
                return Err(());
            }
            todo.extend(self.children.get(&child.id).into_iter().flatten());
        }
        Ok(Some(state))
    }
}
impl Owner<'_, '_> {
    pub(super) fn iteration_origins(&self, output: &mut Vec<Fact>) -> Result<()> {
        let input = self.input;
        let language = attributes::get(&self.entity()?.attrs, "language")?;
        if self.diagnostics
            || input.nested.contains(&self.id)
            || input.dynamic.contains(&self.id)
            || !language.as_ref().and_then(Value::as_str).is_some_and(|l| {
                matches!(
                    l,
                    "python"
                        | "javascript"
                        | "typescript"
                        | "java"
                        | "csharp"
                        | "go"
                        | "rust"
                        | "cpp"
                )
            })
            || !self.ops.iter().any(|&i| input.ctx.op(i).kind == "LOOP")
        {
            return Ok(());
        }
        if self.ops.len() > 100000 {
            return Ok(());
        }
        for &i in &self.ops {
            let op = input.ctx.op(i);
            if BLOCKED.contains(&op.native_kind.as_str())
                || attributes::tokens(&op.attrs)?
                    .iter()
                    .any(|t| matches!(t.as_str(), "ref" | "out" | "unsafe" | "&"))
            {
                return Ok(());
            }
        }
        let mut children = BTreeMap::<String, Vec<usize>>::new();
        for &i in &self.ops {
            if let Some(parent) = &input.ctx.op(i).parent {
                children.entry(parent.clone()).or_default().push(i);
            }
        }
        for kids in children.values_mut() {
            kids.sort_by_key(|&i| {
                let op = input.ctx.op(i);
                (op.start, op.end)
            });
        }
        let mut scopes = BTreeMap::<String, BTreeSet<String>>::new();
        for &i in &self.ops {
            let op = input.ctx.op(i);
            let Some(target) = input.targets.get(&op.id) else {
                continue;
            };
            if !matches!(
                op.native_kind.as_str(),
                "variable_declarator" | "short_var_declaration" | "let_declaration"
            ) {
                continue;
            }
            let mut ancestor = input.ctx.parent(i);
            for _ in 0..64 {
                let Some(a) = ancestor else {
                    break;
                };
                let a = input.ctx.op(a);
                if matches!(
                    a.native_kind.as_str(),
                    "block" | "statement_block" | "compound_statement"
                ) {
                    scopes
                        .entry(target.clone())
                        .or_default()
                        .insert(a.id.clone());
                    break;
                }
                ancestor = a
                    .parent
                    .as_deref()
                    .and_then(|p| input.ctx.ids.get(p))
                    .copied();
            }
        }
        for &looping in self.ops.iter().filter(|&&i| input.ctx.op(i).kind == "LOOP") {
            let loop_op = input.ctx.op(looping);
            let bodies = children
                .get(&loop_op.id)
                .into_iter()
                .flatten()
                .copied()
                .filter(|&i| input.ctx.op(i).role == "body")
                .collect::<Vec<_>>();
            if bodies.len() != 1 {
                continue;
            }
            let body = bodies[0];
            let mut descendants = Vec::new();
            let mut todo = vec![body];
            let mut seen = BTreeSet::new();
            let mut cyclic = false;
            while let Some(i) = todo.pop() {
                let op = input.ctx.op(i);
                if !seen.insert(op.id.as_str()) {
                    cyclic = true;
                    break;
                }
                descendants.push(i);
                if op.kind != "LOOP" {
                    todo.extend(children.get(&op.id).into_iter().flatten());
                }
            }
            if cyclic {
                continue;
            }
            let ids = descendants
                .iter()
                .map(|&i| input.ctx.op(i).id.clone())
                .collect::<BTreeSet<_>>();
            let mut unsupported = false;
            for &i in &descendants {
                let op = input.ctx.op(i);
                unsupported |= matches!(
                    op.kind.as_str(),
                    "LOOP"
                        | "TRY"
                        | "THROW"
                        | "YIELD"
                        | "AWAIT"
                        | "RESOURCE_SCOPE"
                        | "MATCH"
                        | "IMPORT"
                        | "EXPORT"
                ) || BLOCKED.contains(&op.native_kind.as_str())
                    || (op.kind == "BRANCH" && !self.arms.contains_key(&op.id))
                    || (op.kind == "ASSIGN"
                        && (!input.targets.contains_key(&op.id)
                            || !input.values.contains_key(&op.id)
                            || !self.locals.contains(&input.targets[&op.id])))
                    || attributes::tokens(&op.attrs)?.iter().any(|t| {
                        matches!(
                            t.as_str(),
                            "ref"
                                | "out"
                                | "unsafe"
                                | "&"
                                | "*"
                                | "++"
                                | "--"
                                | "+="
                                | "-="
                                | "*="
                                | "/="
                                | "%="
                                | "&="
                                | "|="
                                | "^="
                                | "<<="
                                | ">>="
                                | "??="
                                | "&&="
                                | "||="
                        )
                    });
            }
            if unsupported {
                continue;
            }
            let bindings = descendants
                .iter()
                .filter_map(|&i| input.targets.get(&input.ctx.op(i).id))
                .collect::<BTreeSet<_>>();
            if scopes
                .iter()
                .any(|(binding, scopes)| scopes.len() > 1 && bindings.contains(binding))
            {
                continue;
            }
            let mut regions = [input.ctx.op(body).id.clone()]
                .into_iter()
                .collect::<BTreeSet<_>>();
            regions.extend(
                self.arms
                    .values()
                    .flat_map(|arms| arms.values())
                    .filter(|arm| ids.contains(*arm))
                    .cloned(),
            );
            let mut misplaced = false;
            for &i in &descendants {
                if !input.targets.contains_key(&input.ctx.op(i).id) {
                    continue;
                }
                let mut ancestor = input.ctx.parent(i);
                let mut seen = BTreeSet::new();
                while let Some(a) = ancestor.filter(|&i| !regions.contains(&input.ctx.op(i).id)) {
                    if !seen.insert(a) {
                        misplaced = true;
                        break;
                    }
                    let op = input.ctx.op(a);
                    if !CONTAINERS.contains(&op.native_kind.as_str())
                        && !matches!(
                            op.native_kind.as_str(),
                            "block" | "statement_block" | "compound_statement" | "else_clause"
                        )
                    {
                        misplaced = true;
                        break;
                    }
                    ancestor = input.ctx.parent(a);
                }
                if ancestor.is_none() {
                    misplaced = true;
                }
            }
            if misplaced {
                continue;
            }
            let mut analysis = Iteration {
                owner: self,
                children: &children,
                ids: &ids,
                work: 0,
                pending: BTreeMap::new(),
                order: Vec::new(),
            };
            if analysis.walk(body, State::new(), 0).is_err() {
                continue;
            }
            for read in &analysis.order {
                let origins = &analysis.pending[read];
                for origin in origins.iter().filter_map(|v| v.as_ref()) {
                    let op = input.ctx.op(input.ctx.ids[read.as_str()]);
                    output.push(fact(read,"READ_ORIGIN",origin,Some(format!("{}:{}",self.entity()?.path,op.line)),json!({"basis":"evaluated-condition-input/1","analysis":"iteration-local-inputs/1","modality":if origins.len()==1{"must"}else{"may"}})));
                }
            }
        }
        Ok(())
    }
}
