use super::*;
use context::*;
use ken_program::Operation;
impl Context<'_> {
    pub fn initializer_prefix(
        &mut self,
        statements: &[Clause],
        bindings: &Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let owner = self.owner.local_id.clone();
        if self
            .entity(&owner, s)?
            .is_some_and(|e| !attr(&e.attrs, "constructor").is_ok_and(|v| v.truthy()))
        {
            return Ok(truth(false));
        }
        let initializers = self.rows("HAS_INITIALIZER", Some(&owner), None, s)?;
        let parameters = self.ids("HAS_PARAMETER", &owner, s)?;
        let mut copies = BTreeSet::new();
        for initializer in &initializers {
            for argument in self.rows("INITIALIZER_ARGUMENT", Some(&initializer.object), None, s)? {
                if !self
                    .ids("MEMBER_OF", &argument.object, s)?
                    .is_disjoint(&parameters)
                {
                    copies.insert(initializer.object.clone());
                }
            }
        }
        if copies.is_empty() {
            for initializer in &initializers {
                if !supported(&self.rows(
                    "CONSTRUCTOR_INITIALIZER_STATUS",
                    Some(&initializer.object),
                    None,
                    s,
                )?) {
                    return Ok(unknown("constructor_initializer_unknown"));
                }
            }
        }
        for statement in statements {
            let field = node(bindings, op(statement, 0)?.value());
            let value = node(bindings, op(statement, 1)?.value());
            let (Some(field), Some(value)) = (field, value) else {
                return Ok(unknown("initializer_binding_unknown"));
            };
            if !parameters.contains(&value.local_id) {
                return Ok(truth(false));
            }
            let overwritten = self
                .rows("WRITES", Some(&owner), Some(&field.local_id), s)?
                .iter()
                .any(|f| attr(&f.attrs, "execution").is_ok_and(|v| v.truthy()));
            if self.has(
                "PARAMETER_INITIALIZES_FIELD",
                &value.local_id,
                &field.local_id,
                s,
            )? {
                if overwritten {
                    return Ok(truth(false));
                }
                continue;
            }
            if self.has(
                "CONSTRUCTOR_FIELD_INPUT",
                &field.local_id,
                &value.local_id,
                s,
            )? {
                continue;
            }
            let mut copied = false;
            for initializer in &initializers {
                if copies.contains(&initializer.object)
                    && self.has("INITIALIZES_FIELD", &initializer.object, &field.local_id, s)?
                {
                    copied = true;
                }
            }
            if copied {
                if overwritten {
                    return Ok(truth(false));
                }
                continue;
            }
            let mut accepted = false;
            let mut uncertain = false;
            for initializer in &initializers {
                if !supported(&self.rows(
                    "CONSTRUCTOR_INITIALIZER_STATUS",
                    Some(&initializer.object),
                    None,
                    s,
                )?) {
                    uncertain = true;
                    continue;
                }
                if self.has("INITIALIZES_FIELD", &initializer.object, &field.local_id, s)?
                    && self.has(
                        "CONSTRUCTOR_INITIALIZER_INPUT",
                        &initializer.object,
                        &value.local_id,
                        s,
                    )?
                {
                    if overwritten {
                        return Ok(truth(false));
                    }
                    accepted = true;
                }
            }
            if !accepted {
                return Ok(if uncertain {
                    unknown("constructor_initializer_unknown")
                } else {
                    truth(false)
                });
            }
        }
        Ok(truth(true))
    }
    pub fn construct_match(
        &mut self,
        item: &Clause,
        clause: &Clause,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let Some(call) = self.call(operation) else {
            return Ok(unknown("construct_resolution_missing"));
        };
        let produced = self.ids("RESULT", &call.id, s)?;
        let allocated = self.ids("ALLOCATES_TYPE", &call.id, s)?;
        let mut instance = BTreeSet::new();
        for value in &produced {
            instance.extend(self.ids("INSTANCE_OF", value, s)?);
        }
        let mut built = current.get(&clause.role).cloned();
        let mut result = truth(false);
        if !matches!(built, Some(Value::Node(_))) {
            let types: BTreeSet<_> = allocated.union(&instance).cloned().collect();
            built = Some(if types.len() == 1 {
                self.value_node(types.into_iter().next().unwrap(), "CLASS")
            } else {
                result = unknown("construct_type_incomplete");
                unknown("construct_type_incomplete")
            });
            updated.insert(clause.role.clone(), built.clone().unwrap());
        }
        if let Some(Value::Node(built)) = built {
            result =
                truth(allocated.contains(&built.local_id) || instance.contains(&built.local_id));
        }
        for c in block(clause) {
            let matched = if c.kind == "argument" {
                let expected = c
                    .expressions
                    .iter()
                    .map(O::from)
                    .find(|e| e.kind() != "from");
                let derivation = c
                    .expressions
                    .iter()
                    .map(O::from)
                    .find(|e| e.kind() == "from");
                let bound = derivation
                    .or(expected.filter(|e| e.kind() == "role"))
                    .and_then(|e| node(current, e.value()));
                if let Some(bound) = bound {
                    let mut positions = BTreeSet::new();
                    if let Some(parameter) = node(current, &c.role) {
                        for binding in self.rows("CALL_BINDING", Some(&call.id), None, s)? {
                            if self.has(
                                "BINDING_PARAMETER",
                                &binding.object,
                                &parameter.local_id,
                                s,
                            )? && let Some(p) = number(&binding.attrs, "position")?
                            {
                                positions.insert(p);
                            }
                        }
                    }
                    let mut matched = truth(false);
                    for argument in self.rows("ARGUMENT", Some(&call.id), None, s)? {
                        if text(&argument.attrs, "kind")?.starts_with("spread") {
                            matched = matched.or(unknown("argument_pack_unresolved"));
                            continue;
                        }
                        let position = number(&argument.attrs, "position")?;
                        let selected = if !c.role.is_empty() {
                            position.is_some_and(|p| positions.contains(&p))
                        } else {
                            c.name == "any"
                                || (text(&argument.attrs, "kind")? == "positional"
                                    && c.name
                                        .parse::<i64>()
                                        .ok()
                                        .is_some_and(|p| Some(p) == position))
                        };
                        if !selected {
                            continue;
                        }
                        let mut same = argument.object == bound.local_id;
                        if !same && bound.kind == "CALL" {
                            let results = self.ids("RESULT", &bound.local_id, s)?;
                            same = !results.is_empty()
                                && !self
                                    .ids("VALUE", &argument.object, s)?
                                    .is_disjoint(&results);
                        }
                        matched = matched.or(truth(same));
                    }
                    matched
                } else {
                    unknown("construct_argument_unknown")
                }
            } else if c.kind == "property" && c.name == "retained" {
                if let Some(previous) = node(current, op(c, 0)?.value()) {
                    let owner = self.owner.local_id.clone();
                    let mut holds = false;
                    for choice in self.rows("BODY_VALUE", Some(&owner), None, s)? {
                        for condition in self.rows("SYNTAX_NODE", Some(&choice.object), None, s)? {
                            for test in self.rows(
                                "NULL_TEST",
                                Some(&condition.object),
                                Some(&previous.local_id),
                                s,
                            )? {
                                let (taken, kept) = if text(&test.attrs, "when")? == "true" {
                                    ("BRANCH_TRUE", "BRANCH_FALSE")
                                } else {
                                    ("BRANCH_FALSE", "BRANCH_TRUE")
                                };
                                let mut construction = false;
                                let mut retains = false;
                                for arm in self.rows(taken, Some(&condition.object), None, s)? {
                                    construction |= self.has("VALUE", &arm.object, &call.id, s)?;
                                }
                                for arm in self.rows(kept, Some(&condition.object), None, s)? {
                                    retains |=
                                        self.has("VALUE", &arm.object, &previous.local_id, s)?;
                                }
                                holds |= construction && retains;
                            }
                        }
                    }
                    truth(holds)
                } else {
                    unknown("retained_binding_unknown")
                }
            } else if c.kind == "initializer" {
                if let Some(place) = node(current, &c.role) {
                    let initializers = self.rows("HAS_INITIALIZER", Some(&call.id), None, s)?;
                    if !c.expressions.is_empty() {
                        if let Some(carried) = node(current, op(c, 0)?.value()) {
                            let mut stored = BTreeSet::from([carried.local_id.clone()]);
                            if let Some(producer) = self.producers.get(&carried.local_id) {
                                stored.insert(producer.clone());
                            }
                            let mut accepted = false;
                            for initializer in initializers {
                                accepted |= self.has(
                                    "INITIALIZES_FIELD",
                                    &initializer.object,
                                    &place.local_id,
                                    s,
                                )? && !self
                                    .ids("STORES_VALUE", &initializer.object, s)?
                                    .is_disjoint(&stored);
                            }
                            truth(accepted)
                        } else {
                            unknown("initializer_value_unknown")
                        }
                    } else {
                        let mut stored = false;
                        let mut inputs = self.ids("ARGUMENT", &call.id, s)?;
                        for initializer in initializers {
                            let values = self.ids("STORES_VALUE", &initializer.object, s)?;
                            stored |= values.contains(&place.local_id);
                            inputs.extend(values);
                        }
                        let loaded = self.has("ARGUMENT", &call.id, &place.local_id, s)?;
                        let forms = block(c)
                            .first()
                            .and_then(|c| c.expressions.first())
                            .map(O::from)
                            .map(|e| {
                                e.args()
                                    .map(|a| a.value().to_owned())
                                    .collect::<BTreeSet<_>>()
                            })
                            .unwrap_or_else(|| BTreeSet::from(["identity".into()]));
                        let mut accepted = forms.contains("identity") && (stored || loaded);
                        if forms.contains("shallow_copy") {
                            for input in inputs {
                                accepted |=
                                    self.has("SHALLOW_COPY_SOURCE", &input, &place.local_id, s)?;
                            }
                        }
                        truth(accepted)
                    }
                } else {
                    unknown("initializer_binding_unknown")
                }
            } else {
                truth(true)
            };
            result = result.and(matched);
        }
        if item.kind == "let" && !result.is_false() {
            if produced.len() == 1 {
                let id = produced.into_iter().next().unwrap();
                updated.insert(item.role.clone(), self.value_node(&id, "VALUE"));
                self.producers.insert(id, call.id.clone());
            } else {
                updated.insert(item.role.clone(), unknown("construct_result_incomplete"));
                result = result.and(unknown("construct_result_incomplete"));
            }
        }
        Ok(result)
    }
}
