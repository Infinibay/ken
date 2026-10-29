//! Return/argument summaries, declaration defaults and selector publication.
use super::*;
// Numeric positions use Python equality, including bool/int/float equivalence.
// An exact dyadic key avoids rounding large integer positions through f64.
#[derive(Eq, PartialEq, Ord, PartialOrd)]
enum PositionKey {
    Number(bool, u64, i32),
    Other(String),
}
impl PositionKey {
    fn number(negative: bool, mantissa: u64, exponent: i32) -> Self {
        if mantissa == 0 {
            return Self::Number(false, 0, 0);
        }
        let zeros = mantissa.trailing_zeros();
        Self::Number(negative, mantissa >> zeros, exponent + zeros as i32)
    }
    fn new(value: Value) -> Self {
        match value {
            Value::Bool(v) => Self::number(false, u64::from(v), 0),
            Value::Number(ref n) => {
                if let Some(i) = n.as_i64() {
                    return Self::number(i < 0, i.unsigned_abs(), 0);
                }
                if let Some(i) = n.as_u64() {
                    return Self::number(false, i, 0);
                }
                if let Some(f) = n.as_f64() {
                    let bits = f.to_bits();
                    let stored = ((bits >> 52) & 0x7ff) as i32;
                    let fraction = bits & ((1u64 << 52) - 1);
                    let (mantissa, exponent) = if stored == 0 {
                        (fraction, -1074)
                    } else {
                        (fraction | (1u64 << 52), stored - 1023 - 52)
                    };
                    return Self::number(bits >> 63 != 0, mantissa, exponent);
                }
                Self::Other(value.to_string())
            }
            _ => Self::Other(value.to_string()),
        }
    }
}
pub(super) fn return_and_arguments(
    g: &mut Graph,
    precise: &crate::control::ReturnOrigins,
) -> Result<()> {
    let assigned = g.sets("ASSIGNED_FROM");
    let allocations = g.map("ALLOCATES_TYPE");
    let owners = g.map("IN_TYPE");
    let callees = g.map("CALLEE_NAME");
    for f in g.rows("RETURNS") {
        let execution = v(&f.attrs, "execution")?;
        let execution = if f.attrs.contains_key("execution") {
            execution
        } else {
            json!("unknown")
        };
        if g.get(&f.object).is_some_and(|e| e.kind == "STORAGE") {
            g.add(
                &f.subject,
                "RETURNS_STORAGE",
                &f.object,
                ev(&f),
                json!({"execution":execution}),
            );
        }
        let origins = precise.get(&(f.subject.clone(), f.object.clone()));
        let mut values = origins
            .cloned()
            .unwrap_or_else(|| [f.object.clone()].into());
        let mut todo = if origins.is_some() {
            vec![]
        } else {
            vec![f.object.clone()]
        };
        while !todo.is_empty() && values.len() <= 256 {
            let current = todo.pop().unwrap();
            for value in set(&assigned, &current) {
                if values.insert(value.clone()) {
                    todo.push(value);
                }
            }
        }
        for value in values {
            if let Some(unit) = allocations.get(&value) {
                let mut a = json!({"execution":execution});
                if origins.is_some_and(|x| x.len() > 1) {
                    a["modality"] = "may".into();
                    a["basis"] = "flow".into();
                }
                g.add(&f.subject, "RETURNS_NEW", unit, ev(&f), a.clone());
                if owners.get(&f.subject) == Some(unit) {
                    g.add(&f.subject, "RETURNS_NEW_SELF", unit, ev(&f), a);
                }
            }
        }
        if callees.contains_key(&f.object) {
            g.add(
                &f.subject,
                "RETURNS_CALL",
                &f.object,
                ev(&f),
                json!({"execution":execution}),
            );
        }
    }
    let calls = g.map("TARGET");
    let mut params = BTreeMap::<_, Vec<_>>::new();
    for f in g.rows("HAS_PARAMETER") {
        if !b(&f.attrs, "receiver")? {
            params.entry(f.subject.clone()).or_default().push(f);
        }
    }
    let mut by_position = BTreeMap::<(String, PositionKey), Vec<usize>>::new();
    let mut by_name = BTreeMap::<(String, String), Vec<usize>>::new();
    for (target, parameters) in &params {
        for (i, parameter) in parameters.iter().enumerate() {
            by_position
                .entry((
                    target.clone(),
                    PositionKey::new(v(&parameter.attrs, "position")?),
                ))
                .or_default()
                .push(i);
            by_name
                .entry((target.clone(), g.e(&parameter.object)?.name.clone()))
                .or_default()
                .push(i);
        }
    }
    let returns = g.groups("RETURNS");
    let args = g.groups("ARGUMENT");
    for (call, target) in calls {
        let parameters = params.get(&target).map_or(&[][..], Vec::as_slice);
        for arg in args.get(&call).into_iter().flatten() {
            let kind = s(&arg.attrs, "kind")?;
            if kind.starts_with("spread") {
                // A spread really has one possible edge per parameter occurrence.
                for parameter in parameters {
                    g.add(
                        &arg.object,
                        "MAY_BIND_TO",
                        &parameter.object,
                        ev(arg),
                        json!({}),
                    );
                }
                continue;
            }
            let matched = if kind == "positional" {
                by_position.get(&(target.clone(), PositionKey::new(v(&arg.attrs, "position")?)))
            } else if kind == "named" {
                by_name.get(&(target.clone(), s(&arg.attrs, "name")?))
            } else {
                None
            };
            for &i in matched.into_iter().flatten() {
                let parameter = &parameters[i];
                g.add(
                    &arg.object,
                    "BINDS_TO",
                    &parameter.object,
                    ev(arg),
                    json!({}),
                );
                g.add(
                    &arg.object,
                    "FLOWS_TO",
                    &parameter.object,
                    ev(arg),
                    json!({}),
                );
            }
        }
        for f in returns.get(&target).into_iter().flatten() {
            g.add(&f.object, "FLOWS_TO", &call, "", json!({}));
        }
    }
    Ok(())
}
pub(super) fn field_defaults(g: &mut Graph) -> Result<()> {
    let declarations = g.groups("FIELD_DECLARATION");
    let values = g.map("ASSIGNMENT_VALUE");
    let declared = g.map("TYPE");
    for (slot, entries) in declarations {
        let entity = g.e(&slot)?.clone();
        let f = &entries[0];
        let mode = s(&f.attrs, "initialization")?;
        let (mut status, mut reason) = ("supported", "");
        let mut value = None;
        if entries.len() != 1
            || !g.ir.diagnostics.is_empty()
            || s(&f.attrs, "syntax_status")? != "supported"
        {
            status = "unsupported";
            reason = "ambiguous-or-invalid-declaration";
        } else if mode == "absent" {
            status = "absent";
            reason = "no-runtime-initializer";
        } else if mode == "explicit" {
            value = values.get(&f.object).cloned();
            if value.is_none() {
                status = "unsupported";
                reason = "unmodeled-initializer";
            }
        } else {
            let language = s(&entity.attrs, "language")?;
            let native = s(&f.attrs, "native_type")?;
            let native = trim(&native);
            let mut primitive = "";
            let mut literal = json!(0);
            match language.as_str() {
                "javascript" => value = Some("UNDEFINED".into()),
                "typescript" => reason = "typescript-field-emit-policy",
                "java" | "csharp" => {
                    if language == "java" {
                        if !native.is_empty()
                            && !matches!(
                                native,
                                "byte"
                                    | "short"
                                    | "int"
                                    | "long"
                                    | "float"
                                    | "double"
                                    | "boolean"
                                    | "char"
                                    | "var"
                                    | "void"
                                    | "unknown"
                            )
                        {
                            value = Some("NULL".into());
                        }
                    } else {
                        let base = native.strip_suffix('?').unwrap_or(native);
                        let target = g.get(lookup(&declared, &slot));
                        let parameters = v(&f.attrs, "type_parameters")?;
                        let bound = parameters
                            .as_array()
                            .is_some_and(|v| v.iter().any(|x| x == base));
                        let known = if let Some(t) = target {
                            !bound
                                && matches!(
                                    s(&t.attrs, "native_kind")?.as_str(),
                                    "class_declaration" | "interface_declaration"
                                )
                        } else {
                            false
                        };
                        let primitives = [
                            "byte", "sbyte", "short", "ushort", "int", "uint", "long", "ulong",
                            "nint", "nuint", "float", "double", "decimal", "bool", "char",
                        ];
                        if matches!(base, "string" | "object" | "dynamic")
                            || full(r".+\[[,\s]*\]", base).is_some()
                            || (native.ends_with('?') && primitives.contains(&base))
                            || known
                        {
                            value = Some("NULL".into());
                        }
                    }
                    if value.is_none() {
                        match native {
                            "boolean" | "bool" => {
                                primitive = "bool";
                                literal = false.into();
                            }
                            "char" => {
                                primitive = "char";
                                literal = "\0".into();
                            }
                            "float" | "double" | "decimal" => {
                                primitive = "float";
                                literal = json!(0.0);
                            }
                            "byte" | "sbyte" | "short" | "ushort" | "int" | "uint" | "long"
                            | "ulong" | "nint" | "nuint" => primitive = "int",
                            _ => {}
                        }
                        if !primitive.is_empty() {
                            let id = format!("{slot}/FIELD_DEFAULT");
                            g.insert(Entity{id:id.clone(),kind:"VALUE".into(),name:"default".into(),path:entity.path.clone(),line:entity.line,end_line:entity.end_line,attrs:attrs(json!({"language":language,"type":primitive,"literal_value":literal,"basis":"language-field-default","synthetic":true}))});
                            value = Some(id);
                        } else {
                            reason = "unresolved-field-default";
                        }
                    }
                }
                _ => reason = "unsupported-language",
            }
            if value.is_none() {
                status = "unsupported";
            }
        }
        g.add(
            &slot,
            "FIELD_INITIAL_STATUS",
            status,
            ev(f),
            json!({"reason":reason,"initialization":mode}),
        );
        if status == "supported"
            && let Some(value) = value
        {
            g.add(&slot,"FIELD_INITIAL_VALUE",&value,ev(f),json!({"basis":if mode=="explicit"{"explicit-field-initializer"}else{"language-field-default"},"declaration":f.object,"phase":"declaration"}));
        }
    }
    Ok(())
}
pub(super) fn selector_and_dispatch(g: &mut Graph) -> Result<()> {
    for f in g.rows("HAS_PARAMETER") {
        g.set(&f.object, "pos", v(&f.attrs, "position")?)?;
        g.set(&f.object, "parameter_kind", v(&f.attrs, "kind")?)?;
    }
    let mut bases = SetMap::new();
    for f in g.rows("SUBTYPE_OF") {
        if g.get(&f.object)
            .is_some_and(|e| matches!(e.kind.as_str(), "CLASS" | "STRUCT"))
        {
            bases.entry(f.subject).or_default().insert(f.object);
        }
    }
    let names = g.sets("BASE_NAME");
    let methods = g.groups("HAS_METHOD");
    let mut selected = BTreeSet::new();
    for id in g.ids() {
        let e = g.e(&id)?;
        if e.kind == "CALL" && b(&e.attrs, "base_dispatch_owner")? {
            selected.insert(id);
        }
    }
    g.ir.facts.retain(|f| {
        !(selected.contains(&f.subject)
            && matches!(
                f.relation.as_str(),
                "TARGET" | "DECLARED_TARGET" | "MAY_TARGET"
            ))
    });
    g.reindex();
    for id in selected {
        let e = g.e(&id)?.clone();
        let mut owner = s(&e.attrs, "base_dispatch_owner")?;
        let mut seen = BTreeSet::new();
        let mut target = None;
        while seen.len() < 32 && seen.insert(owner.clone()) {
            let bs = set(&bases, &owner);
            if bs.len() != 1
                || (s(&e.attrs, "language")? == "python" && set(&names, &owner).len() != 1)
            {
                break;
            }
            owner = bs.into_iter().next().unwrap();
            let mut candidates = vec![];
            for f in methods.get(&owner).into_iter().flatten() {
                if g.e(&f.object)?.name == s(&e.attrs, "name")? {
                    candidates.push(f.object.clone());
                }
            }
            if !candidates.is_empty() {
                if candidates.len() == 1 && !b(&g.e(&candidates[0])?.attrs, "static")? {
                    target = Some(candidates[0].clone());
                }
                break;
            }
        }
        g.set(
            &id,
            "resolution",
            if target.is_some() {
                "resolved"
            } else {
                "unresolved"
            }
            .into(),
        )?;
        if let Some(t) = target {
            g.add(
                &id,
                "TARGET",
                &t,
                "",
                json!({"basis":"lexical-base-dispatch"}),
            );
        }
    }
    let bases = g
        .rows("SUBTYPE_OF")
        .into_iter()
        .chain(g.rows("BASE_NAME"))
        .map(|f| f.subject)
        .collect::<BTreeSet<_>>();
    let declarations =
        g.ir.operations
            .iter()
            .filter(|o| o.kind == "FUNCTION")
            .map(|o| (o.owner.clone(), o.clone()))
            .collect::<BTreeMap<_, _>>();
    for id in g.ids() {
        let e = g.e(&id)?;
        if e.kind != "INTERFACE" || s(&e.attrs, "language")? != "java" || bases.contains(&id) {
            continue;
        }
        let mut candidates = vec![];
        for f in methods.get(&id).into_iter().flatten() {
            let m = g.e(&f.object)?;
            if b(&m.attrs, "static")?
                || s(&m.attrs, "visibility")? == "private"
                || matches!(m.name.as_str(), "equals" | "hashCode" | "toString")
            {
                continue;
            }
            if let Some(o) = declarations.get(&m.id)
                && tokens(o)?.iter().any(|t| t == ";")
            {
                candidates.push(m.id.clone());
            }
        }
        if candidates.len() == 1 {
            g.set(&candidates[0], "functional", true.into())?;
            g.set(
                &candidates[0],
                "functional_basis",
                "direct-java-single-abstract-method".into(),
            )?;
        }
    }
    Ok(())
}
pub(super) fn publish(g: &mut Graph) -> Result<()> {
    let arguments = g.groups("ARGUMENT");
    for id in g.ids() {
        let e = g.e(&id)?;
        if e.kind == "CALL" && g.ir.diagnostics.is_empty() {
            g.set(
                &id,
                "explicit_arguments",
                json!(arguments.get(&id).map_or(0, Vec::len)),
            )?;
        }
        let e = g.e(&id)?;
        let mut a = e.attrs.clone();
        a.insert("name".into(), to_raw_value(&e.name)?);
        let kind = e.kind.clone();
        let evidence = g.evidence(&id)?;
        g.add_raw(&id, "ENTITY", &kind, &evidence, a);
    }
    for o in g.ir.operations.clone() {
        let mut a = o.attrs.clone();
        a.extend(attrs(json!({"kind":o.kind,"native_kind":o.native_kind,"owner":o.owner,"role":o.role,"start_byte":o.start,"end_byte":o.end})));
        let evidence = format!("{}:{}", g.e(&o.owner)?.path, o.line);
        g.add_raw(&o.id, "OPERATION", &o.kind, &evidence, a);
        g.add(&o.owner,"HAS_OPERATION",&o.id,"",json!({"execution":o.attrs.get("execution").map(|v|serde_json::from_str::<Value>(v.get())).transpose()?.unwrap_or(json!("unknown"))}));
    }
    if g.ir.diagnostics.is_empty() {
        g.ir.capabilities.insert("resolved_types".into());
    }
    Ok(())
}
