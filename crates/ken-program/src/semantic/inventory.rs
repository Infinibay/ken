//! Explicit source write counts and small contracts over supported summaries.
use super::*;
pub(super) fn allocations(g: &mut Graph) -> Result<()> {
    let mut sites = SetMap::new();
    for f in g.rows("ALLOCATES_TYPE") {
        if g.get(&f.subject).is_some_and(|e| e.kind == "CALL") {
            sites.entry(f.object).or_default().insert(f.subject);
        }
    }
    for id in g.ids() {
        if g.e(&id)?.kind == "CLASS" {
            let count = set(&sites, &id).len();
            g.add(
                &id,
                "RESOLVED_ALLOCATION_COUNT",
                &count.to_string(),
                &g.evidence(&id)?,
                json!({"count":count,"basis":"explicit-resolved-sites"}),
            );
        }
    }
    Ok(())
}
fn inside_branch(g: &Graph, op: &Operation) -> bool {
    let mut current = op.parent.as_deref().and_then(|p| g.op(p));
    let mut seen = BTreeSet::new();
    while let Some(cur) = current {
        if !seen.insert(&cur.id) {
            return true;
        }
        if matches!(
            cur.native_kind.as_str(),
            "if_statement" | "elif_clause" | "else_clause"
        ) {
            return true;
        }
        if cur.kind == "FUNCTION" {
            return false;
        }
        current = cur.parent.as_deref().and_then(|p| g.op(p));
    }
    false
}
pub(super) fn binding_writes(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let targets = g.map("ASSIGNMENT_TARGET");
    let members = g
        .rows("MEMBER_OF")
        .into_iter()
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    let nested = g.nested()?;
    let cfg = g.map("CFG_STATUS");
    let call_owners = g.reverse("HAS_CALL");
    let dynamic = g.dynamic()?;
    let mut candidates = SetMap::new();
    for rel in ["HAS_PARAMETER", "READS"] {
        for f in g.rows(rel) {
            candidates.entry(f.subject).or_default().insert(f.object);
        }
    }
    for rel in ["RECEIVER", "ARGUMENT"] {
        for f in g.rows(rel) {
            if let Some(owner) = call_owners.get(&f.subject) {
                candidates
                    .entry(owner.clone())
                    .or_default()
                    .insert(f.object);
            }
        }
    }
    for (owner, ops) in g.owners() {
        let entity = g.e(&owner)?.clone();
        if entity.kind != "CALLABLE" || !COMMON.contains(&s(&entity.attrs, "language")?.as_str()) {
            continue;
        }
        let mut reason = if lookup(&cfg, &owner) != "structured"
            || nested.contains(&owner)
            || dynamic.contains(&owner)
        {
            "control-or-dynamic-scope"
        } else {
            ""
        };
        let mut writes = BTreeMap::<String, Vec<Operation>>::new();
        for op in &ops {
            if reason.is_empty()
                && (matches!(op.kind.as_str(), "UPDATE" | "LOOP")
                    || matches!(
                        op.native_kind.as_str(),
                        "global_statement"
                            | "nonlocal_statement"
                            | "delete_statement"
                            | "named_expression"
                    ))
            {
                reason = "indirect-write";
            }
            if reason.is_empty()
                && tokens(op)?.iter().any(|t| {
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
                            | "&="
                            | "|="
                            | "^="
                            | "<<="
                            | ">>="
                    )
                })
            {
                reason = "indirect-write";
            }
            if let Some(target) = targets.get(&op.id) {
                if reason.is_empty()
                    && !g.get(target).is_some_and(|e| {
                        matches!(e.kind.as_str(), "STORAGE" | "PARAMETER")
                            || members.contains(target)
                    })
                {
                    reason = "unmodeled-target";
                }
                writes.entry(target.clone()).or_default().push(op.clone());
            }
            if reason.is_empty()
                && op.kind == "ASSIGN"
                && (!targets.contains_key(&op.id) || !tokens(op)?.iter().any(|t| t == "="))
            {
                reason = "unmodeled-assignment";
            }
        }
        g.add(
            &owner,
            "BINDING_WRITE_STATUS",
            if reason.is_empty() {
                "supported"
            } else {
                "unsupported"
            },
            "",
            json!({"analysis":"binding-writes/1","reason":reason}),
        );
        if !reason.is_empty() {
            continue;
        }
        let evidence = format!("{}:{}", entity.path, entity.line);
        for (target, events) in &writes {
            g.add(&owner,"BINDING_WRITE_COUNT",target,&evidence,json!({"count":events.len(),"basis":"explicit-writes","analysis":"binding-writes/1"}));
            if events.len() == 1 && !inside_branch(g, &events[0]) {
                let op = &events[0];
                g.add(
                    &op.id,
                    "UNIQUE_BINDING_WRITE",
                    target,
                    &format!("{}:{}", entity.path, op.line),
                    json!({"basis":"explicit-writes","analysis":"binding-writes/1"}),
                );
            }
        }
        for binding in set(&candidates, &owner) {
            if !writes.contains_key(&binding)
                && g.get(&binding).is_some_and(|e| {
                    matches!(e.kind.as_str(), "STORAGE" | "PARAMETER") || members.contains(&binding)
                })
            {
                g.add(
                    &owner,
                    "BINDING_WRITE_COUNT",
                    &binding,
                    &evidence,
                    json!({"count":0,"basis":"explicit-writes","analysis":"binding-writes/1"}),
                );
                g.add(
                    &owner,
                    "UNREASSIGNED_BINDING",
                    &binding,
                    &evidence,
                    json!({"basis":"explicit-writes","analysis":"binding-writes/1"}),
                );
            }
        }
    }
    Ok(())
}
pub(super) fn writes(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let targets = g.map("ASSIGNMENT_TARGET");
    let mut counts = BTreeMap::<String, usize>::new();
    for target in targets.values() {
        *counts.entry(target.clone()).or_default() += 1;
    }
    for f in g.rows("ITERATION_BINDING") {
        *counts.entry(f.object).or_default() += 1;
    }
    let indexed_locations = g
        .rows("CONTAINER")
        .into_iter()
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    let mut opaque = BTreeSet::new();
    for op in &g.ir.operations {
        let path = &g.e(&op.owner)?.path;
        if (op.kind == "ASSIGN" && !targets.contains_key(&op.id))
            || matches!(
                op.native_kind.as_str(),
                "global_statement"
                    | "nonlocal_statement"
                    | "delete_statement"
                    | "named_expression"
                    | "as_pattern"
            )
            || op.kind == "UPDATE"
        {
            opaque.insert(path.clone());
        }
        if let Some(target) = targets.get(&op.id)
            && !g.get(target).is_some_and(|e| {
                matches!(e.kind.as_str(), "STORAGE" | "PARAMETER" | "MEMBER")
                    || indexed_locations.contains(&e.id)
            })
        {
            opaque.insert(path.clone());
        }
    }
    for f in g.rows("CALLEE_NAME") {
        if DYNAMIC.contains(&f.object.as_str()) {
            opaque.insert(g.e(&f.subject)?.path.clone());
        }
    }
    for id in g.ids() {
        let e = g.e(&id)?.clone();
        if !matches!(e.kind.as_str(), "STORAGE" | "PARAMETER" | "MEMBER") {
            continue;
        }
        let supported = !opaque.contains(&e.path);
        g.add(
            &id,
            "STORAGE_WRITE_STATUS",
            if supported {
                "supported"
            } else {
                "unsupported"
            },
            "",
            json!({"basis":"explicit-source-inventory/1"}),
        );
        if supported {
            g.add(
                &id,
                "STORAGE_WRITE_COUNT",
                &counts.get(&id).unwrap_or(&0).to_string(),
                "",
                json!({"basis":"explicit-source-inventory/1"}),
            );
        }
    }
    let indexes = g.map("INDEX");
    let mut indexed = BTreeMap::<(String, String, String), BTreeSet<String>>::new();
    for f in g.rows("WRITES_ELEMENT") {
        if let (Some(index), Some(op)) = (indexes.get(&f.subject), g.op(&f.subject)) {
            indexed
                .entry((op.owner.clone(), f.object, index.clone()))
                .or_default()
                .insert(op.id.clone());
        }
    }
    for ((owner, _, _), writes) in indexed {
        if !opaque.contains(&g.e(&owner)?.path) {
            for write in &writes {
                g.add(
                    write,
                    "INDEXED_WRITE_COUNT",
                    &writes.len().to_string(),
                    "",
                    json!({"basis":"same-owner-container-index/1"}),
                );
            }
        }
    }
    let syntax = g.map("SYNTAX_NODE");
    let mut clears = BTreeMap::<(String, String), Vec<i64>>::new();
    for f in g.rows("CLEARS_COLLECTION") {
        if let Some(op) = g.op(syntax
            .get(&f.subject)
            .map_or(f.subject.as_str(), String::as_str))
        {
            clears
                .entry((op.owner.clone(), f.object))
                .or_default()
                .push(op.start);
        }
    }
    let mut writes_by_owner = BTreeMap::<(String, String), Vec<i64>>::new();
    let mut binding_events = BTreeMap::<(String, String), Vec<(i64, String, bool)>>::new();
    for (id, binding) in &targets {
        if let Some(op) = g.op(id) {
            writes_by_owner
                .entry((op.owner.clone(), binding.clone()))
                .or_default()
                .push(op.start);
            binding_events
                .entry((op.owner.clone(), binding.clone()))
                .or_default()
                .push((op.end, op.id.clone(), false));
        }
    }
    for f in g.rows("ITERATION_BINDING") {
        if let Some(op) = g.op(&f.subject) {
            writes_by_owner
                .entry((op.owner.clone(), f.object.clone()))
                .or_default()
                .push(op.start);
            binding_events
                .entry((op.owner.clone(), f.object))
                .or_default()
                .push((op.start, op.id.clone(), true));
        }
    }
    for f in g.rows("ITERATION_SOURCE") {
        if let Some(loop_) = g.op(&f.subject).cloned()
            && !opaque.contains(&g.e(&loop_.owner)?.path)
        {
            let key = (loop_.owner.clone(), f.object.clone());
            if !writes_by_owner
                .get(&key)
                .into_iter()
                .flatten()
                .chain(clears.get(&key).into_iter().flatten())
                .any(|&start| start < loop_.start)
            {
                g.add(
                    &loop_.id,
                    "ITERATION_ENTRY_SOURCE",
                    &f.object,
                    "",
                    json!({"basis":"no-prior-explicit-replacement-or-clear/1"}),
                );
            }
        }
    }
    let fields = g
        .rows("HAS_FIELD")
        .into_iter()
        .map(|f| f.object)
        .collect::<BTreeSet<_>>();
    let mut reads = SetMap::new();
    for f in g.rows("READS") {
        if fields.contains(&f.object) {
            reads.entry(f.subject).or_default().insert(f.object);
        }
    }
    let call_owners = g.reverse("HAS_CALL");
    for events in binding_events.values_mut() {
        events.sort();
    }
    for f in g.rows("RECEIVER") {
        let (Some(call), Some(owner)) = (g.get(&f.subject), call_owners.get(&f.subject)) else {
            continue;
        };
        if opaque.contains(&call.path) {
            continue;
        }
        let start = v(&call.attrs, "start_byte")?.as_i64().unwrap_or(-1);
        let events = binding_events
            .get(&(owner.clone(), f.object.clone()))
            .map_or(&[][..], Vec::as_slice);
        let position = events.partition_point(|event| event.0 <= start);
        let previous = position.checked_sub(1).map(|i| &events[i]);
        let version = previous.map_or(f.object.as_str(), |e| e.1.as_str());
        g.add(
            &f.subject,
            "RECEIVER_BINDING_VERSION",
            version,
            ev(&f),
            json!({"basis":"explicit-receiver-write-prefix/1"}),
        );
        if previous.is_none_or(|e| e.2) {
            g.add(
                &f.subject,
                "RECEIVER_UNREPLACED",
                &f.object,
                ev(&f),
                json!({"basis":"explicit-receiver-write-prefix/1"}),
            );
        }
    }
    for f in g.rows("TARGET") {
        let (Some(call), Some(owner)) = (g.get(&f.subject).cloned(), call_owners.get(&f.subject))
        else {
            continue;
        };
        if opaque.contains(&call.path) {
            continue;
        }
        for binding in set(&reads, &f.object) {
            let key = (owner.clone(), binding.clone());
            let start = v(&call.attrs, "start_byte")?.as_i64().unwrap_or(-1);
            if !writes_by_owner
                .get(&key)
                .into_iter()
                .flatten()
                .chain(clears.get(&key).into_iter().flatten())
                .any(|&p| p < start)
            {
                g.add(
                    &call.id,
                    "CALL_ENTRY_BINDING",
                    &binding,
                    "",
                    json!({"basis":"no-prior-explicit-replacement-or-clear/1"}),
                );
            }
        }
    }
    Ok(())
}
pub(super) fn values(g: &mut Graph) -> Result<()> {
    let return_owners =
        g.ir.operations
            .iter()
            .filter(|o| o.kind == "RETURN")
            .map(|o| (o.id.clone(), o.owner.clone()))
            .collect::<BTreeMap<_, _>>();
    let supported = g
        .rows("RETURN_FLOW_STATUS")
        .into_iter()
        .filter(|f| f.object == "supported")
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    let mut origins = SetMap::new();
    for f in g.rows("RETURN_ORIGIN") {
        if let Some(owner) = return_owners.get(&f.subject) {
            origins.entry(owner.clone()).or_default().insert(f.object);
        }
    }
    let targets = g.sets("TARGET");
    let receivers = g
        .rows("RECEIVER")
        .into_iter()
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    let unsafe_ = g
        .rows("DECORATED_BY")
        .into_iter()
        .map(|f| f.subject)
        .chain(g.rows("ASSIGNMENT_TARGET").into_iter().map(|f| f.object))
        .collect::<BTreeSet<_>>();
    let mut dynamic_paths = BTreeSet::new();
    for f in g.rows("CALLEE_NAME") {
        if DYNAMIC.contains(&f.object.as_str()) {
            dynamic_paths.insert(g.e(&f.subject)?.path.clone());
        }
    }
    for op in &g.ir.operations {
        let e = g.e(&op.owner)?;
        if op.native_kind == "with_statement"
            && matches!(
                s(&e.attrs, "language")?.as_str(),
                "javascript" | "typescript"
            )
        {
            dynamic_paths.insert(e.path.clone());
        }
    }
    let callee_values = g.map("CALLEE_VALUE");
    for id in g.ids() {
        let entity = g.e(&id)?.clone();
        if entity.kind != "CALL" {
            continue;
        }
        let mut kind = "unknown";
        let ts = set(&targets, &id);
        if g.ir.diagnostics.is_empty() && ts.len() == 1 {
            let target = ts.first().unwrap();
            let os = set(&origins, target);
            let mut scalar = !os.is_empty();
            for value in &os {
                scalar &= value == "NULL"
                    || if let Some(e) = g.get(value) {
                        e.kind == "VALUE"
                            && matches!(
                                s(&e.attrs, "type")?.as_str(),
                                "int" | "float" | "number" | "str" | "bool" | "char"
                            )
                    } else {
                        false
                    };
            }
            if supported.contains(target)
                && scalar
                && !receivers.contains(&id)
                && !unsafe_.contains(target)
                && !dynamic_paths.contains(&entity.path)
                && !dynamic_paths.contains(&g.e(target)?.path)
                && callee_values.get(&id) == Some(target)
            {
                kind = "scalar";
            }
        }
        g.add(
            &id,
            "CALL_RESULT_KIND",
            kind,
            "",
            json!({"basis":"supported-local-return-origins/1"}),
        );
    }
    let counts = g.map("STORAGE_WRITE_COUNT");
    let mut writes = BTreeMap::<String, Vec<Operation>>::new();
    for f in g.rows("ASSIGNMENT_TARGET") {
        if let Some(op) = g.op(&f.subject) {
            writes.entry(f.object).or_default().push(op.clone());
        }
    }
    let values = g.map("ASSIGNMENT_VALUE");
    let mut owners = g.reverse("DECLARES");
    owners.extend(g.map("OWNED_BY"));
    let mut params = BTreeMap::new();
    for f in g.rows("HAS_PARAMETER") {
        if !b(&f.attrs, "receiver")? {
            params.insert(f.object, f.subject);
        }
    }
    for f in g.rows("BASE_VALUE") {
        let derived = g.e(&f.subject)?.clone();
        let owner = owners.get(&derived.id);
        let mut current = f.object.clone();
        let mut before = v(&derived.attrs, "start_byte")?.as_i64().unwrap_or(-1);
        let mut seen = BTreeSet::new();
        while seen.len() < 32 && seen.insert(current.clone()) {
            if params.get(&current) == owner && lookup(&counts, &current) == "0" {
                g.add(
                    &derived.id,
                    "BASE_INPUT",
                    &current,
                    ev(&f),
                    json!({"basis":"unique-preceding-base-alias/1"}),
                );
                break;
            }
            let ws = writes.get(&current).cloned().unwrap_or_default();
            if lookup(&counts, &current) != "1" || ws.len() != 1 {
                break;
            }
            let write = &ws[0];
            if Some(&write.owner) != owner
                || write.start >= before
                || s(&write.attrs, "execution")? != "possible"
            {
                break;
            }
            let mut parent = write.parent.as_deref().and_then(|p| g.op(p));
            let mut path = BTreeSet::new();
            while let Some(p) = parent {
                if !matches!(
                    p.native_kind.as_str(),
                    "expression_statement"
                        | "lexical_declaration"
                        | "variable_declaration"
                        | "declaration"
                ) {
                    break;
                }
                if !path.insert(p.id.clone()) {
                    parent = None;
                    break;
                }
                parent = p.parent.as_deref().and_then(|p| g.op(p));
            }
            if parent.is_none_or(|p| {
                p.role != "body"
                    || p.parent
                        .as_deref()
                        .and_then(|p| g.op(p))
                        .is_none_or(|p| p.kind != "FUNCTION")
            }) {
                break;
            }
            before = write.start;
            current = lookup(&values, &write.id).into();
        }
    }
    Ok(())
}
