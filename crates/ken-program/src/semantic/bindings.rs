//! Occurrence-correlated argument binding and conservative constructor selection.
use super::*;
pub(super) fn bindings(g: &mut Graph) -> Result<()> {
    if !g.ir.diagnostics.is_empty() {
        return Ok(());
    }
    let mut params = BTreeMap::<String, Vec<Fact>>::new();
    for f in g.rows("HAS_PARAMETER") {
        if !b(&f.attrs, "receiver")? {
            params.entry(f.subject.clone()).or_default().push(f);
        }
    }
    let arguments = g.groups("ARGUMENT");
    let mut targets = SetMap::new();
    for f in g.rows("TARGET") {
        if g.get(&f.object).is_some_and(|e| e.kind == "CALLABLE") {
            targets.entry(f.subject).or_default().insert(f.object);
        }
    }
    let mut constructors = BTreeMap::<String, Vec<String>>::new();
    let mut methods = BTreeMap::<String, Vec<String>>::new();
    for f in g.rows("HAS_METHOD") {
        methods
            .entry(f.subject.clone())
            .or_default()
            .push(f.object.clone());
        if b(&g.e(&f.object)?.attrs, "constructor")? {
            constructors.entry(f.subject).or_default().push(f.object);
        }
    }
    let mut unsupported = BTreeSet::new();
    for op in &g.ir.operations {
        if tokens(op)?
            .iter()
            .any(|t| matches!(t.as_str(), "ref" | "out" | "params"))
        {
            unsupported.insert(op.owner.clone());
        }
    }
    for f in g.rows("ALLOCATES_TYPE") {
        let unit = g.e(&f.object)?.clone();
        let language = s(&unit.attrs, "language")?;
        let mut candidates = constructors.get(&f.object).cloned().unwrap_or_default();
        let mut basis = "unique-declaration";
        let actual = arguments.get(&f.subject).cloned().unwrap_or_default();
        let mut fixed = true;
        for a in &actual {
            fixed &= s(&a.attrs, "kind")? == "positional";
        }
        for c in &candidates {
            for p in params.get(c).into_iter().flatten() {
                fixed &= s(&p.attrs, "kind")? == "positional" && !b(&p.attrs, "default")?;
            }
        }
        if candidates.len() > 1
            && matches!(language.as_str(), "java" | "csharp")
            && !candidates.iter().any(|c| unsupported.contains(c))
            && fixed
        {
            let compatible = candidates
                .iter()
                .filter(|c| params.get(*c).map_or(0, Vec::len) == actual.len())
                .cloned()
                .collect::<Vec<_>>();
            if compatible.len() == 1 {
                candidates = compatible;
                basis = "unique-fixed-arity";
            }
        }
        if !COMMON.contains(&language.as_str()) {
            g.add(
                &f.subject,
                "CONSTRUCTOR_STATUS",
                "unsupported",
                ev(&f),
                json!({"reason":"language"}),
            );
            continue;
        }
        if language == "python"
            && methods
                .get(&f.object)
                .into_iter()
                .flatten()
                .any(|m| g.get(m).is_some_and(|e| e.name == "__new__"))
        {
            g.add(
                &f.subject,
                "CONSTRUCTOR_STATUS",
                "unsupported",
                ev(&f),
                json!({"reason":"custom-allocation"}),
            );
            continue;
        }
        if candidates.len() == 1 {
            g.add(
                &f.subject,
                "CONSTRUCTOR_TARGET",
                &candidates[0],
                ev(&f),
                json!({"basis":basis}),
            );
            g.add(
                &f.subject,
                "CONSTRUCTOR_STATUS",
                "resolved",
                ev(&f),
                json!({"basis":basis}),
            );
            targets.insert(f.subject.clone(), candidates.into_iter().collect());
        } else {
            for candidate in &candidates {
                g.add(
                    &f.subject,
                    "MAY_CONSTRUCTOR_TARGET",
                    candidate,
                    ev(&f),
                    json!({"modality":"may"}),
                );
            }
            g.add(&f.subject,"CONSTRUCTOR_STATUS","unsupported",ev(&f),json!({"reason":if candidates.is_empty(){"implicit-or-inherited"}else{"ambiguous"}}));
        }
    }
    for (call, ts) in targets {
        if ts.len() != 1 {
            continue;
        }
        let target = ts.into_iter().next().unwrap();
        let entity = g.e(&target)?.clone();
        let language = s(&entity.attrs, "language")?;
        let evidence = g.evidence(&call)?;
        let mut signature = params.get(&target).cloned().unwrap_or_default();
        let mut actual = arguments.get(&call).cloned().unwrap_or_default();
        for p in signature.iter().chain(&actual) {
            n(&p.attrs, "position")?;
        }
        signature.sort_by_key(|p| n(&p.attrs, "position").unwrap());
        actual.sort_by_key(|p| n(&p.attrs, "position").unwrap());
        let mut reason = if !COMMON.contains(&language.as_str()) {
            "language"
        } else if unsupported.contains(&target) {
            "parameter-mode"
        } else {
            ""
        };
        if reason.is_empty() {
            for a in &actual {
                if s(&a.attrs, "kind")?.starts_with("spread") {
                    reason = "expanded-arguments";
                }
            }
        }
        if reason.is_empty() {
            for p in &signature {
                if s(&p.attrs, "kind")?.starts_with("variadic") {
                    reason = "variadic-parameters";
                }
            }
        }
        let mut positional = vec![];
        let mut names = BTreeMap::new();
        for p in &signature {
            if s(&p.attrs, "kind")? != "keyword_only" {
                positional.push(p);
            }
            names.insert(g.e(&p.object)?.name.clone(), p);
        }
        let mut bound = BTreeSet::new();
        let mut pending = vec![];
        let (mut position, mut named_seen) = (0, false);
        for argument in &actual {
            if !reason.is_empty() {
                break;
            }
            let kind = s(&argument.attrs, "kind")?;
            let mut parameter = None;
            if kind == "positional" && !named_seen && position < positional.len() {
                parameter = Some(positional[position]);
                position += 1;
            } else if kind == "named" && matches!(language.as_str(), "python" | "csharp") {
                named_seen = true;
                parameter = names.get(&s(&argument.attrs, "name")?).copied();
                if let Some(p) = parameter
                    && s(&p.attrs, "kind")? == "positional_only"
                {
                    parameter = None;
                }
            }
            let Some(parameter) = parameter else {
                reason = "argument-shape";
                break;
            };
            if !bound.insert(parameter.object.clone()) {
                reason = "argument-shape";
                break;
            }
            pending.push((argument, parameter));
        }
        if reason.is_empty() {
            for p in &signature {
                if !bound.contains(&p.object) && !b(&p.attrs, "default")? {
                    reason = "missing-argument";
                    break;
                }
            }
        }
        g.add(
            &call,
            "BINDING_STATUS",
            if reason.is_empty() {
                "supported"
            } else {
                "unsupported"
            },
            &evidence,
            json!({"analysis":"explicit-arguments/1","reason":reason}),
        );
        if !reason.is_empty() {
            continue;
        }
        for (a, p) in pending {
            let position = n(&a.attrs, "position")?;
            let binding = format!("{call}/binding/{position}");
            g.add(&call,"CALL_BINDING",&binding,ev(a),json!({"position":position,"kind":v(&a.attrs,"kind")?,"name":a.attrs.get("name").map(|v|serde_json::from_str::<Value>(v.get())).transpose()?.unwrap_or(json!("")),"mode":"direct"}));
            g.add(&binding, "BINDING_PARAMETER", &p.object, ev(a), json!({}));
            g.add(&binding, "BINDING_VALUE", &a.object, ev(a), json!({}));
            g.add(&binding, "BINDING_TARGET", &target, ev(a), json!({}));
        }
    }
    Ok(())
}
