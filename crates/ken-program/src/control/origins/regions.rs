//! Owner admission and statement regions define the supported local-flow boundary.
use super::*;
impl<'a, 'b> Owner<'a, 'b> {
    pub(super) fn prepare(
        input: &'a Inputs<'b>,
        id: &str,
        diagnostic_paths: Option<&BTreeSet<String>>,
    ) -> Result<Option<Self>> {
        let entity = input.ctx.entity(id)?;
        if entity.kind != "CALLABLE" {
            return Ok(None);
        }
        let ops = input.ctx.owners.get(id).cloned().unwrap_or_default();
        let return_ops = ops
            .iter()
            .copied()
            .filter(|&i| input.returns.contains_key(&input.ctx.op(i).id))
            .collect::<Vec<_>>();
        if return_ops.is_empty()
            && !ops.iter().any(|&i| {
                input.arguments.contains_key(&input.ctx.op(i).id)
                    || input.receiver_reads.contains_key(&input.ctx.op(i).id)
            })
            && !ops.iter().any(|&i| {
                matches!(
                    input.ctx.op(i).native_kind.as_str(),
                    "if_statement" | "elif_clause"
                ) || input.targets.contains_key(&input.ctx.op(i).id)
            })
        {
            return Ok(None);
        }
        let locals = input.locals.get(id).cloned().unwrap_or_default();
        let member_writes = ops
            .iter()
            .filter_map(|&i| {
                let op = input.ctx.op(i);
                let target = input.targets.get(&op.id)?;
                input
                    .members
                    .get(target)
                    .filter(|base| locals.contains(*base))
                    .map(|_| (op.id.clone(), target.clone()))
            })
            .collect();
        let diagnostics = diagnostic_paths
            .map_or(!input.ctx.graph.diagnostics.is_empty(), |paths| {
                paths.contains(&entity.path)
            });
        let mut owner = Self {
            input,
            id: id.into(),
            ops,
            locals,
            parameters: input.parameters.get(id).cloned().unwrap_or_default(),
            member_writes,
            return_ops,
            body: String::new(),
            arms: BTreeMap::new(),
            conditions: BTreeMap::new(),
            regions: BTreeSet::new(),
            reason: String::new(),
            diagnostics,
            events: BTreeMap::new(),
            escaped: BTreeSet::new(),
            work: 0,
            pending: BTreeMap::new(),
            arg_pending: BTreeMap::new(),
            expression_pending: BTreeMap::new(),
            assignment_pending: BTreeMap::new(),
            read_pending: BTreeMap::new(),
            field_returns: BTreeMap::new(),
            return_states: BTreeMap::new(),
            arg_order: Vec::new(),
            expression_order: Vec::new(),
            assignment_order: Vec::new(),
            read_order: Vec::new(),
        };
        let language = attributes::get(&entity.attrs, "language")?;
        let language = language.as_ref().and_then(Value::as_str).unwrap_or("");
        if diagnostics {
            owner.reason = "diagnostics".into();
        } else if !matches!(
            language,
            "python" | "javascript" | "typescript" | "java" | "csharp" | "go" | "rust" | "cpp"
        ) {
            owner.reason = "language".into();
        } else if input.nested.contains(id) || input.dynamic.contains(id) {
            owner.reason = "nested-or-dynamic-execution".into();
        } else {
            for &i in &owner.ops {
                let op = input.ctx.op(i);
                if matches!(
                    op.kind.as_str(),
                    "LOOP"
                        | "TRY"
                        | "YIELD"
                        | "AWAIT"
                        | "RESOURCE_SCOPE"
                        | "MATCH"
                        | "IMPORT"
                        | "EXPORT"
                ) || BLOCKED.contains(&op.native_kind.as_str())
                    || (op.kind == "THROW"
                        && !matches!(
                            op.native_kind.as_str(),
                            "raise_statement" | "throw_statement"
                        ))
                    || (op.kind == "BRANCH"
                        && !matches!(op.native_kind.as_str(), "if_statement" | "elif_clause")
                        && !owner.opaque_rhs(i))
                    || attributes::tokens(&op.attrs)?.iter().any(|t| {
                        matches!(
                            t.as_str(),
                            "ref"
                                | "out"
                                | "unsafe"
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
                    })
                {
                    owner.reason = "control-or-indirect-write".into();
                    break;
                }
            }
        }
        let bodies = owner
            .ops
            .iter()
            .copied()
            .filter(|&i| {
                input.ctx.op(i).role == "body"
                    && input
                        .ctx
                        .parent(i)
                        .is_some_and(|p| input.ctx.op(p).kind == "FUNCTION")
            })
            .collect::<Vec<_>>();
        if bodies.len() != 1 {
            owner.set_reason("body");
        } else {
            owner.body = input.ctx.op(bodies[0]).id.clone();
        }
        let branches = owner
            .ops
            .iter()
            .copied()
            .filter(|&i| {
                matches!(
                    input.ctx.op(i).native_kind.as_str(),
                    "if_statement" | "elif_clause"
                )
            })
            .collect::<Vec<_>>();
        let branch_ids = branches
            .iter()
            .map(|&i| input.ctx.op(i).id.clone())
            .collect::<BTreeSet<_>>();
        for &i in &owner.ops {
            let read = input.ctx.op(i);
            let Some(binding) = input.references.get(&read.id) else {
                continue;
            };
            let mut current = i;
            let mut seen = BTreeSet::new();
            while let Some(parent) = input.ctx.parent(current) {
                if !seen.insert(current) {
                    break;
                }
                let p = input.ctx.op(parent);
                if branch_ids.contains(&p.id) {
                    if input.ctx.op(current).role == "condition" {
                        owner
                            .conditions
                            .entry(p.id.clone())
                            .or_default()
                            .push((read.id.clone(), binding.clone()));
                    }
                    break;
                }
                current = parent;
            }
        }
        owner.arms = branch_ids
            .into_iter()
            .map(|id| (id, BTreeMap::new()))
            .collect();
        let mut alternatives = BTreeMap::<String, Vec<String>>::new();
        for &i in &owner.ops {
            let op = input.ctx.op(i);
            if let Some(parent) = op.parent.as_ref().filter(|p| owner.arms.contains_key(*p)) {
                if op.role == "consequence" {
                    owner
                        .arms
                        .get_mut(parent)
                        .unwrap()
                        .insert(op.role.clone(), op.id.clone());
                }
                if op.role == "alternative" {
                    alternatives
                        .entry(parent.clone())
                        .or_default()
                        .push(op.id.clone());
                }
            }
        }
        for (parent, mut chain) in alternatives {
            chain.sort_by_key(|id| input.ctx.op(input.ctx.ids[id.as_str()]).start);
            owner
                .arms
                .get_mut(&parent)
                .unwrap()
                .insert("alternative".into(), chain[0].clone());
            for pair in chain.windows(2) {
                if let Some(arms) = owner.arms.get_mut(&pair[0]) {
                    arms.insert("alternative".into(), pair[1].clone());
                } else {
                    owner.set_reason("branch-grammar");
                }
            }
        }
        owner.regions.insert(owner.body.clone());
        for arms in owner.arms.values() {
            owner.regions.extend(arms.values().cloned());
        }
        for &i in &owner.ops.clone() {
            let op = input.ctx.op(i);
            if let Some(target) = input.targets.get(&op.id)
                && ((!owner.locals.contains(target) && !owner.member_writes.contains_key(&op.id))
                    || owner.region(i).is_none()
                    || attributes::tokens(&op.attrs)?
                        .iter()
                        .any(|t| t.ends_with('=') && !matches!(t.as_str(), "=" | ":=")))
            {
                owner.set_reason("nonlocal-or-nested-write");
            }
        }
        if owner.ops.iter().any(|&i| {
            let op = input.ctx.op(i);
            (matches!(op.kind.as_str(), "RETURN" | "THROW") || owner.arms.contains_key(&op.id))
                && owner.region(i).is_none()
        }) {
            owner.set_reason("nested-return");
        }
        if owner
            .arms
            .values()
            .any(|arms| !arms.contains_key("consequence"))
        {
            owner.set_reason("branch-grammar");
        }
        if owner.ops.iter().any(|&i| {
            input.ctx.op(i).kind == "ASSIGN" && !input.targets.contains_key(&input.ctx.op(i).id)
        }) {
            owner.set_reason("unmodeled-assignment");
        }
        let scoped = match language {
            "javascript" | "typescript" => Some("lexical_declaration"),
            "java" => Some("local_variable_declaration"),
            "csharp" => Some("variable_declaration"),
            _ => None,
        };
        if let Some(scoped) = scoped {
            let mut blocks = BTreeMap::<String, BTreeSet<String>>::new();
            for &i in &owner.ops {
                let op = input.ctx.op(i);
                let Some(binding) = input
                    .targets
                    .get(&op.id)
                    .filter(|b| owner.locals.contains(*b))
                else {
                    continue;
                };
                if op.kind != "ASSIGN" || op.native_kind != "variable_declarator" {
                    continue;
                }
                let mut ancestor = input.ctx.parent(i);
                let mut wrapper = "";
                for _ in 0..64 {
                    let Some(a) = ancestor else {
                        break;
                    };
                    let a = input.ctx.op(a);
                    if wrapper.is_empty()
                        && matches!(
                            a.native_kind.as_str(),
                            "lexical_declaration"
                                | "local_variable_declaration"
                                | "variable_declaration"
                                | "field_declaration"
                        )
                    {
                        wrapper = &a.native_kind;
                    }
                    if matches!(
                        a.native_kind.as_str(),
                        "block" | "statement_block" | "compound_statement"
                    ) {
                        if wrapper == scoped {
                            blocks
                                .entry(binding.clone())
                                .or_default()
                                .insert(a.id.clone());
                        }
                        break;
                    }
                    ancestor = a
                        .parent
                        .as_deref()
                        .and_then(|p| input.ctx.ids.get(p))
                        .copied();
                }
            }
            if blocks.values().any(|b| b.len() > 1) {
                owner.set_reason("shadowed-binding");
            }
        }
        for &i in &owner.return_ops {
            owner
                .pending
                .insert(input.ctx.op(i).id.clone(), Cases::new());
        }
        Ok(Some(owner))
    }
    fn opaque_rhs(&self, i: usize) -> bool {
        let op = self.input.ctx.op(i);
        if !matches!(
            op.native_kind.as_str(),
            "conditional_expression" | "ternary_expression"
        ) {
            return false;
        }
        let mut current = i;
        for _ in 0..32 {
            let Some(parent) = self.input.ctx.parent(current) else {
                break;
            };
            if self
                .member_writes
                .contains_key(&self.input.ctx.op(parent).id)
            {
                return matches!(self.input.ctx.op(current).role.as_str(), "right" | "value");
            }
            current = parent;
        }
        false
    }
    pub(super) fn region(&self, i: usize) -> Option<String> {
        let mut current = Some(i);
        let mut seen = BTreeSet::new();
        while let Some(i) = current {
            if !seen.insert(i) {
                return None;
            }
            let op = self.input.ctx.op(i);
            if self.regions.contains(&op.id) {
                return Some(op.id.clone());
            }
            let parent = self.input.ctx.parent(i);
            if let Some(parent) = parent {
                let p = self.input.ctx.op(parent);
                if !self.regions.contains(&p.id)
                    && !CONTAINERS.contains(&p.native_kind.as_str())
                    && p.native_kind != "else_clause"
                {
                    let allowed = matches!(
                        p.native_kind.as_str(),
                        "block" | "statement_block" | "compound_statement"
                    ) && self.input.ctx.parent(parent).is_some_and(|e| {
                        self.input.ctx.op(e).native_kind == "else_clause"
                            && self.regions.contains(&self.input.ctx.op(e).id)
                    });
                    if !allowed {
                        return None;
                    }
                }
            }
            current = parent;
        }
        None
    }
    fn call_region(&self, mut i: usize) -> Option<String> {
        let mut seen = BTreeSet::new();
        while !self.regions.contains(&self.input.ctx.op(i).id) {
            if !seen.insert(i) {
                return None;
            }
            let parent = self.input.ctx.parent(i)?;
            let p = self.input.ctx.op(parent);
            if self.regions.contains(&p.id) {
                return Some(p.id.clone());
            }
            if !self.input.targets.contains_key(&p.id)
                && !self.input.returns.contains_key(&p.id)
                && p.kind != "CALL"
                && !CONTAINERS.contains(&p.native_kind.as_str())
                && !matches!(
                    p.native_kind.as_str(),
                    "argument_list"
                        | "arguments"
                        | "argument"
                        | "parenthesized_expression"
                        | "expression_list"
                )
            {
                return None;
            }
            i = parent;
        }
        Some(self.input.ctx.op(i).id.clone())
    }
    pub(super) fn prepare_events(&mut self) -> Result<()> {
        let input = self.input;
        if !self.member_writes.is_empty() {
            let names = self
                .locals
                .iter()
                .map(|binding| Ok((input.ctx.entity(binding)?.name.clone(), binding.clone())))
                .collect::<Result<BTreeMap<_, _>>>()?;
            for &i in &self.ops {
                let op = input.ctx.op(i);
                let text = attributes::text(&op.attrs, "text", "")?;
                let Some(binding) = names.get(&text) else {
                    continue;
                };
                if !matches!(op.native_kind.as_str(), "identifier" | "variable_name") {
                    continue;
                }
                if let Some(parent) = input.ctx.parent(i) {
                    let p = input.ctx.op(parent);
                    if (p.kind == "FUNCTION" && op.role == "name")
                        || (p.kind == "MEMBER"
                            && matches!(
                                op.role.as_str(),
                                "attribute" | "property" | "field" | "name"
                            ))
                    {
                        continue;
                    }
                }
                let mut current = i;
                let mut allowed = false;
                for _ in 0..32 {
                    let Some(parent) = input.ctx.parent(current) else {
                        break;
                    };
                    let p = input.ctx.op(parent);
                    if let Some(target) = input.targets.get(&p.id) {
                        allowed = (target == binding
                            && matches!(input.ctx.op(current).role.as_str(), "left" | "name"))
                            || (input.values.get(&p.id) == Some(binding)
                                && self.locals.contains(target))
                            || (self.member_writes.contains_key(&p.id)
                                && input.ctx.op(current).role == "left"
                                && input.members.get(target) == Some(binding));
                        break;
                    }
                    if let Some(returned) = input.returns.get(&p.id) {
                        allowed = returned == binding;
                        break;
                    }
                    current = parent;
                }
                if !allowed {
                    self.escaped.insert(binding.clone());
                }
            }
            let mut todo = self.escaped.iter().cloned().collect::<Vec<_>>();
            while let Some(current) = todo.pop() {
                for source in input.assigned.get(&current).into_iter().flatten() {
                    if self.escaped.insert(source.clone()) {
                        todo.push(source.clone());
                    }
                }
            }
        }
        for kind in 0..4 {
            for &i in &self.ops {
                let op = input.ctx.op(i);
                let included = match kind {
                    0 => input.targets.contains_key(&op.id),
                    1 => op.kind == "RETURN",
                    2 => op.kind == "THROW",
                    _ => self.arms.contains_key(&op.id),
                };
                if included && let Some(region) = self.region(i) {
                    self.events.entry(region).or_default().push(i);
                }
            }
        }
        for &i in &self.ops {
            let op = input.ctx.op(i);
            if (input.arguments.contains_key(&op.id) || input.receiver_reads.contains_key(&op.id))
                && let Some(region) = self.call_region(i)
            {
                self.events.entry(region).or_default().push(i);
            }
        }
        for sequence in self.events.values_mut() {
            sequence.sort_by_key(|&i| {
                let op = input.ctx.op(i);
                (
                    if self.arms.contains_key(&op.id) {
                        op.start
                    } else {
                        op.end
                    },
                    usize::from(op.kind != "CALL"),
                    -i128::from(op.start),
                )
            });
        }
        Ok(())
    }
}
