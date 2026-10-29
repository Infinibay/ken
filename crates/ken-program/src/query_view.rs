//! Query occurrences and coverage derived without changing source semantics.
use crate::{Attributes, Entity, Fact, ProgramError, StructuralIr, value::GraphValue};
use serde_json::value::RawValue;
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, ProgramError>;
fn val(a: &Attributes, k: &str) -> Result<GraphValue> {
    a.get(k)
        .map_or(Ok(GraphValue::Null), |v| GraphValue::parse(v))
}
fn text(a: &Attributes, k: &str, default: &str) -> Result<String> {
    Ok(if a.contains_key(k) {
        {
            let v = val(a, k)?;
            v.string().unwrap_or_else(|| v.repr())
        }
    } else {
        default.into()
    })
}
fn raw(v: impl serde::Serialize) -> Result<Box<RawValue>> {
    Ok(serde_json::value::to_raw_value(&v)?)
}
fn set(a: &mut Attributes, k: &str, v: impl serde::Serialize) -> Result<()> {
    a.insert(k.into(), raw(v)?);
    Ok(())
}
fn copy(a: &mut Attributes, k: &str, source: &Attributes, key: &str, default: &str) -> Result<()> {
    a.insert(
        k.into(),
        source
            .get(key)
            .cloned()
            .unwrap_or(RawValue::from_string(default.into())?),
    );
    Ok(())
}
fn family(a: &Attributes, k: &str) -> Result<Box<RawValue>> {
    let Some(value) = a.get(k) else {
        return raw("unknown");
    };
    let v = GraphValue::parse(value)?;
    if let Some(name) = v.string() {
        return match name.as_str() {
            "str" | "string" | "String" => raw("string"),
            "int" => raw("integer"),
            "bool" | "boolean" => raw("boolean"),
            _ => Ok(value.clone()),
        };
    }
    if matches!(
        v,
        GraphValue::List(_) | GraphValue::Dict(_) | GraphValue::Set(_)
    ) {
        return Err(ProgramError::Invalid("unhashable type family"));
    }
    Ok(value.clone())
}
fn state(a: &Attributes, native: &str, kind: &str) -> Result<&'static str> {
    Ok(
        if val(a, native)?.truthy() || text(a, kind, "unknown")? != "unknown" {
            "known"
        } else {
            "unknown"
        },
    )
}
fn position(a: &Attributes) -> Result<String> {
    let v = a
        .get("position")
        .map_or(Ok(GraphValue::Int("0".into())), |r| GraphValue::parse(r))?;
    Ok(match v {
        GraphValue::Bool(v) => format!("number:{}", u8::from(v)),
        GraphValue::Int(v) => format!("number:{v}"),
        GraphValue::Float(v) if v.is_finite() && v.fract() == 0. => format!(
            "number:{}",
            if v == 0. {
                "0".into()
            } else {
                format!("{v:.0}")
            }
        ),
        GraphValue::Float(v) => format!("number:{}", crate::value::float_hex(v)),
        GraphValue::String(v) => format!("str:{}", crate::value::string_repr(&v)),
        GraphValue::Null => "null".into(),
        _ => return Err(ProgramError::Invalid("unhashable argument position")),
    })
}
struct Query<'a> {
    source: &'a StructuralIr,
    graph: StructuralIr,
    entities: BTreeMap<&'a str, &'a Entity>,
    positions: BTreeMap<String, usize>,
    results: BTreeMap<String, String>,
    stored: BTreeMap<&'a str, Vec<&'a str>>,
    origins: BTreeMap<(String, String, String), &'a Fact>,
}
impl Query<'_> {
    fn add(&mut self, s: &str, r: &str, o: &str, e: &[String], attrs: Attributes) {
        self.graph.relations.insert(r.into());
        self.graph.facts.push(Fact {
            subject: s.into(),
            relation: r.into(),
            object: o.into(),
            attrs,
            evidence: e
                .first()
                .filter(|s| !s.is_empty())
                .cloned()
                .into_iter()
                .collect(),
        });
    }
    fn entity(&mut self, e: Entity) {
        if let Some(&i) = self.positions.get(&e.id) {
            self.graph.entities[i] = (e.id.clone(), e);
        } else {
            self.positions
                .insert(e.id.clone(), self.graph.entities.len());
            self.graph.entities.push((e.id.clone(), e));
        }
    }
    fn as_value(
        &mut self,
        source: &str,
        occurrence: &str,
        evidence: &[String],
        consumer: Option<(&str, String)>,
    ) -> Result<String> {
        if let Some(v) = self.results.get(source) {
            return Ok(v.clone());
        }
        let Some(e) = self
            .entities
            .get(source)
            .copied()
            .filter(|e| matches!(e.kind.as_str(), "STORAGE" | "PARAMETER"))
        else {
            return Ok(source.into());
        };
        let id = format!("{occurrence}/loaded-value");
        let mut attrs = Attributes::new();
        set(&mut attrs, "origin", "load")?;
        set(&mut attrs, "storage", source)?;
        self.entity(Entity {
            id: id.clone(),
            kind: "VALUE".into(),
            name: e.name.clone(),
            path: e.path.clone(),
            line: e.line,
            end_line: e.end_line,
            attrs,
        });
        let mut attrs = Attributes::new();
        copy(&mut attrs, "type", &e.attrs, "type", "\"unknown\"")?;
        self.add(&id, "ENTITY", "VALUE", evidence, attrs);
        self.add(&id, "LOADED_FROM", source, evidence, Attributes::new());
        let origin = consumer.and_then(|(call, pos)| {
            self.origins
                .get(&(call.into(), source.into(), pos))
                .copied()
        });
        let mut live = BTreeSet::new();
        if let Some(f) = origin
            && let GraphValue::List(items) | GraphValue::Tuple(items) | GraphValue::Set(items) =
                val(&f.attrs, "origins")?
        {
            for v in items {
                if let Some(s) = v.string() {
                    live.insert(s);
                }
            }
        }
        let mut incoming = live.clone();
        incoming.extend(
            self.stored
                .get(source)
                .into_iter()
                .flatten()
                .map(|s| s.to_string()),
        );
        for from in incoming {
            if let Some(result) = self.results.get(&from).cloned() {
                let must = origin.is_some_and(|f| {
                    text(&f.attrs, "modality", "").ok().as_deref() == Some("must")
                }) && live.contains(&from);
                let mut attrs = Attributes::new();
                set(&mut attrs, "modality", if must { "must" } else { "may" })?;
                self.add(&result, "VALUE_FLOW", &id, evidence, attrs);
            }
        }
        Ok(id)
    }
}
pub fn normalize_query_graph(ir: &StructuralIr) -> Result<StructuralIr> {
    if ir.view == "query" {
        return Ok(ir.clone());
    }
    let entities = ir
        .entities
        .iter()
        .map(|(_, e)| (e.id.as_str(), e))
        .collect();
    let positions = ir
        .entities
        .iter()
        .enumerate()
        .map(|(i, (k, _))| (k.clone(), i))
        .collect();
    let mut q = Query {
        source: ir,
        graph: ir.clone(),
        entities,
        positions,
        results: BTreeMap::new(),
        stored: BTreeMap::new(),
        origins: BTreeMap::new(),
    };
    q.graph.view = "query".into();
    q.graph.facts.clear();
    let mut methods = BTreeSet::new();
    let mut arities: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    let mut generators = BTreeSet::new();
    let mut supported = BTreeSet::new();
    let mut overrides: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    let mut overridden: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    for f in &ir.facts {
        match f.relation.as_str() {
            "HAS_METHOD" => {
                methods.insert(f.object.as_str());
            }
            "HAS_PARAMETER" if !val(&f.attrs, "receiver")?.truthy() => {
                arities.entry(&f.subject).or_default().insert(&f.object);
            }
            "HAS_YIELD" => {
                generators.insert(f.subject.as_str());
            }
            "RETURN_FLOW_STATUS" if f.object == "supported" => {
                supported.insert(f.subject.as_str());
            }
            "ASSIGNED_FROM" => q.stored.entry(&f.subject).or_default().push(&f.object),
            "ARGUMENT_ORIGIN" => {
                q.origins.insert(
                    (f.subject.clone(), f.object.clone(), position(&f.attrs)?),
                    f,
                );
            }
            "OVERRIDES" => {
                overrides.entry(&f.object).or_default().insert(&f.subject);
                overridden.entry(&f.subject).or_default().insert(&f.object);
            }
            _ => (),
        }
    }
    for (_, e) in &mut q.graph.entities {
        if e.kind == "CALL"
            && let Some(name) = e.attrs.get("name")
        {
            e.name = GraphValue::parse(name)?
                .string()
                .ok_or(ProgramError::Invalid("call name must be a string"))?;
        }
    }
    for (_, e) in &ir.entities {
        if ir.diagnostics.is_empty() && e.kind == "CALLABLE" {
            q.graph
                .capabilities
                .insert(format!("complete:{}:HAS_CALL", e.id));
            if text(&e.attrs, "language", "")? == "python" {
                q.graph
                    .capabilities
                    .insert(format!("complete:{}:HAS_PARAMETER", e.id));
            }
        }
        if e.kind == "CALL" {
            q.results.insert(e.id.clone(), format!("{}/result", e.id));
        }
    }
    for (call, id) in q.results.clone() {
        let e = q.entities[call.as_str()];
        let mut attrs = Attributes::new();
        set(&mut attrs, "origin", &call)?;
        q.entity(Entity {
            id: id.clone(),
            kind: "VALUE".into(),
            name: String::new(),
            path: e.path.clone(),
            line: e.line,
            end_line: e.end_line,
            attrs,
        });
        q.add(&id, "ENTITY", "VALUE", &[], Attributes::new());
        q.add(&call, "RESULT", &id, &[], Attributes::new());
    }
    for f in &ir.facts {
        if f.relation == "ARGUMENT" {
            let p = position(&f.attrs)?;
            let aid = format!(
                "{}/argument/{}",
                f.subject,
                text(&f.attrs, "position", "0")?
            );
            q.add(&f.subject, "ARGUMENT", &aid, &f.evidence, Attributes::new());
            let v = q.as_value(&f.object, &aid, &f.evidence, Some((&f.subject, p)))?;
            q.add(&aid, "VALUE", &v, &f.evidence, Attributes::new());
            let empty = Attributes::new();
            let source = q
                .entities
                .get(f.object.as_str())
                .map_or(&empty, |e| &e.attrs);
            let mut attrs = f.attrs.clone();
            copy(&mut attrs, "type", source, "type", "\"unknown\"")?;
            attrs.insert("type_family".into(), family(source, "type")?);
            set(
                &mut attrs,
                "type_state",
                state(source, "native_type", "type")?,
            )?;
            q.add(&aid, "ENTITY", "ARGUMENT", &f.evidence, attrs);
            continue;
        }
        let mut fact = f.clone();
        if f.relation == "ENTITY" {
            let a = &mut fact.attrs;
            a.insert("type_family".into(), family(&f.attrs, "type")?);
            set(a, "type_state", state(&f.attrs, "native_type", "type")?)?;
            a.insert("return_family".into(), family(&f.attrs, "return_type")?);
            set(
                a,
                "return_type_state",
                state(&f.attrs, "native_return_type", "return_type")?,
            )?;
            copy(
                a,
                "position",
                &f.attrs,
                if f.attrs.contains_key("pos") {
                    "pos"
                } else {
                    "position"
                },
                "null",
            )?;
            if let Some(v) = f.attrs.get("parameter_kind") {
                a.insert("kind".into(), v.clone());
            } else {
                set(a, "kind", f.object.to_lowercase())?;
            }
            set(a, "method", methods.contains(f.subject.as_str()))?;
            let generator = val(&f.attrs, "generator")?;
            if generator.truthy() {
                a.insert("generator".into(), generator.to_raw()?);
            } else {
                set(a, "generator", generators.contains(f.subject.as_str()))?;
            }
            copy(a, "async", &f.attrs, "async_", "false")?;
            set(
                a,
                "arity",
                ir.diagnostics
                    .is_empty()
                    .then(|| arities.get(f.subject.as_str()).map_or(0, BTreeSet::len)),
            )?;
            if let Some(e) = q.entities.get(f.subject.as_str()) {
                set(a, "path", &e.path)?;
                if e.kind == "CALL" {
                    copy(
                        a,
                        "name",
                        &e.attrs,
                        "name",
                        &serde_json::to_string(&e.name)?,
                    )?;
                }
            }
        } else if f.relation == "OPERATION" {
            let mut kind = text(&f.attrs, "kind", &f.object)?.to_lowercase();
            if kind == "yield" && val(&f.attrs, "delegated")?.truthy() {
                kind = "yield_delegate".into();
            }
            if kind == "yield"
                && matches!(val(&f.attrs,"tokens")?,GraphValue::List(v)if v.iter().any(|x|x.string().as_deref()==Some("break")))
            {
                kind = "generator_stop".into();
            }
            set(&mut fact.attrs, "kind", kind)?;
        }
        q.graph.facts.push(fact);
        match f.relation.as_str() {
            "ALLOCATES_TYPE" => {
                let s = q.results.get(&f.subject).unwrap_or(&f.subject).clone();
                q.add(&s, "INSTANCE_OF", &f.object, &f.evidence, Attributes::new());
            }
            "RETURNS" | "ASSIGNED_FROM"
                if f.relation != "RETURNS" || !supported.contains(f.subject.as_str()) =>
            {
                let v = q.as_value(
                    &f.object,
                    &format!("{}/{}/{}", f.subject, f.relation, f.object),
                    &f.evidence,
                    None,
                )?;
                let mut attrs = Attributes::new();
                if f.relation == "RETURNS" {
                    set(&mut attrs, "basis", "syntax")?;
                }
                q.add(
                    &f.subject,
                    if f.relation == "RETURNS" {
                        "RETURNS_VALUE"
                    } else {
                        "STORES_VALUE"
                    },
                    &v,
                    &f.evidence,
                    attrs,
                );
            }
            "FLOWS_TO" => {
                if let (Some(s), Some(o)) = (
                    q.results.get(&f.subject).cloned(),
                    q.results.get(&f.object).cloned(),
                ) {
                    let mut attrs = Attributes::new();
                    set(&mut attrs, "modality", "may")?;
                    q.add(&s, "VALUE_FLOW", &o, &f.evidence, attrs);
                }
            }
            _ => (),
        }
    }
    for f in &ir.facts {
        if f.relation == "CALLS" {
            q.add(
                &f.subject,
                "POSSIBLE_CALL",
                &f.object,
                &f.evidence,
                f.attrs.clone(),
            );
            for implementation in overrides.get(f.object.as_str()).into_iter().flatten() {
                q.add(
                    &f.subject,
                    "POSSIBLE_CALL",
                    implementation,
                    &f.evidence,
                    f.attrs.clone(),
                );
            }
        }
    }
    for f in &ir.facts {
        if f.relation == "DELEGATES_TO" && val(&f.attrs, "name")?.truthy() {
            for slot in overridden.get(f.subject.as_str()).into_iter().flatten() {
                if let Some(e) = q.entities.get(*slot)
                    && text(&e.attrs, "name", &e.name)? == text(&f.attrs, "name", "")?
                {
                    q.add(
                        &f.subject,
                        "FORWARDS_SLOT",
                        slot,
                        &f.evidence,
                        f.attrs.clone(),
                    );
                }
            }
        }
    }
    let returns: BTreeMap<_, _> = q
        .source
        .operations
        .iter()
        .filter(|o| o.kind == "RETURN")
        .map(|o| (o.id.as_str(), o))
        .collect();
    for f in &ir.facts {
        if f.relation == "RETURN_ORIGIN"
            && let Some(op) = returns
                .get(f.subject.as_str())
                .filter(|o| supported.contains(o.owner.as_str()))
        {
            let v = q.as_value(
                &f.object,
                &format!("{}/return-origin/{}", f.subject, f.object),
                &f.evidence,
                None,
            )?;
            let mut attrs = f.attrs.clone();
            set(&mut attrs, "basis", "flow")?;
            set(&mut attrs, "return_operation", &op.id)?;
            q.add(&op.owner, "RETURNS_VALUE", &v, &f.evidence, attrs);
        }
    }
    Ok(q.graph)
}
