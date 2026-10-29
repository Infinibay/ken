//! Linear input-to-field/member summaries with explicit escape/control exclusions.
use super::*;
const CONTAINERS: &[&str] = &[
    "expression_statement",
    "lexical_declaration",
    "variable_declaration",
    "local_variable_declaration",
    "local_declaration_statement",
    "declaration",
];
fn bodies(g: &Graph, ops: &[Operation]) -> BTreeSet<String> {
    ops.iter()
        .filter(|o| {
            o.role == "body"
                && o.parent
                    .as_deref()
                    .and_then(|p| g.op(p))
                    .is_some_and(|p| p.kind == "FUNCTION")
        })
        .map(|o| o.id.clone())
        .collect()
}
fn body_parent<'a>(g: &'a Graph, o: &Operation, containers: &[&str]) -> Option<&'a Operation> {
    let mut current = o.parent.as_deref().and_then(|id| g.op(id));
    let mut seen = BTreeSet::new();
    while let Some(op) = current {
        if !containers.contains(&op.native_kind.as_str()) {
            return Some(op);
        }
        if !seen.insert(op.id.as_str()) {
            return None;
        }
        current = op.parent.as_deref().and_then(|p| g.op(p));
    }
    None
}
fn indirect(ops: &[Operation]) -> Result<bool> {
    for o in ops {
        if matches!(
            o.kind.as_str(),
            "LOOP"
                | "BRANCH"
                | "TRY"
                | "THROW"
                | "YIELD"
                | "AWAIT"
                | "RESOURCE_SCOPE"
                | "MATCH"
                | "UPDATE"
        ) || matches!(
            o.native_kind.as_str(),
            "global_statement" | "nonlocal_statement" | "delete_statement" | "named_expression"
        ) || tokens(o)?.iter().any(|t| {
            matches!(
                t.as_str(),
                "ref"
                    | "out"
                    | "++"
                    | "--"
                    | "+="
                    | "-="
                    | "*="
                    | "/="
                    | "%="
                    | "??="
                    | "&&="
                    | "||="
            )
        }) {
            return Ok(true);
        }
    }
    Ok(false)
}
pub(super) fn fields(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let by_owner = g.owners();
    let owners = g.reverse("HAS_METHOD");
    let mut fields = SetMap::new();
    for f in g.rows("HAS_FIELD") {
        if !b(&g.e(&f.object)?.attrs, "static")? {
            fields.entry(f.subject).or_default().insert(f.object);
        }
    }
    let params = g.params()?;
    let mut receiver_names = SetMap::new();
    for f in g.rows("HAS_PARAMETER") {
        if b(&f.attrs, "receiver")? {
            receiver_names
                .entry(f.subject)
                .or_default()
                .insert(g.e(&f.object)?.name.clone());
        }
    }
    let parameter_owners = params
        .iter()
        .flat_map(|(o, ps)| ps.iter().map(move |p| (p.clone(), o.clone())))
        .collect::<BTreeMap<_, _>>();
    let mut implicit = BTreeMap::<String, BTreeMap<String, String>>::new();
    for f in g.rows("PARAMETER_INITIALIZES_FIELD") {
        if let Some(owner) = parameter_owners.get(&f.subject) {
            implicit
                .entry(owner.clone())
                .or_default()
                .insert(f.object, f.subject);
        }
    }
    let mut initializer_owners = BTreeMap::new();
    for f in g.rows("HAS_INITIALIZER") {
        if s(&f.attrs, "basis")? == "cpp-constructor-syntax" {
            initializer_owners.insert(f.object, f.subject);
        }
    }
    let initialized_fields = g.map("INITIALIZES_FIELD");
    let unsupported = g
        .rows("CONSTRUCTOR_INITIALIZER_STATUS")
        .into_iter()
        .filter(|f| f.object == "unsupported")
        .filter_map(|f| initializer_owners.get(&f.subject).cloned())
        .collect::<BTreeSet<_>>();
    for f in g.rows("CONSTRUCTOR_INITIALIZER_INPUT") {
        if let (Some(owner), Some(slot)) = (
            initializer_owners.get(&f.subject),
            initialized_fields.get(&f.subject),
        ) && parameter_owners.get(&f.object) == Some(owner)
        {
            implicit
                .entry(owner.clone())
                .or_default()
                .insert(slot.clone(), f.object);
        }
    }
    let targets = g.map("ASSIGNMENT_TARGET");
    let values = g.map("ASSIGNMENT_VALUE");
    let returns = g.map("RETURN_OPERAND");
    let call_owners = g.reverse("HAS_CALL");
    let calls = g.groups("HAS_CALL");
    let receivers = g.groups("RECEIVER");
    let mut escaped = BTreeSet::new();
    for relation in ["ARGUMENT", "RECEIVER"] {
        for f in g.rows(relation) {
            if f.object.ends_with("/THIS")
                && let Some(owner) = call_owners.get(&f.subject)
            {
                escaped.insert(owner.clone());
            }
        }
    }
    let nested = g.nested()?;
    let dynamic = g.dynamic()?;
    for (owner, cls) in owners {
        let entity = g.e(&owner)?.clone();
        let ops = by_owner.get(&owner).cloned().unwrap_or_default();
        if ![COMMON, &["cpp"]]
            .concat()
            .contains(&s(&entity.attrs, "language")?.as_str())
        {
            continue;
        }
        if implicit.get(&owner).is_none_or(BTreeMap::is_empty)
            && !ops
                .iter()
                .any(|o| targets.contains_key(&o.id) || returns.contains_key(&o.id))
        {
            continue;
        }
        let bodies = bodies(g, &ops);
        for op in &ops {
            let named = matches!(
                op.native_kind.as_str(),
                "identifier" | "this" | "self" | "this_expression"
            ) && (s(&op.attrs, "text")? == "this"
                || set(&receiver_names, &owner).contains(&s(&op.attrs, "text")?));
            let embedded = tokens(op)?.iter().any(|t| t == "this") && op.kind != "MEMBER";
            if !named && !embedded {
                continue;
            }
            let immediate = op.parent.as_deref().and_then(|p| g.op(p));
            if s(&entity.attrs, "language")? == "java"
                && b(&entity.attrs, "constructor")?
                && named
                && op.role == "constructor"
                && let Some(i) = immediate
                && i.native_kind == "explicit_constructor_invocation"
                && i.parent.as_ref().is_some_and(|p| bodies.contains(p))
            {
                let siblings = ops
                    .iter()
                    .filter(|o| o.parent == i.parent)
                    .collect::<Vec<_>>();
                let arguments = ops
                    .iter()
                    .filter(|o| o.parent.as_deref() == Some(i.id.as_str()) && o.role == "arguments")
                    .collect::<Vec<_>>();
                if siblings
                    .iter()
                    .min_by_key(|o| o.start)
                    .is_some_and(|o| o.id == i.id)
                    && arguments.len() == 1
                    && s(&arguments[0].attrs, "text")? == "()"
                {
                    continue;
                }
            }
            if named && immediate.is_some_and(|o| o.kind == "MEMBER") {
                continue;
            }
            let mut current = immediate;
            for _ in 0..32 {
                let Some(o) = current else {
                    break;
                };
                if bodies.contains(&o.id) {
                    escaped.insert(owner.clone());
                    break;
                }
                current = o.parent.as_deref().and_then(|p| g.op(p));
            }
        }
        let mut reason = if bodies.len() != 1
            || escaped.contains(&owner)
            || nested.contains(&owner)
            || dynamic.contains(&owner)
        {
            "body-or-escape"
        } else if unsupported.contains(&owner) {
            "unsupported-constructor-initializer"
        } else if indirect(&ops)? {
            "control-or-indirect-write"
        } else {
            ""
        };
        let writes = ops
            .iter()
            .filter(|o| targets.contains_key(&o.id))
            .cloned()
            .collect::<Vec<_>>();
        let exits = ops
            .iter()
            .filter(|o| o.kind == "RETURN")
            .cloned()
            .collect::<Vec<_>>();
        for op in writes.iter().chain(&exits) {
            if body_parent(g, op, CONTAINERS).is_none_or(|p| !bodies.contains(&p.id))
                && reason.is_empty()
            {
                reason = "nested-event";
            }
        }
        if reason.is_empty()
            && ops
                .iter()
                .any(|o| o.kind == "ASSIGN" && !targets.contains_key(&o.id))
        {
            reason = "unmodeled-write";
        }
        g.add(
            &owner,
            "FIELD_FLOW_STATUS",
            if reason.is_empty() {
                "supported"
            } else {
                "unsupported"
            },
            "",
            json!({"analysis":"linear-fields/1","reason":reason}),
        );
        if !reason.is_empty() {
            continue;
        }
        let mutated = writes
            .iter()
            .map(|o| targets[&o.id].clone())
            .collect::<BTreeSet<_>>();
        let parameters = set(&params, &owner);
        let slots = set(&fields, &cls);
        for f in calls.get(&owner).into_iter().flatten() {
            for rec in receivers.get(&f.object).into_iter().flatten() {
                if parameters.contains(&rec.object) && !mutated.contains(&rec.object) {
                    g.add(
                        &f.object,
                        "CALL_RECEIVER_INPUT",
                        &rec.object,
                        ev(rec),
                        json!({"basis":"linear-syntax","analysis":"linear-fields/1"}),
                    );
                }
            }
        }
        let mut events = writes.into_iter().chain(exits).collect::<Vec<_>>();
        events.sort_by_key(|o| o.start);
        let mut last = BTreeMap::new();
        for op in events {
            if op.kind == "RETURN" {
                if let Some(field) = returns.get(&op.id)
                    && slots.contains(field)
                    && !mutated.contains(field)
                {
                    g.add(
                        &owner,
                        "RETURNS_FIELD",
                        field,
                        &format!("{}:{}", entity.path, op.line),
                        json!({"basis":"linear-syntax","return_operation":op.id}),
                    );
                }
                break;
            }
            last.insert(targets[&op.id].clone(), op);
        }
        let mut final_inputs = implicit.get(&owner).cloned().unwrap_or_default();
        for (field, write) in last {
            let value = values
                .get(&write.id)
                .ok_or(ProgramError::Invalid("field assignment value is missing"))?;
            final_inputs.insert(field.clone(), value.clone());
            if slots.contains(&field) {
                let ev = format!("{}:{}", entity.path, write.line);
                g.add(
                    &write.id,
                    "FINAL_FIELD_VALUE",
                    value,
                    &ev,
                    json!({"basis":"linear-syntax","analysis":"linear-fields/1"}),
                );
                if parameters.contains(value) && !mutated.contains(value) {
                    g.add(
                        &write.id,
                        "FINAL_FIELD_INPUT",
                        value,
                        &ev,
                        json!({"basis":"linear-syntax","analysis":"linear-fields/1"}),
                    );
                }
            }
        }
        if b(&entity.attrs, "constructor")? {
            for (field, value) in final_inputs {
                if slots.contains(&field)
                    && parameters.contains(&value)
                    && !mutated.contains(&value)
                {
                    g.add(
                        &field,
                        "CONSTRUCTOR_FIELD_INPUT",
                        &value,
                        &format!("{}:{}", entity.path, entity.line),
                        json!({"basis":"linear-syntax","analysis":"linear-fields/1"}),
                    );
                }
            }
        }
    }
    Ok(())
}
pub(super) fn members(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let targets = g.map("ASSIGNMENT_TARGET");
    let values = g.map("ASSIGNMENT_VALUE");
    let mut members = g
        .rows("MEMBER_OF")
        .into_iter()
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    for f in g.rows("HAS_FIELD") {
        if !b(&g.e(&f.object)?.attrs, "static")? {
            members.insert(f.object);
        }
    }
    let mut bindings = members.clone();
    bindings.extend(
        g.ir.entities
            .iter()
            .filter(|(_, e)| matches!(e.kind.as_str(), "STORAGE" | "PARAMETER"))
            .map(|(id, _)| id.clone()),
    );
    let params = g.params()?;
    let nested = g.nested()?;
    let mut dynamic = BTreeSet::new();
    for f in g.rows("CALLEE_NAME") {
        if DYNAMIC.contains(&f.object.as_str()) {
            dynamic.insert(s(&g.e(&f.subject)?.attrs, "owner")?);
        }
    }
    for (owner, ops) in g.owners() {
        let e = g.e(&owner)?.clone();
        if e.kind != "CALLABLE"
            || ![COMMON, &["rust", "cpp", "go", "ruby"]]
                .concat()
                .contains(&s(&e.attrs, "language")?.as_str())
            || !ops.iter().any(|o| targets.contains_key(&o.id))
        {
            continue;
        }
        let member_writes = ops
            .iter()
            .any(|o| targets.get(&o.id).is_some_and(|t| members.contains(t)));
        let bodies = bodies(g, &ops);
        let mut reason = if bodies.len() != 1 || nested.contains(&owner) || dynamic.contains(&owner)
        {
            "body-or-dynamic-scope"
        } else {
            ""
        };
        if reason.is_empty() && indirect(&ops)? {
            reason = "control-or-indirect-write";
        }
        let writes = ops
            .iter()
            .filter(|o| targets.contains_key(&o.id))
            .cloned()
            .collect::<Vec<_>>();
        let exits = ops
            .iter()
            .filter(|o| o.kind == "RETURN")
            .cloned()
            .collect::<Vec<_>>();
        let containers = [CONTAINERS, &["statement_list"]].concat();
        for op in writes.iter().chain(&exits) {
            if reason.is_empty()
                && body_parent(g, op, &containers).is_none_or(|p| !bodies.contains(&p.id))
            {
                reason = "nested-event";
            }
        }
        if reason.is_empty() {
            for o in &ops {
                if o.kind == "ASSIGN"
                    && (!targets.contains_key(&o.id)
                        || !tokens(o)?.iter().any(|t| t == "=")
                        || (!members.contains(lookup(&targets, &o.id))
                            && !g.get(lookup(&targets, &o.id)).is_some_and(|e| {
                                matches!(e.kind.as_str(), "STORAGE" | "PARAMETER")
                            })))
                {
                    reason = "unmodeled-write";
                    break;
                }
            }
        }
        g.add(
            &owner,
            "BINDING_FLOW_STATUS",
            if reason.is_empty() {
                "supported"
            } else {
                "unsupported"
            },
            "",
            json!({"analysis":"linear-bindings/1","reason":reason}),
        );
        if member_writes {
            g.add(
                &owner,
                "MEMBER_FLOW_STATUS",
                if reason.is_empty() {
                    "supported"
                } else {
                    "unsupported"
                },
                "",
                json!({"analysis":"linear-members/1","reason":reason}),
            );
        }
        if !reason.is_empty() {
            continue;
        }
        let mutated = writes
            .iter()
            .map(|o| targets[&o.id].clone())
            .collect::<BTreeSet<_>>();
        let mut events = writes.into_iter().chain(exits).collect::<Vec<_>>();
        events.sort_by_key(|o| o.start);
        let mut last = BTreeMap::new();
        for o in events {
            if o.kind == "RETURN" {
                break;
            }
            last.insert(targets[&o.id].clone(), o);
        }
        let params = set(&params, &owner);
        for (target, write) in last {
            let Some(value) = values.get(&write.id) else {
                continue;
            };
            let ev = format!("{}:{}", e.path, write.line);
            if params.contains(value) && !mutated.contains(value) {
                if bindings.contains(&target) {
                    g.add(
                        &write.id,
                        "FINAL_BINDING_INPUT",
                        value,
                        &ev,
                        json!({"basis":"linear-syntax","analysis":"linear-bindings/1"}),
                    );
                }
                if members.contains(&target) {
                    g.add(
                        &write.id,
                        "FINAL_MEMBER_INPUT",
                        value,
                        &ev,
                        json!({"basis":"linear-syntax","analysis":"linear-members/1"}),
                    );
                }
            }
        }
    }
    Ok(())
}
