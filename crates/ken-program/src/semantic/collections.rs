//! Collection copies and lexical reset order, without runtime identity claims.
use super::*;
pub(super) fn snapshots(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let syntax = g.map("SYNTAX_NODE");
    let args = g.groups("ARGUMENT");
    let receivers = g.map("RECEIVER");
    let callees = g.map("CALLEE_VALUE");
    let writes = g.rows("ASSIGNMENT_TARGET").into_iter().fold(
        BTreeMap::<String, Vec<String>>::new(),
        |mut m, f| {
            m.entry(f.object).or_default().push(f.subject);
            m
        },
    );
    let rhs = g.map("ASSIGNMENT_VALUE");
    let declared = g
        .rows("DECLARES")
        .into_iter()
        .map(|f| (f.subject, f.object))
        .collect::<BTreeSet<_>>();
    let written = g
        .rows("WRITES")
        .into_iter()
        .map(|f| f.object)
        .collect::<BTreeSet<_>>();
    let mut unsafe_owners = BTreeSet::new();
    for op in &g.ir.operations {
        if op.kind == "UPDATE"
            || tokens(op)?
                .iter()
                .any(|t| matches!(t.as_str(), "ref" | "out"))
            || matches!(
                op.native_kind.as_str(),
                "delete_statement"
                    | "global_statement"
                    | "nonlocal_statement"
                    | "named_expression"
                    | "augmented_assignment"
                    | "augmented_assignment_expression"
            )
        {
            unsafe_owners.insert(op.owner.clone());
        }
    }
    for f in g.rows("CALLEE_NAME") {
        if matches!(f.object.as_str(), "eval" | "exec" | "locals" | "globals") {
            unsafe_owners.insert(s(&g.e(&f.subject)?.attrs, "owner")?);
        }
    }
    let mut unsafe_values = receivers
        .values()
        .cloned()
        .chain(g.rows("ARGUMENT").into_iter().map(|f| f.object))
        .chain(g.rows("WRITES_ELEMENT").into_iter().map(|f| f.object))
        .collect::<BTreeSet<_>>();
    let mut aliases = SetMap::new();
    for (target, defs) in &writes {
        for def in defs {
            let value = lookup(&rhs, def);
            if g.get(value)
                .is_some_and(|e| matches!(e.kind.as_str(), "STORAGE" | "PARAMETER"))
            {
                aliases
                    .entry(target.clone())
                    .or_default()
                    .insert(value.into());
                aliases
                    .entry(value.into())
                    .or_default()
                    .insert(target.clone());
            }
        }
    }
    let mut pending = unsafe_values.iter().cloned().collect::<VecDeque<_>>();
    while let Some(value) = pending.pop_front() {
        for alias in set(&aliases, &value) {
            if unsafe_values.insert(alias.clone()) {
                pending.push_back(alias);
            }
        }
    }
    let mut shadowed = BTreeSet::new();
    for (_, e) in &g.ir.entities {
        if matches!(e.name.as_str(), "Array" | "list" | "tuple")
            && (matches!(
                e.kind.as_str(),
                "CLASS" | "INTERFACE" | "PARAMETER" | "CALLABLE"
            ) || b(&e.attrs, "declared")?)
        {
            shadowed.insert((e.path.clone(), e.name.clone()));
        }
    }
    for f in g.rows("IMPORT_SYNTAX") {
        for name in ["Array", "list", "tuple"] {
            if ken_text::unicode::contains_word(&f.object, name) || f.object.contains('*') {
                shadowed.insert((
                    f.subject
                        .strip_suffix("::module")
                        .unwrap_or(&f.subject)
                        .into(),
                    name.into(),
                ));
            }
        }
    }
    for f in g.rows("MEMBER_OF") {
        if writes.contains_key(&f.subject)
            && g.get(&f.subject).is_some()
            && let Some(base) = g.get(&f.object)
            && base.name == "Array"
        {
            shadowed.insert((base.path.clone(), "Array".into()));
        }
    }
    let mut params = BTreeSet::new();
    for f in g.rows("HAS_PARAMETER") {
        if !b(&f.attrs, "receiver")? {
            params.insert((f.subject, f.object));
        }
    }
    for f in g.rows("INSERTED_VALUE") {
        let owner = s(&g.e(&f.subject)?.attrs, "owner")?;
        if params.contains(&(owner.clone(), f.object.clone()))
            && !written.contains(&f.object)
            && !unsafe_owners.contains(&owner)
        {
            g.add(
                &f.subject,
                "INSERTED_INPUT",
                &f.object,
                ev(&f),
                json!({"basis":"syntax-unwritten-binding"}),
            );
        }
    }
    let calls =
        g.ir.entities
            .iter()
            .filter(|(_, e)| e.kind == "CALL")
            .map(|(id, _)| id.clone())
            .collect::<BTreeSet<_>>();
    let mut snapshots = BTreeSet::new();
    for call in &calls {
        let actual = args.get(call).cloned().unwrap_or_default();
        if actual.len() != 1 || s(&actual[0].attrs, "kind")? != "positional" {
            continue;
        }
        let e = g.e(call)?.clone();
        let language = s(&e.attrs, "language")?;
        let name = s(&e.attrs, "name")?;
        let mut model = String::new();
        if language == "python"
            && matches!(name.as_str(), "list" | "tuple")
            && !receivers.contains_key(call)
        {
            if !callees.contains_key(call) && !shadowed.contains(&(e.path.clone(), name.clone())) {
                model = format!("python.{name}");
            }
        } else if matches!(language.as_str(), "javascript" | "typescript")
            && name == "from"
            && let Some(receiver) = g.get(lookup(&receivers, call))
            && receiver.name == "Array"
            && receiver.kind == "STORAGE"
            && s(&receiver.attrs, "native_kind")? == "identifier"
            && !shadowed.contains(&(e.path.clone(), "Array".into()))
        {
            model = "javascript.Array.from".into();
        }
        if !model.is_empty() {
            g.add(
                call,
                "COLLECTION_SNAPSHOT_OF",
                &actual[0].object,
                &g.evidence(call)?,
                json!({"model":model,"basis":"api-model"}),
            );
            snapshots.insert(call.clone());
        }
    }
    let mut bindings = BTreeMap::<String, Vec<String>>::new();
    let mut binding_loops = SetMap::new();
    for f in g.rows("ITERATION_BINDING") {
        binding_loops
            .entry(f.object.clone())
            .or_default()
            .insert(f.subject.clone());
        if s(&f.attrs, "role")? == "value" {
            bindings.entry(f.subject).or_default().push(f.object);
        }
    }
    let loops = g.map("ENCLOSING_LOOP");
    let mut calls_in_loop = BTreeMap::<String, Vec<String>>::new();
    for (call, node) in syntax {
        if let Some(loop_) = loops.get(&node) {
            calls_in_loop.entry(loop_.clone()).or_default().push(call);
        }
    }
    for f in g.rows("ITERATION_SOURCE") {
        let Some(loop_) = g.op(&f.subject).cloned() else {
            continue;
        };
        let mut value = f.object.clone();
        let mut use_ = loop_.clone();
        let mut seen = BTreeSet::new();
        let mut producer = None;
        if !unsafe_owners.contains(&use_.owner) {
            for _ in 0..32 {
                if calls.contains(&value) {
                    producer = Some(value);
                    break;
                }
                if !seen.insert(value.clone())
                    || unsafe_values.contains(&value)
                    || binding_loops.contains_key(&value)
                    || !declared.contains(&(use_.owner.clone(), value.clone()))
                {
                    break;
                }
                let defs = writes.get(&value).cloned().unwrap_or_default();
                if defs.len() != 1 {
                    break;
                }
                let Some(write) = g.op(&defs[0]).cloned() else {
                    break;
                };
                if write.owner != use_.owner
                    || !super::members::precedes(
                        g,
                        &write,
                        &use_,
                        &[
                            "expression_statement",
                            "lexical_declaration",
                            "variable_declaration",
                            "local_variable_declaration",
                            "local_declaration_statement",
                        ],
                    )
                    || !rhs.contains_key(&write.id)
                    || tokens(&write)?.iter().any(|t| t.ends_with('=') && t != "=")
                {
                    break;
                }
                value = rhs[&write.id].clone();
                use_ = write;
            }
        }
        if let Some(producer) = producer {
            g.add(
                &loop_.id,
                "ITERATION_ORIGIN",
                &producer,
                ev(&f),
                json!({"basis":"unique-local-write"}),
            );
            if snapshots.contains(&producer) {
                g.add(
                    &loop_.id,
                    "ITERATION_SNAPSHOT",
                    &producer,
                    ev(&f),
                    json!({"basis":"unique-local-write","model":"collection-snapshot/1"}),
                );
            }
        }
        for binding in bindings.get(&loop_.id).into_iter().flatten() {
            if written.contains(binding)
                || unsafe_owners.contains(&loop_.owner)
                || set(&binding_loops, binding).len() != 1
            {
                continue;
            }
            for call in calls_in_loop.get(&loop_.id).into_iter().flatten() {
                if s(&g.e(call)?.attrs, "owner")? != loop_.owner {
                    continue;
                }
                for arg in args.get(call).into_iter().flatten() {
                    if &arg.object == binding && s(&arg.attrs, "kind")? == "positional" {
                        g.add(&loop_.id,"ITERATION_PASSES_VALUE",call,&g.evidence(call)?,json!({"position":v(&arg.attrs,"position")?,"basis":"syntax-unwritten-binding"}));
                    }
                }
                let invoked = receivers.get(call).or_else(|| callees.get(call));
                if invoked == Some(binding) {
                    g.add(
                        &loop_.id,
                        "ITERATION_INVOKES_VALUE",
                        call,
                        &g.evidence(call)?,
                        json!({"basis":"syntax"}),
                    );
                }
            }
        }
    }
    Ok(())
}
fn statement(g: &Graph, node: &str) -> Option<Operation> {
    let mut op = g.op(node)?;
    for _ in 0..32 {
        let parent = op.parent.as_deref().and_then(|p| g.op(p))?;
        if parent.owner != op.owner {
            return None;
        }
        if matches!(
            parent.native_kind.as_str(),
            "block" | "statement_block" | "compound_statement"
        ) {
            return Some(op.clone());
        }
        if !matches!(
            parent.native_kind.as_str(),
            "expression_statement" | "parenthesized_expression"
        ) {
            return None;
        }
        op = parent;
    }
    None
}
pub(super) fn lifecycle(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let syntax = g.map("SYNTAX_NODE");
    let receivers = g.map("RECEIVER");
    let targets = g.map("ASSIGNMENT_TARGET");
    let empty = g
        .rows("EMPTY_COLLECTION")
        .into_iter()
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    let arguments = g
        .rows("ARGUMENT")
        .into_iter()
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    let mut resets = BTreeMap::new();
    for f in g.rows("ASSIGNMENT_VALUE") {
        if empty.contains(&f.object)
            && targets.contains_key(&f.subject)
            && let Some(op) = g.op(&f.subject)
            && tokens(op)?.iter().any(|t| t == "=")
        {
            resets.insert(f.subject.clone(), targets[&f.subject].clone());
            g.add(
                &f.subject,
                "CLEARS_COLLECTION",
                &targets[&f.subject],
                ev(&f),
                json!({"basis":"empty-literal-replacement"}),
            );
        }
    }
    for f in g.rows("CALLEE_NAME") {
        let language = s(&g.e(&f.subject)?.attrs, "language")?;
        if matches!(language.as_str(), "python" | "java" | "csharp")
            && f.object
                == if language == "csharp" {
                    "Clear"
                } else {
                    "clear"
                }
            && !arguments.contains(&f.subject)
            && let Some(receiver) = receivers.get(&f.subject)
        {
            resets.insert(f.subject.clone(), receiver.clone());
            g.add(
                &f.subject,
                "CLEARS_COLLECTION",
                receiver,
                ev(&f),
                json!({"basis":"collection-api-shape"}),
            );
        }
    }
    let mut siblings = BTreeMap::<String, Vec<Operation>>::new();
    for op in &g.ir.operations {
        if let Some(parent) = op.parent.as_deref().and_then(|p| g.op(p))
            && parent.owner == op.owner
            && matches!(
                parent.native_kind.as_str(),
                "block" | "statement_block" | "compound_statement"
            )
        {
            siblings
                .entry(parent.id.clone())
                .or_default()
                .push(op.clone());
        }
    }
    let mut positions = BTreeMap::new();
    let mut barriers = BTreeMap::<String, Vec<usize>>::new();
    for (block, mut items) in siblings {
        items.sort_by_key(|o| o.start);
        for (pos, op) in items.into_iter().enumerate() {
            positions.insert(op.id.clone(), pos);
            if matches!(op.kind.as_str(), "RETURN" | "THROW")
                || matches!(
                    op.native_kind.as_str(),
                    "break_statement" | "continue_statement"
                )
            {
                barriers.entry(block.clone()).or_default().push(pos);
            }
        }
    }
    let mut iterations = BTreeMap::<String, Vec<Operation>>::new();
    for f in g.rows("ITERATION_SOURCE") {
        if let Some(stmt) = statement(g, &f.subject)
            && stmt.id == f.subject
            && let Some(parent) = stmt.parent.clone()
        {
            iterations.entry(parent).or_default().push(stmt);
        }
    }
    for event in resets.keys() {
        let Some(stmt) = statement(g, syntax.get(event).map_or(event.as_str(), String::as_str))
        else {
            continue;
        };
        let Some(parent) = &stmt.parent else {
            continue;
        };
        let Some(&pos) = positions.get(&stmt.id) else {
            continue;
        };
        let stops = barriers.get(parent).cloned().unwrap_or_default();
        let stop = stops.partition_point(|&p| p < pos);
        let lower = if stop == 0 {
            -1
        } else {
            stops[stop - 1] as i64
        };
        for loop_ in iterations.get(parent).into_iter().flatten() {
            let p = positions[&loop_.id];
            if lower < (p as i64) && p < pos {
                let evidence = format!("{}:{}", g.e(&stmt.owner)?.path, stmt.line);
                g.add(
                    event,
                    "AFTER_ITERATION",
                    &loop_.id,
                    &evidence,
                    json!({"basis":"same-block-order","analysis":"collection-reset/1"}),
                );
            }
        }
    }
    Ok(())
}
