//! Lexical calls, declared contracts and possible instance targets remain distinct.
use super::*;
impl Project {
    pub(super) fn lexical_captures(&mut self) {
        for f in self.rows("OWNED_BY") {
            self.lexical.insert(f.subject, f.object);
        }
        let mut binding_owners = BTreeMap::new();
        for relation in ["DECLARES", "HAS_PARAMETER"] {
            for f in self.rows(relation) {
                binding_owners.insert(f.object, f.subject);
            }
        }
        for f in self.rows("READS") {
            if !self.positions.contains_key(&f.object)
                || (self.entity(&f.object).kind != "PARAMETER" && !self.flag(&f.object, "declared"))
            {
                continue;
            }
            let owner = binding_owners.get(&f.object).cloned().unwrap_or_default();
            if owner == f.subject
                || !self.positions.contains_key(&owner)
                || self.entity(&owner).kind != "CALLABLE"
            {
                continue;
            }
            let mut scope = self.lexical.get(&f.subject).cloned().unwrap_or_default();
            let mut seen = BTreeSet::new();
            while !scope.is_empty() && scope != owner && seen.insert(scope.clone()) {
                scope = self.lexical.get(&scope).cloned().unwrap_or_default();
            }
            if scope == owner {
                self.add(
                    &f.subject,
                    "CAPTURES",
                    &f.object,
                    f.evidence.first().map_or("", String::as_str),
                    json!({"model":"lexical-outer-binding"}),
                );
            }
        }
        for (_, e) in &self.graph.entities {
            if e.kind == "CALLABLE" {
                self.lexical_calls
                    .entry((
                        self.lexical.get(&e.id).cloned().unwrap_or_default(),
                        e.name.clone(),
                    ))
                    .or_default()
                    .push(e.id.clone());
            }
        }
    }
    fn execution(&self, call: &str) -> Value {
        self.entity(call)
            .attrs
            .get("execution")
            .map(|raw| serde_json::from_str(raw.get()).unwrap())
            .unwrap_or_else(|| "unknown".into())
    }
    fn call_edge(&mut self, call: &str, target: &str, certain: bool, basis: Option<&str>) {
        let ev = self.ev(call);
        let attrs = basis
            .map(|basis| json!({"basis":basis}))
            .unwrap_or_else(|| json!({}));
        self.add(
            call,
            if certain { "TARGET" } else { "MAY_TARGET" },
            target,
            &ev,
            attrs.clone(),
        );
        let mut attrs = attrs;
        attrs["execution"] = self.execution(call);
        self.add(
            &self.call_owner[call].clone(),
            if certain { "CALLS" } else { "MAY_CALLS" },
            target,
            &ev,
            attrs,
        );
    }
    pub(super) fn link_lexical_calls(&mut self) {
        let callees = self
            .callees
            .iter()
            .map(|(call, name)| (call.clone(), name.clone()))
            .collect::<Vec<_>>();
        for (call, name) in callees {
            if self.receivers.get(&call).is_some() || self.allocations.contains_key(&call) {
                continue;
            }
            let mut scope = self.call_owner[&call].clone();
            let mut candidates = Vec::new();
            let mut possible_import = false;
            let mut seen = BTreeSet::new();
            while !scope.is_empty() && seen.insert(scope.clone()) {
                if self
                    .bindings
                    .get(&(scope.clone(), name.clone()))
                    .into_iter()
                    .flatten()
                    .any(|id| {
                        self.entity(id).kind == "PARAMETER"
                            || (self.entity(id).kind == "STORAGE"
                                && (self.attr(id, "language") != "python"
                                    || self.flag(id, "declared")))
                    })
                {
                    break;
                }
                candidates = self
                    .lexical_calls
                    .get(&(scope.clone(), name.clone()))
                    .cloned()
                    .unwrap_or_default();
                if !candidates.is_empty() {
                    break;
                }
                scope = self.lexical.get(&scope).cloned().unwrap_or_else(|| {
                    scope
                        .rsplit_once('/')
                        .map(|(p, _)| p.to_owned())
                        .unwrap_or_default()
                });
            }
            let key = (self.entity(&call).path.clone(), name.clone());
            if candidates.is_empty() && scope.is_empty() {
                if let Some(imported) = self.imports.members.get(&key) {
                    candidates = self
                        .lexical_calls
                        .get(&(format!("{}::module", imported.0), imported.1.clone()))
                        .cloned()
                        .unwrap_or_default();
                } else if self.imports.ambiguous.contains(&key) {
                    possible_import = true;
                    candidates = self
                        .imports
                        .options
                        .get(&key)
                        .into_iter()
                        .flatten()
                        .flat_map(|(path, symbol)| {
                            self.lexical_calls
                                .get(&(format!("{path}::module"), symbol.clone()))
                                .into_iter()
                                .flatten()
                                .cloned()
                        })
                        .collect::<BTreeSet<_>>()
                        .into_iter()
                        .collect();
                }
            }
            let caller = self.call_owner[&call].clone();
            if let Some(instance_type) = self.owners.get(&caller).cloned().filter(|_| {
                !candidates.is_empty()
                    && self.positions.contains_key(&caller)
                    && self
                        .attr(&caller, "language")
                        .as_str()
                        .is_some_and(|l| matches!(l, "java" | "csharp" | "cpp"))
                    && !self.flag(&caller, "static")
            }) {
                let mut lineage = self.ancestors(&instance_type);
                lineage.insert(instance_type.clone());
                if candidates.iter().all(|target| {
                    self.owners
                        .get(target)
                        .is_some_and(|owner| lineage.contains(owner))
                        && !self.flag(target, "static")
                }) {
                    let receiver = format!("{instance_type}/THIS");
                    let ev = self.ev(&call);
                    self.add(
                        &instance_type,
                        "INSTANCE_RECEIVER",
                        &receiver,
                        &ev,
                        json!({"basis":"resolved-implicit-instance-member"}),
                    );
                    self.add(
                        &call,
                        "RECEIVER",
                        &receiver,
                        &ev,
                        json!({"basis":"resolved-implicit-instance-member"}),
                    );
                }
            }
            for target in &candidates {
                self.call_edge(
                    &call,
                    target,
                    candidates.len() == 1 && !possible_import,
                    None,
                );
            }
        }
    }
    fn external_functional_slot(
        &mut self,
        receiver: &str,
        call: &str,
        spellings: &BTreeMap<String, String>,
        arguments: &BTreeMap<String, Vec<Fact>>,
    ) -> Option<String> {
        if !self.positions.contains_key(receiver) || self.attr(receiver, "language") != "java" {
            return None;
        }
        let spelling = trim(spellings.get(receiver).map_or("", String::as_str));
        if spelling.is_empty() || self.resolve(spelling, receiver).is_some() {
            return None;
        }
        let mut scope = receiver.to_owned();
        let mut seen = BTreeSet::new();
        while !scope.is_empty() && seen.insert(scope.clone()) {
            if self.positions.contains_key(&scope)
                && self
                    .attr(&scope, "type_parameters")
                    .as_array()
                    .is_some_and(|v| v.iter().any(|v| v == spelling))
            {
                return None;
            }
            scope = self.lexical.get(&scope).cloned().unwrap_or_else(|| {
                scope
                    .rsplit_once('/')
                    .map(|(p, _)| p.into())
                    .unwrap_or_default()
            });
        }
        let imports = self
            .imports
            .java_imports
            .get(&(self.entity(receiver).path.clone(), spelling.into()));
        let qualified = if matches!(
            spelling,
            "java.util.function.IntSupplier" | "java.util.function.IntUnaryOperator"
        ) {
            spelling.to_owned()
        } else {
            imports
                .filter(|v| v.len() == 1)
                .and_then(|v| v.first())
                .cloned()
                .unwrap_or_default()
        };
        let (name, arity) = match qualified.as_str() {
            "java.util.function.IntSupplier" => ("getAsInt", 0),
            "java.util.function.IntUnaryOperator" => ("applyAsInt", 1),
            _ => return None,
        };
        if self.callees.get(&call.to_owned()).is_none_or(|n| n != name) {
            return None;
        }
        let args = arguments.get(call).map_or(&[][..], Vec::as_slice);
        if args.len() != arity || args.iter().any(|a| fact_attr(a, "kind") != "positional") {
            return None;
        }
        let path = format!("<model:{qualified}>");
        let contract = format!(
            "{path}::module/INTERFACE:{}",
            qualified.rsplit('.').next().unwrap()
        );
        let target = format!("{contract}/CALLABLE:{name}");
        if !self.positions.contains_key(&target) {
            let common =
                json!({"language":"java","external":true,"model":"java-functional-slots/1"});
            self.insert(Entity {
                id: contract.clone(),
                kind: "INTERFACE".into(),
                name: qualified.rsplit('.').next().unwrap().into(),
                path: path.clone(),
                line: 0,
                end_line: 0,
                attrs: attrs(common.clone()),
            });
            let mut method = common.clone();
            method["constructor"] = false.into();
            method["static"] = false.into();
            method["functional"] = true.into();
            method["arity"] = arity.into();
            method["return_type"] = "int".into();
            method["type"] = "unknown".into();
            self.insert(Entity {
                id: target.clone(),
                kind: "CALLABLE".into(),
                name: name.into(),
                path: path.clone(),
                line: 0,
                end_line: 0,
                attrs: attrs(method),
            });
            self.add(
                &contract,
                "HAS_METHOD",
                &target,
                "",
                json!({"basis":"external-api-contract"}),
            );
            self.add(
                &target,
                "IN_TYPE",
                &contract,
                "",
                json!({"basis":"external-api-contract"}),
            );
            self.add(
                &target,
                "OWNED_BY",
                &contract,
                "",
                json!({"basis":"external-api-contract"}),
            );
            for position in 0..arity {
                let parameter = format!("{target}/PARAMETER:operand");
                let mut metadata = common.clone();
                metadata["receiver"] = false.into();
                metadata["position"] = position.into();
                metadata["kind"] = "positional".into();
                metadata["type"] = "int".into();
                self.insert(Entity {
                    id: parameter.clone(),
                    kind: "PARAMETER".into(),
                    name: "operand".into(),
                    path: path.clone(),
                    line: 0,
                    end_line: 0,
                    attrs: attrs(metadata),
                });
                self.add(
                    &target,
                    "HAS_PARAMETER",
                    &parameter,
                    "",
                    json!({"position":position,"receiver":false,"kind":"positional"}),
                );
            }
        }
        self.add(
            receiver,
            "TYPE",
            &contract,
            "",
            json!({"basis":"external-api-contract"}),
        );
        Some(target)
    }
    pub(super) fn link_receivers(&mut self) {
        let spellings = self
            .rows("TYPE_NAME")
            .into_iter()
            .map(|f| (f.subject, f.object))
            .collect::<BTreeMap<_, _>>();
        let mut arguments = BTreeMap::<String, Vec<Fact>>::new();
        for f in self.rows("ARGUMENT") {
            arguments.entry(f.subject.clone()).or_default().push(f);
        }
        let accessors = self
            .graph
            .operations
            .iter()
            .filter(|op| {
                op.native_kind == "method_definition"
                    && op.kind == "FUNCTION"
                    && op.attrs.get("tokens").is_some_and(|raw| {
                        serde_json::from_str::<Value>(raw.get())
                            .ok()
                            .and_then(|v| v.as_array().cloned())
                            .is_some_and(|tokens| tokens.iter().any(|t| t == "get" || t == "set"))
                    })
            })
            .map(|op| op.owner.clone())
            .collect::<BTreeSet<_>>();
        let assignment_targets = self
            .rows("ASSIGNMENT_TARGET")
            .into_iter()
            .map(|f| f.object)
            .collect::<BTreeSet<_>>();
        let receivers = self
            .receivers
            .iter()
            .map(|(call, receiver)| (call.clone(), receiver.clone()))
            .collect::<Vec<_>>();
        for (call, receiver) in receivers {
            let imported = if self.positions.contains_key(&receiver)
                && self.entity(&receiver).kind == "STORAGE"
                && !self.flag(&receiver, "declared")
            {
                self.imports
                    .modules
                    .get(&(
                        self.entity(&receiver).path.clone(),
                        self.entity(&receiver).name.clone(),
                    ))
                    .cloned()
            } else {
                None
            };
            if let Some(modules) = imported.filter(|m| !m.is_empty()) {
                let name = self.callees.get(&call).cloned().unwrap_or_default();
                let candidates = modules
                    .into_iter()
                    .flat_map(|module| {
                        self.lexical_calls
                            .get(&(format!("{module}::module"), name.clone()))
                            .into_iter()
                            .flatten()
                            .cloned()
                    })
                    .collect::<BTreeSet<_>>();
                let certain = candidates.len() == 1
                    && !self.imports.ambiguous.contains(&(
                        self.entity(&receiver).path.clone(),
                        self.entity(&receiver).name.clone(),
                    ));
                for target in candidates {
                    self.call_edge(&call, &target, certain, Some("explicit-module-import"));
                }
                continue;
            }
            let language = self.attr(&receiver, "language");
            if self.types.contains(&receiver)
                && language.as_str().is_some_and(|l| {
                    matches!(
                        l,
                        "java" | "csharp" | "javascript" | "typescript" | "python"
                    )
                })
            {
                let name = self.callees.get(&call).cloned().unwrap_or_default();
                let methods = self
                    .methods
                    .get(&(receiver.clone(), name.clone()))
                    .cloned()
                    .unwrap_or_default();
                let shadowed = language
                    .as_str()
                    .is_some_and(|l| matches!(l, "javascript" | "typescript"))
                    && (self.fields.contains_key(&(receiver.clone(), name.clone()))
                        || methods.iter().any(|m| accessors.contains(m)));
                let mut targets = if shadowed {
                    Vec::new()
                } else {
                    methods
                        .into_iter()
                        .filter(|m| self.flag(m, "static") && !accessors.contains(m))
                        .collect::<Vec<_>>()
                };
                if language == "python" {
                    targets.retain(|m|matches!(self.attr(m,"decorators"),Value::Array(v)if v==vec![Value::String("@classmethod".into())]||v==vec![Value::String("@staticmethod".into())])&&!self.fields.contains_key(&(receiver.clone(),name.clone()))&&!assignment_targets.contains(m));
                }
                for target in &targets {
                    self.call_edge(
                        &call,
                        target,
                        targets.len() == 1,
                        Some("direct-class-static"),
                    );
                }
                continue;
            }
            if let Some(target) =
                self.external_functional_slot(&receiver, &call, &spellings, &arguments)
            {
                self.add(
                    &call,
                    "DECLARED_TARGET",
                    &target,
                    &self.ev(&call),
                    json!({"basis":"external-api-contract","model":"java-functional-slots/1"}),
                );
            }
            let possible = receiver
                .strip_suffix("/THIS")
                .map(|cls| [cls.into()].into_iter().collect::<BTreeSet<String>>())
                .unwrap_or_else(|| self.known.entry(receiver.clone()).or_default().clone());
            let name = self.callees.get(&call).cloned().unwrap_or_default();
            if let Some(declared) = self.declared.get(&receiver).cloned() {
                let mut slots = self
                    .methods
                    .get(&(declared.clone(), name.clone()))
                    .cloned()
                    .unwrap_or_default()
                    .into_iter()
                    .collect::<BTreeSet<_>>();
                if slots.is_empty() {
                    for base in self.ancestors(&declared) {
                        slots.extend(
                            self.methods
                                .get(&(base, name.clone()))
                                .into_iter()
                                .flatten()
                                .cloned(),
                        );
                    }
                }
                if slots.len() == 1 {
                    self.add(
                        &call,
                        "DECLARED_TARGET",
                        slots.first().unwrap(),
                        &self.ev(&call),
                        json!({"basis":"nominal-annotation"}),
                    );
                }
            }
            let mut targets = BTreeSet::new();
            for cls in &possible {
                let direct = self
                    .methods
                    .get(&(cls.clone(), name.clone()))
                    .cloned()
                    .unwrap_or_default();
                targets.extend(direct.iter().cloned());
                if direct.is_empty() {
                    for base in self.ancestors(cls) {
                        targets.extend(
                            self.methods
                                .get(&(base, name.clone()))
                                .into_iter()
                                .flatten()
                                .cloned(),
                        );
                    }
                }
            }
            for target in &targets {
                self.call_edge(&call, target, targets.len() == 1, None);
            }
            let caller = self.call_owner[&call].clone();
            for cls in possible {
                self.add(
                    &caller,
                    "DELEGATES_TYPE",
                    &cls,
                    &self.ev(&call),
                    json!({"name":name,"execution":self.execution(&call)}),
                );
            }
        }
    }
}
