//! Explicit-import API models for Optional and Python concurrency.
use super::*;
pub(super) fn optional(g: &mut Graph) -> Result<()> {
    let mut imports = SetMap::new();
    let mut arguments = BTreeMap::<String, BTreeMap<i64, String>>::new();
    let mut receivers = BTreeMap::<String, Vec<String>>::new();
    let assignments = g.sets("ASSIGNED_FROM");
    for f in &g.ir.facts {
        match f.relation.as_str() {
            "IMPORT_SYNTAX" if s(&f.attrs, "language")? == "java" => {
                if let Some(m) = full(r"import\s+([\w.]+\.Optional)\s*;", &f.object) {
                    imports
                        .entry(
                            f.subject
                                .strip_suffix("::module")
                                .unwrap_or(&f.subject)
                                .into(),
                        )
                        .or_default()
                        .insert(m[1].into());
                }
            }
            "ARGUMENT" => {
                arguments
                    .entry(f.subject.clone())
                    .or_default()
                    .insert(n(&f.attrs, "position")?, f.object.clone());
            }
            "RECEIVER" => receivers
                .entry(f.object.clone())
                .or_default()
                .push(f.subject.clone()),
            _ => {}
        }
    }
    let mut shadowed = BTreeSet::new();
    for (_, e) in &g.ir.entities {
        if e.name == "Optional"
            && (matches!(
                e.kind.as_str(),
                "CLASS" | "INTERFACE" | "PARAMETER" | "CALLABLE"
            ) || b(&e.attrs, "declared")?)
        {
            shadowed.insert(e.path.clone());
        }
    }
    let mut aliases = BTreeMap::<String, Vec<String>>::new();
    for (storage, values) in assignments {
        if values.len() == 1 {
            aliases
                .entry(values.first().unwrap().clone())
                .or_default()
                .push(storage);
        }
    }
    let mut pending = VecDeque::new();
    for (receiver, calls) in &receivers {
        let Some(symbol) = g.get(receiver).cloned() else {
            continue;
        };
        if symbol.name != "Optional"
            || shadowed.contains(&symbol.path)
            || symbol.kind != "STORAGE"
            || s(&symbol.attrs, "native_kind")? != "identifier"
            || set(&imports, &symbol.path) != ["java.util.Optional".into()].into()
        {
            continue;
        }
        for call in calls {
            if s(&g.e(call)?.attrs, "name")? == "ofNullable"
                && let Some(args) = arguments.get(call)
                && args.len() == 1
                && args.contains_key(&0)
            {
                g.add(
                    call,
                    "OPTIONAL_VALUE",
                    &args[&0],
                    &g.evidence(call)?,
                    json!({"model":"java.util.Optional.ofNullable"}),
                );
                pending.push_back(call.clone());
            }
        }
    }
    let mut visited = BTreeSet::new();
    while let Some(receiver) = pending.pop_front() {
        if !visited.insert(receiver.clone()) {
            continue;
        }
        pending.extend(aliases.get(&receiver).into_iter().flatten().cloned());
        for call in receivers.get(&receiver).into_iter().flatten() {
            let name = s(&g.e(call)?.attrs, "name")?;
            let relation = match name.as_str() {
                "or" => "OPTIONAL_OR",
                "ifPresent" => "OPTIONAL_PRESENT",
                "orElse" => "OPTIONAL_FALLBACK",
                _ => "",
            };
            if !relation.is_empty()
                && let Some(args) = arguments.get(call)
                && args.len() == 1
                && args.contains_key(&0)
            {
                g.add(
                    call,
                    relation,
                    &args[&0],
                    &g.evidence(call)?,
                    json!({"model":format!("java.util.Optional.{name}")}),
                );
                if name == "or" {
                    pending.push_back(call.clone());
                }
            }
        }
    }
    Ok(())
}
pub(super) fn concurrency(g: &mut Graph) -> Result<()> {
    let mut aliases = BTreeMap::<(String, String), String>::new();
    for f in g.rows("IMPORT_SYNTAX") {
        if s(&f.attrs, "language")? != "python" {
            continue;
        }
        let path = f.subject.strip_suffix("::module").unwrap_or(&f.subject);
        if let Some(m) = full(r"import\s+(threading|asyncio)(?:\s+as\s+(\w+))?", &f.object) {
            aliases.insert(
                (
                    path.into(),
                    m.get(2).unwrap_or(m.get(1).unwrap()).as_str().into(),
                ),
                m[1].into(),
            );
        }
        if let Some(m) = full(r"from\s+(threading|asyncio)\s+import\s+(.+)", &f.object) {
            for item in m[2].split(',') {
                let pattern = rx(r"\s+as\s+");
                let parts = pattern.split(trim(item)).collect::<Vec<_>>();
                aliases.insert(
                    (path.into(), parts.last().unwrap().to_string()),
                    format!("{}.{}", &m[1], parts[0]),
                );
            }
        }
    }
    let names = g.map("CALLEE_NAME");
    let receiver = g.map("RECEIVER");
    let args = g.groups("ARGUMENT");
    let assigned = g.rows("ASSIGNED_FROM");
    let rebound = assigned
        .iter()
        .map(|f| f.subject.clone())
        .collect::<BTreeSet<_>>();
    let shadowed =
        g.ir.entities
            .iter()
            .filter(|(_, e)| {
                aliases.contains_key(&(e.path.clone(), e.name.clone()))
                    && (matches!(e.kind.as_str(), "PARAMETER" | "CALLABLE" | "CLASS")
                        || rebound.contains(&e.id))
            })
            .map(|(_, e)| (e.path.clone(), e.name.clone()))
            .collect::<BTreeSet<_>>();
    let mut contexts = SetMap::new();
    for (call, name) in &names {
        let e = g.e(call)?.clone();
        let rec = receiver.get(call);
        let rec_entity = rec.and_then(|r| g.get(r));
        let alias = rec_entity.map_or(name.as_str(), |r| r.name.as_str());
        let mut api = aliases
            .get(&(e.path.clone(), alias.into()))
            .cloned()
            .unwrap_or_default();
        if api.is_empty()
            || rec.is_some_and(|r| rebound.contains(r))
            || shadowed.contains(&(e.path.clone(), alias.into()))
        {
            continue;
        }
        if rec_entity.is_some() {
            api.push('.');
            api.push_str(name);
        }
        if matches!(
            api.as_str(),
            "threading.Thread" | "threading.Lock" | "threading.RLock" | "asyncio.create_task"
        ) {
            contexts
                .entry(call.clone())
                .or_default()
                .insert(call.clone());
            let evidence = format!("{}:{}", e.path, e.line);
            let effect = if api.ends_with(".Lock") || api.ends_with(".RLock") {
                "CREATES_LOCK"
            } else {
                "CREATES_CONTEXT"
            };
            g.add(call, effect, call, &evidence, json!({"api":api}));
            if api == "asyncio.create_task" {
                g.add(call, "STARTS_CONTEXT", call, &evidence, json!({"api":api}));
            }
            for arg in args.get(call).into_iter().flatten() {
                if s(&arg.attrs, "name")? == "target"
                    || (api == "asyncio.create_task" && v(&arg.attrs, "position")? == json!(0))
                {
                    g.add(call, "CONTEXT_ENTRY", &arg.object, &evidence, json!({}));
                }
            }
        }
    }
    for _ in 0..16 {
        let mut changed = false;
        for f in &assigned {
            let inherited = set(&contexts, &f.object);
            if inherited.is_empty() {
                continue;
            }
            let values = contexts.entry(f.subject.clone()).or_default();
            let before = values.len();
            values.extend(inherited);
            changed |= before != values.len();
        }
        if !changed {
            break;
        }
    }
    let mut creations = BTreeMap::new();
    for f in &g.ir.facts {
        if matches!(f.relation.as_str(), "CREATES_LOCK" | "CREATES_CONTEXT") {
            creations
                .entry(f.subject.clone())
                .or_insert_with(|| f.clone());
        }
    }
    for (call, rec) in receiver {
        let Some(possible) = contexts.get(&rec) else {
            continue;
        };
        let ambiguous = possible.len() != 1;
        for context in possible {
            let name = lookup(&names, &call);
            let Some(creation) = creations.get(context) else {
                continue;
            };
            let effect = match name {
                "start" | "join" if creation.relation == "CREATES_CONTEXT" => {
                    if name == "start" {
                        "STARTS_CONTEXT"
                    } else {
                        "WAITS_FOR"
                    }
                }
                "acquire" | "release" if creation.relation == "CREATES_LOCK" => {
                    if name == "acquire" {
                        "ACQUIRES_LOCK"
                    } else {
                        "RELEASES_LOCK"
                    }
                }
                _ => continue,
            };
            let effect = if ambiguous
                || (name == "join" && args.get(&call).is_some_and(|a| !a.is_empty()))
            {
                format!("MAY_{effect}")
            } else {
                effect.into()
            };
            g.add(&call, &effect, context, &g.evidence(&call)?, json!({}));
        }
    }
    g.ir.capabilities.insert("python_concurrency_api".into());
    Ok(())
}
