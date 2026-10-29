//! Nominal roots, visible instance slots, access paths and structural contracts.
use super::*;
pub(super) fn roots(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let mut types = BTreeSet::new();
    for id in g.ids() {
        let e = g.e(&id)?;
        if matches!(e.kind.as_str(), "CLASS" | "INTERFACE")
            && [COMMON, &["cpp"]]
                .concat()
                .contains(&s(&e.attrs, "language")?.as_str())
        {
            types.insert(id);
        }
    }
    let bases = g.sets("SUBTYPE_OF");
    let names = g.sets("BASE_NAME");
    let mut memo = BTreeMap::new();
    fn roots(
        unit: &str,
        trail: &BTreeSet<String>,
        types: &BTreeSet<String>,
        bases: &SetMap,
        names: &SetMap,
        memo: &mut BTreeMap<(String, usize), (BTreeSet<String>, String)>,
    ) -> (BTreeSet<String>, String) {
        if trail.contains(unit) {
            return (Default::default(), "cycle".into());
        }
        let key = (unit.into(), 32 - trail.len());
        if let Some(v) = memo.get(&key) {
            return v.clone();
        }
        let reason = if trail.len() >= 32 {
            "depth-bound"
        } else if !types.contains(unit) {
            "unsupported-type"
        } else if set(names, unit).len() != set(bases, unit).len() {
            "unresolved-bases"
        } else {
            ""
        };
        let mut out = (BTreeSet::new(), reason.into());
        if reason.is_empty() {
            let parents = set(bases, unit);
            if parents.is_empty() {
                out.0.insert(unit.into());
            } else {
                let mut path = trail.clone();
                path.insert(unit.into());
                for base in parents {
                    let (found, reason) = roots(&base, &path, types, bases, names, memo);
                    if !reason.is_empty() {
                        out = (Default::default(), reason);
                        break;
                    }
                    out.0.extend(found);
                    if out.0.len() > 1 {
                        out = (Default::default(), "multiple-roots".into());
                        break;
                    }
                }
            }
        }
        memo.insert(key, out.clone());
        out
    }
    for id in &types {
        let (found, reason) = roots(id, &BTreeSet::new(), &types, &bases, &names, &mut memo);
        g.add(
            id,
            "NOMINAL_ROOT_STATUS",
            if reason.is_empty() {
                "supported"
            } else {
                "unsupported"
            },
            "",
            json!({"analysis":"explicit-nominal-roots/1","reason":reason}),
        );
        if reason.is_empty() && found.len() == 1 {
            g.add(
                id,
                "NOMINAL_ROOT",
                found.first().unwrap(),
                &g.evidence(id)?,
                json!({"basis":"explicit-resolved-bases","analysis":"explicit-nominal-roots/1"}),
            );
        }
    }
    Ok(())
}
/// A write in a lexical sequence dominates a later containing use subtree.
pub(super) fn precedes(g: &Graph, write: &Operation, use_: &Operation, wrappers: &[&str]) -> bool {
    let mut current = write;
    let mut block = None;
    for _ in 0..64 {
        let Some(parent) = current.parent.as_deref().and_then(|id| g.op(id)) else {
            return false;
        };
        if parent.owner != write.owner {
            return false;
        }
        if matches!(parent.native_kind.as_str(), "block" | "statement_block") {
            block = Some(parent.id.as_str());
            break;
        }
        if !wrappers.contains(&parent.native_kind.as_str()) {
            return false;
        }
        current = parent;
    }
    let Some(block) = block else {
        return false;
    };
    current = use_;
    for _ in 0..64 {
        if current.parent.as_deref() == Some(block) {
            return write.end <= current.start;
        }
        let Some(parent) = current.parent.as_deref().and_then(|id| g.op(id)) else {
            return false;
        };
        if parent.owner != write.owner {
            return false;
        }
        current = parent;
    }
    false
}
pub(super) fn access(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let bases = g.sets("SUBTYPE_OF");
    let spellings = g.sets("BASE_NAME");
    let mut fields = BTreeMap::<String, BTreeMap<String, String>>::new();
    let mut methods = BTreeMap::<String, BTreeMap<String, Vec<String>>>::new();
    for f in g.rows("HAS_FIELD") {
        fields
            .entry(f.subject)
            .or_default()
            .insert(g.e(&f.object)?.name.clone(), f.object);
    }
    for f in g.rows("HAS_METHOD") {
        methods
            .entry(f.subject)
            .or_default()
            .entry(g.e(&f.object)?.name.clone())
            .or_default()
            .push(f.object);
    }
    for id in g.ids() {
        let unit = g.e(&id)?.clone();
        if unit.kind != "CLASS"
            || !matches!(
                s(&unit.attrs, "language")?.as_str(),
                "python" | "javascript" | "typescript"
            )
        {
            continue;
        }
        let mut chain = vec![];
        let mut cls = id.clone();
        while !chain.contains(&cls) && chain.len() < 32 {
            chain.push(cls.clone());
            let bs = set(&bases, &cls);
            if bs.len() > 1 || set(&spellings, &cls).len() != bs.len() {
                chain.clear();
                break;
            }
            if bs.is_empty() {
                break;
            }
            cls = bs.into_iter().next().unwrap();
            if chain.contains(&cls) || chain.len() >= 32 {
                chain.clear();
                break;
            }
        }
        if chain.is_empty() {
            continue;
        }
        let mut visible = BTreeMap::<String, Vec<String>>::new();
        for cls in chain.iter().rev() {
            visible.extend(methods.get(cls).cloned().unwrap_or_default());
            for (name, field) in fields.get(cls).into_iter().flatten() {
                if b(&g.e(field)?.attrs, "declared")? {
                    visible.remove(name);
                }
            }
        }
        for defs in visible.values() {
            if defs.len() == 1 {
                let method = &defs[0];
                let decorators = v(&g.e(method)?.attrs, "decorators")?;
                let property = decorators.as_array().is_some_and(|a| {
                    a.iter().filter_map(Value::as_str).any(|d| {
                        ["property", ".setter", ".deleter"]
                            .iter()
                            .any(|end| d.strip_prefix('@').unwrap_or(d).ends_with(end))
                    })
                });
                if property {
                    continue;
                }
                g.add(
                    &id,
                    "EFFECTIVE_METHOD",
                    method,
                    &g.evidence(method)?,
                    json!({"basis":"single-inheritance"}),
                );
            }
        }
        for (name, field) in fields.get(&id).into_iter().flatten() {
            if name.starts_with('#') || (name.starts_with("__") && !name.ends_with("__")) {
                continue;
            }
            let candidates = chain
                .iter()
                .rev()
                .filter_map(|cls| fields.get(cls).and_then(|f| f.get(name)))
                .collect::<Vec<_>>();
            let mut stat = false;
            for c in &candidates {
                stat |= b(&g.e(c)?.attrs, "static")?;
            }
            if stat
                || chain
                    .iter()
                    .any(|cls| methods.get(cls).is_some_and(|m| m.contains_key(name)))
            {
                continue;
            }
            g.add(
                field,
                "INSTANCE_SLOT",
                candidates[0],
                &format!("{}:{}", unit.path, g.e(field)?.line),
                json!({"basis":"single-inheritance","relative_to":id}),
            );
        }
    }
    let members = g.sets("MEMBER_OF");
    let writes = g
        .rows("ASSIGNMENT_TARGET")
        .into_iter()
        .fold(SetMap::new(), |mut m, f| {
            m.entry(f.object).or_default().insert(f.subject);
            m
        });
    let rhs = g.map("ASSIGNMENT_VALUE");
    let locals = g
        .rows("DECLARES")
        .into_iter()
        .map(|f| (f.subject, f.object))
        .collect::<BTreeSet<_>>();
    let mut params = BTreeSet::new();
    for f in g.rows("HAS_PARAMETER") {
        if !b(&f.attrs, "receiver")? {
            params.insert((f.subject, f.object));
        }
    }
    let loop_bindings = g
        .rows("ITERATION_BINDING")
        .into_iter()
        .map(|f| f.object)
        .collect::<BTreeSet<_>>();
    let mut unsafe_ = BTreeSet::new();
    for op in &g.ir.operations {
        if op.kind == "UPDATE"
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
            unsafe_.insert(op.owner.clone());
        }
    }
    for f in g.rows("CALLEE_NAME") {
        if matches!(f.object.as_str(), "eval" | "exec" | "locals" | "globals") {
            unsafe_.insert(s(&g.e(&f.subject)?.attrs, "owner")?);
        }
    }
    let locations =
        g.ir.operations
            .iter()
            .map(|o| {
                Ok((
                    (
                        g.e(&o.owner)?.path.clone(),
                        o.start,
                        o.end,
                        o.native_kind.clone(),
                    ),
                    o.clone(),
                ))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
    for access in members.keys() {
        let entity = g.e(access)?.clone();
        let key = (
            entity.path.clone(),
            v(&entity.attrs, "start_byte")?.as_i64().unwrap_or(-1),
            v(&entity.attrs, "end_byte")?.as_i64().unwrap_or(-1),
            s(&entity.attrs, "native_kind")?,
        );
        let Some(mut use_) = locations.get(&key).cloned() else {
            continue;
        };
        if unsafe_.contains(&use_.owner) {
            continue;
        }
        let mut value = access.clone();
        let mut seen = BTreeSet::new();
        let mut steps = vec![];
        let mut definitions = vec![];
        for _ in 0..32 {
            if !seen.insert(value.clone()) || loop_bindings.contains(&value) {
                break;
            }
            if params.contains(&(use_.owner.clone(), value.clone())) {
                if set(&writes, &value).is_empty() {
                    steps.reverse();
                    g.add(access,"ACCESS_INPUT",&value,&format!("{}:{}",entity.path,entity.line),json!({"basis":"syntax-local-alias","members":steps,"assignments":definitions}));
                }
                break;
            }
            let parents = set(&members, &value);
            if parents.len() == 1 {
                steps.push(g.e(&value)?.name.clone());
                value = parents.into_iter().next().unwrap();
                continue;
            }
            let ws = set(&writes, &value);
            if !locals.contains(&(use_.owner.clone(), value.clone())) || ws.len() != 1 {
                break;
            }
            let Some(write) = g.op(ws.first().unwrap()).cloned() else {
                break;
            };
            if !rhs.contains_key(&write.id)
                || !precedes(
                    g,
                    &write,
                    &use_,
                    &[
                        "expression_statement",
                        "lexical_declaration",
                        "variable_declaration",
                    ],
                )
                || tokens(&write)?.iter().any(|t| t.ends_with('=') && t != "=")
            {
                break;
            }
            definitions.push(write.id.clone());
            value = rhs[&write.id].clone();
            use_ = write;
        }
    }
    Ok(())
}
pub(super) fn contracts(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let receivers = g.sets("MEMBER_OF");
    let mut fields = BTreeMap::<String, BTreeMap<String, String>>::new();
    let mut methods = BTreeMap::<String, BTreeMap<String, String>>::new();
    for f in g.rows("HAS_FIELD") {
        fields
            .entry(f.subject)
            .or_default()
            .insert(g.e(&f.object)?.name.clone(), f.object);
    }
    for f in g.rows("HAS_METHOD") {
        methods
            .entry(f.subject)
            .or_default()
            .insert(g.e(&f.object)?.name.clone(), f.object);
    }
    let mut by_name = BTreeMap::<_, Vec<_>>::new();
    for (id, e) in &g.ir.entities {
        if matches!(e.kind.as_str(), "CLASS" | "INTERFACE") {
            by_name.entry(e.name.clone()).or_default().push(id.clone());
        }
    }
    for (access, rs) in receivers {
        for receiver in rs {
            let Some(e) = g.get(&receiver) else {
                continue;
            };
            let spelling = s(&e.attrs, "type")?;
            let a = rx(r"^[&*]+\s*").replace(trim(&spelling), "");
            let a = rx(r"^(?:dyn|impl|mut|const)\s+")
                .replace(&a, "")
                .into_owned();
            let a = trim(&a);
            if full(r"[A-Za-z_][\w.]*", a).is_none() {
                continue;
            }
            let Some(candidates) = by_name.get(a).filter(|v| v.len() == 1) else {
                continue;
            };
            let unit = &candidates[0];
            let name = &g.e(&access)?.name;
            let field = fields.get(unit).and_then(|t| t.get(name));
            let method = methods.get(unit).and_then(|t| t.get(name));
            if field.is_some() || method.is_some() {
                if let Some(field) = field {
                    g.add(
                        &access,
                        "MEMBER_DECLARATION",
                        field,
                        &g.evidence(&access)?,
                        json!({"basis":"nominal-receiver"}),
                    );
                }
                break;
            }
        }
    }
    let mut arity = BTreeMap::<String, usize>::new();
    for f in g.rows("HAS_PARAMETER") {
        if !b(&f.attrs, "receiver")? {
            *arity.entry(f.subject).or_default() += 1;
        }
    }
    let mut required = BTreeMap::new();
    let mut provided = BTreeMap::new();
    for (owner, table) in &methods {
        if let Some(e) = g.get(owner)
            && s(&e.attrs, "language")? == "go"
        {
            if e.kind == "INTERFACE" {
                required.insert(owner.clone(), table);
            } else if e.kind == "CLASS" {
                provided.insert(owner.clone(), table);
            }
        }
    }
    for (interface, wanted) in required {
        if wanted.is_empty() {
            continue;
        }
        for (concrete, available) in &provided {
            if !wanted.iter().all(|(name, m)| {
                available
                    .get(name)
                    .is_some_and(|a| arity.get(a).unwrap_or(&0) == arity.get(m).unwrap_or(&0))
            }) {
                continue;
            }
            let evidence = g.evidence(concrete)?;
            g.add(
                concrete,
                "IMPLEMENTS",
                &interface,
                &evidence,
                json!({"basis":"method-set"}),
            );
            for (name, contract) in wanted {
                g.add(
                    &available[name],
                    "OVERRIDES",
                    contract,
                    &evidence,
                    json!({"basis":"method-set"}),
                );
            }
        }
    }
    let mut members = BTreeMap::<(String, usize), Vec<String>>::new();
    let mut owners = BTreeMap::<(String, usize), BTreeSet<String>>::new();
    // Python dictionaries retain the first declaring owner's order. It selects
    // the shared signature's evidence location, so a sorted map is not equivalent.
    let mut seen_owners = BTreeSet::new();
    let method_owners = g
        .rows("HAS_METHOD")
        .into_iter()
        .filter_map(|f| seen_owners.insert(f.subject.clone()).then_some(f.subject))
        .collect::<Vec<_>>();
    for owner in &method_owners {
        let table = &methods[owner];
        if !g
            .get(owner)
            .is_some_and(|e| matches!(e.kind.as_str(), "CLASS" | "INTERFACE"))
        {
            continue;
        }
        for (name, member) in table {
            if name.is_empty() || b(&g.e(member)?.attrs, "constructor")? {
                continue;
            }
            let key = (name.clone(), *arity.get(member).unwrap_or(&0));
            members.entry(key.clone()).or_default().push(member.clone());
            owners.entry(key).or_default().insert(owner.clone());
        }
    }
    for ((name, count), owners) in owners {
        if owners.len() < 2 {
            continue;
        }
        let signature = format!("signature:{name}/{count}");
        let members = &members[&(name.clone(), count)];
        let first = g.e(&members[0])?.clone();
        let evidence = format!("{}:{}", first.path, first.line);
        if g.get(&signature).is_none() {
            g.insert(Entity {
                id: signature.clone(),
                kind: "SIGNATURE".into(),
                name: name.clone(),
                path: first.path,
                line: first.line,
                end_line: first.end_line,
                attrs: attrs(json!({"name":name,"arity":count,"language":g.ir.language})),
            });
            g.add(
                &signature,
                "IS",
                "SIGNATURE",
                &evidence,
                json!({"basis":"shared-member-signature"}),
            );
        }
        for member in members {
            g.add(
                member,
                "MATCHES_SIGNATURE",
                &signature,
                &evidence,
                json!({"basis":"shared-member-signature"}),
            );
        }
    }
    Ok(())
}
pub(super) fn events(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let events = g
        .rows("DECLARES_EVENT")
        .into_iter()
        .map(|f| f.object)
        .collect::<BTreeSet<_>>();
    if events.is_empty() {
        return Ok(());
    }
    let declared = g.map("MEMBER_DECLARATION");
    let targets = g.map("ASSIGNMENT_TARGET");
    let handlers = g.map("ASSIGNMENT_VALUE");
    for op in g.ir.operations.clone() {
        let token = tokens(&op)?
            .into_iter()
            .find(|t| matches!(t.as_str(), "+=" | "-="));
        let Some(token) = token else {
            continue;
        };
        let Some(target) = targets.get(&op.id) else {
            continue;
        };
        let slot = if events.contains(target) {
            target
        } else {
            lookup(&declared, target)
        };
        if !events.contains(slot) {
            continue;
        }
        let evidence = g
            .get(&op.owner)
            .map(|e| format!("{}:{}", e.path, op.line))
            .unwrap_or_default();
        g.add(
            &op.owner,
            if token == "+=" {
                "ADDS_HANDLER"
            } else {
                "REMOVES_HANDLER"
            },
            slot,
            &evidence,
            json!({"handler":lookup(&handlers,&op.id)}),
        );
    }
    let owners = g.reverse("HAS_CALL");
    for rel in ["RECEIVER", "CALLEE_VALUE"] {
        for f in g.rows(rel) {
            if events.contains(&f.object) {
                g.add(
                    &f.subject,
                    "RAISES_EVENT",
                    &f.object,
                    ev(&f),
                    json!({"basis":"event-invocation"}),
                );
                if let Some(owner) = owners.get(&f.subject) {
                    g.add(
                        owner,
                        "METHOD_RAISES_EVENT",
                        &f.object,
                        ev(&f),
                        json!({"basis":"event-invocation"}),
                    );
                }
            }
        }
    }
    Ok(())
}
