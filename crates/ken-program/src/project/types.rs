//! Nominal type evidence and bounded possible-type propagation remain conservative.
use super::*;
impl Project {
    pub(super) fn link_types(&mut self) {
        let base_values = self
            .rows("BASE_VALUE")
            .into_iter()
            .map(|f| {
                let name = fact_attr(&f, "name").as_str().unwrap_or("").to_owned();
                ((f.subject, name), f.object)
            })
            .collect::<BTreeMap<_, _>>();
        for f in self.rows("BASE_NAME") {
            if let Some(binding) = base_values.get(&(f.subject.clone(), f.object.clone())) {
                let bound = self.entity(binding);
                if binding == &f.subject
                    || matches!(bound.kind.as_str(), "PARAMETER" | "CALLABLE")
                    || (bound.kind == "STORAGE" && self.flag(binding, "declared"))
                {
                    continue;
                }
                if matches!(bound.kind.as_str(), "CLASS" | "INTERFACE") {
                    self.add(
                        &f.subject,
                        "SUBTYPE_OF",
                        binding,
                        f.evidence.first().map_or("", String::as_str),
                        json!({}),
                    );
                    continue;
                }
            }
            let mut name = f.object.clone();
            if self
                .attr(&f.subject, "language")
                .as_str()
                .is_some_and(|s| matches!(s, "java" | "csharp" | "cpp" | "typescript"))
                && let Some(m) = full(r"([\w.$:]+)\s*<.+>", trim(&name))
            {
                name = m[1].into();
            }
            if let Some(target) = self.resolve(&name, &f.subject) {
                self.add(
                    &f.subject,
                    "SUBTYPE_OF",
                    &target,
                    f.evidence.first().map_or("", String::as_str),
                    json!({}),
                );
            }
        }
        let heads = self
            .rows("TYPE_HEAD")
            .into_iter()
            .map(|f| (f.subject, f.object))
            .collect::<BTreeMap<_, _>>();
        let opaque = self
            .rows("TYPE_HEAD_STATUS")
            .into_iter()
            .filter(|f| f.object == "unsupported")
            .map(|f| f.subject)
            .collect::<BTreeSet<_>>();
        for f in self.rows("TYPE_NAME") {
            let language = self.attr(&f.subject, "language");
            let denoted = if language == "rust" {
                resolution::rust_denoted(&f.object)
            } else {
                f.object.clone()
            };
            if self.positions.contains_key(&f.subject) {
                self.set(&f.subject, "type", resolution::normalized(&denoted).into());
            }
            let mut head = if denoted != f.object {
                denoted
            } else {
                heads.get(&f.subject).cloned().unwrap_or(denoted)
            };
            if language == "go"
                && let Some(m) = full(r"([\w.]+)\s*\[.+\]", trim(&head))
            {
                head = m[1].into();
            }
            if !opaque.contains(&f.subject)
                && let Some(target) = self.resolve(&head, &f.subject)
            {
                self.known
                    .entry(f.subject.clone())
                    .or_default()
                    .insert(target.clone());
                self.declared.insert(f.subject.clone(), target.clone());
                self.add(
                    &f.subject,
                    "TYPE",
                    &target,
                    f.evidence.first().map_or("", String::as_str),
                    json!({}),
                );
            }
            let mut element=regex(r"(?:list|List|Sequence|Collection|Iterable|Array|Vec|vector|IEnumerable|IList|Set)[<\[]\s*([\w]+)").captures(&f.object).map(|m|m[1].to_owned());
            if language == "go" {
                element =
                    full(r"\[\]\s*\*?\s*([A-Za-z_]\w*)", trim(&f.object)).map(|m| m[1].into());
            }
            if element.is_none()
                && language
                    .as_str()
                    .is_some_and(|l| matches!(l, "typescript" | "java" | "csharp"))
            {
                element = full(r"\s*([A-Za-z_$][\w.$]*)\s*\[\]\s*", &f.object).map(|m| m[1].into());
            }
            if let Some(target) = element.and_then(|name| self.resolve(&name, &f.subject)) {
                self.add(
                    &f.subject,
                    "ELEMENT_TYPE",
                    &target,
                    f.evidence.first().map_or("", String::as_str),
                    json!({}),
                );
            }
            let keyed = if language == "go" {
                full(r"map\s*\[\s*([\w.*]+?)\s*\]\s*([\w.*]+)", trim(&f.object))
            } else {
                full(
                    r"(?:Map|Dictionary|HashMap|map|dict)\s*<\s*([\w.$]+)\s*,\s*([\w.$]+)\s*>",
                    trim(&f.object),
                )
            };
            if let Some(m) = keyed {
                for (relation, spelling) in [("KEY_TYPE", &m[1]), ("VALUE_TYPE", &m[2])] {
                    if let Some(target) =
                        self.resolve(spelling.trim_matches([' ', '*', '&']), &f.subject)
                    {
                        self.add(
                            &f.subject,
                            relation,
                            &target,
                            f.evidence.first().map_or("", String::as_str),
                            json!({}),
                        );
                    }
                }
            }
        }
    }
    pub(super) fn link_methods(&mut self) {
        for f in self.rows("IN_TYPE") {
            self.owners.insert(f.subject, f.object);
        }
        for f in self.rows("HAS_METHOD") {
            let key = (f.subject, self.entity(&f.object).name.clone());
            if !self.methods.values.contains_key(&key) {
                self.methods.insert(key.clone(), Vec::new());
            }
            self.methods.values.get_mut(&key).unwrap().push(f.object);
        }
        for f in &self.graph.facts {
            if f.relation == "SUBTYPE_OF" {
                self.bases
                    .entry(f.subject.clone())
                    .or_default()
                    .insert(f.object.clone());
            }
        }
        let methods = self
            .methods
            .iter()
            .map(|(key, values)| (key.clone(), values.clone()))
            .collect::<Vec<_>>();
        for ((cls, name), implementations) in methods {
            if self.attr(&cls, "language") == "cpp" {
                continue;
            }
            for base in self.ancestors(&cls) {
                let originals = self
                    .methods
                    .get(&(base, name.clone()))
                    .cloned()
                    .unwrap_or_default();
                for implementation in &implementations {
                    for original in &originals {
                        self.add(
                            implementation,
                            "OVERRIDES",
                            original,
                            &self.ev(implementation),
                            json!({}),
                        );
                    }
                }
            }
        }
        self.cpp_overrides();
    }
    pub(super) fn allocate(&mut self) {
        for f in self.rows("CALLEE_NAME") {
            self.callees.insert(f.subject, f.object);
        }
        for f in self.rows("RECEIVER") {
            self.receivers.insert(f.subject, f.object);
        }
        for f in self.rows("HAS_CALL") {
            self.call_owner.insert(f.object, f.subject);
        }
        let callees = self
            .callees
            .iter()
            .map(|(call, name)| (call.clone(), name.clone()))
            .collect::<Vec<_>>();
        for (call, name) in callees {
            if self.receivers.get(&call).is_some() {
                continue;
            }
            if let Some(target) = self.resolve(&name, &call) {
                self.allocations.insert(call.clone(), target.clone());
                self.known
                    .entry(call.clone())
                    .or_default()
                    .insert(target.clone());
                let ev = self.ev(&call);
                self.add(&call, "ALLOCATES_TYPE", &target, &ev, json!({}));
                self.add(
                    &self.call_owner[&call].clone(),
                    "CREATES",
                    &target,
                    &ev,
                    json!({}),
                );
            }
        }
        for f in self.rows("HAS_FIELD") {
            self.fields
                .insert((f.subject, self.entity(&f.object).name.clone()), f.object);
        }
        let names = self
            .rows("FIELD_NAME")
            .into_iter()
            .map(|f| (f.subject, f.object))
            .collect::<BTreeMap<_, _>>();
        for f in self.rows("HAS_INITIALIZER") {
            if let Some(target) = self
                .fields
                .get(&(
                    self.allocations
                        .get(&f.subject)
                        .cloned()
                        .unwrap_or_default(),
                    names.get(&f.object).cloned().unwrap_or_default(),
                ))
                .cloned()
            {
                self.graph.relations.insert("INITIALIZES_FIELD".into());
                self.graph.facts.push(Fact {
                    subject: f.object,
                    relation: "INITIALIZES_FIELD".into(),
                    object: target,
                    attrs: f.attrs,
                    evidence: f.evidence.into_iter().take(1).collect(),
                });
            }
        }
    }
    pub(super) fn propagate(&mut self, check: &mut impl FnMut() -> Result<()>) -> Result<()> {
        let assignments = self.rows("ASSIGNED_FROM");
        let mut changed = false;
        for _ in 0..16 {
            check()?;
            changed = false;
            for f in &assignments {
                let incoming = self.known.entry(f.object.clone()).or_default().clone();
                let targets = self.known.entry(f.subject.clone()).or_default();
                let before = targets.len();
                targets.extend(incoming);
                changed |= targets.len() != before;
            }
            if !changed {
                break;
            }
        }
        if changed {
            self.graph
                .diagnostics
                .push("type propagation reached its 16-pass bound".into());
        }
        for (storage, targets) in self.known.clone() {
            for target in &targets {
                self.add(
                    &storage,
                    if targets.len() == 1 && !self.declared.contains_key(&storage) {
                        "TYPE"
                    } else {
                        "MAY_TYPE"
                    },
                    target,
                    "",
                    json!({}),
                );
            }
        }
        for f in assignments {
            if self.positions.contains_key(&f.subject)
                && self.positions.contains_key(&f.object)
                && !self.entity(&f.subject).attrs.contains_key("type")
            {
                let value = self
                    .entity(&f.object)
                    .attrs
                    .get("type")
                    .cloned()
                    .unwrap_or_else(|| to_raw_value("unknown").unwrap());
                let position = self.positions[&f.subject];
                self.graph.entities[position]
                    .1
                    .attrs
                    .insert("type".into(), value);
            }
        }
        for id in self
            .graph
            .entities
            .iter()
            .map(|(id, _)| id.clone())
            .collect::<Vec<_>>()
        {
            if !self.entity(&id).attrs.contains_key("type") {
                self.set(&id, "type", "unknown".into());
            }
            if self.entity(&id).kind == "CALLABLE" {
                if self.entity(&id).attrs.contains_key("return_type")
                    && !self.entity(&id).attrs.contains_key("native_return_type")
                {
                    let value = self.attr(&id, "return_type");
                    self.set(&id, "native_return_type", value);
                }
                let annotation = self.attr(&id, "return_type");
                self.set(
                    &id,
                    "return_type",
                    resolution::normalized(annotation.as_str().unwrap_or("")).into(),
                );
            }
        }
        Ok(())
    }
}
