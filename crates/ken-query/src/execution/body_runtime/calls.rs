use super::*;
use context::*;
use ken_program::{Entity, Operation};
impl Context<'_> {
    pub fn call_match(
        &mut self,
        item: &Clause,
        clause: &Clause,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let call = self.call(operation);
        let mut target = current.get(&clause.role).cloned();
        if !current.contains_key(&clause.role) {
            target = Some(if let Some(call) = &call {
                let mut targets = self.ids("TARGET", &call.id, s)?;
                targets.extend(self.ids("DECLARED_TARGET", &call.id, s)?);
                if targets.len() == 1 {
                    let id = targets.into_iter().next().unwrap();
                    let metadata = self.rows("ENTITY", Some(&id), None, s)?;
                    let name = metadata
                        .iter()
                        .find(|f| f.object == "CALLABLE")
                        .map(|f| text(&f.attrs, "name"))
                        .transpose()?
                        .unwrap_or_default();
                    let mut n = if let Value::Node(n) = self.value_node(id, "CALLABLE") {
                        (*n).clone()
                    } else {
                        unreachable!()
                    };
                    n.name = Some(name);
                    n.owner = None;
                    Value::Node(Arc::new(n))
                } else if block(clause).iter().any(|c| {
                    c.kind == "argument" || (c.kind == "property" && c.name == "resolution")
                }) {
                    let mut n = if let Value::Node(n) = self.value_node(&call.id, "CALL") {
                        (*n).clone()
                    } else {
                        unreachable!()
                    };
                    n.name = Some(call.name.clone());
                    n.owner = None;
                    Value::Node(Arc::new(n))
                } else {
                    unknown("call_target_incomplete")
                }
            } else {
                unknown("call_target_incomplete")
            });
            updated.insert(clause.role.clone(), target.clone().unwrap());
        }
        let mut result = truth(false);
        if let Some(source) = clause
            .expressions
            .first()
            .map(O::from)
            .filter(|e| e.kind() == "index")
        {
            let mut elements = self.ids("CALLEE_VALUE", &operation.id, s)?;
            if let Some(call) = &call {
                elements.extend(self.ids("CALLEE_VALUE", &call.id, s)?);
            }
            if elements.is_empty() {
                for f in self.rows("CALLEE_VALUE", None, None, s)? {
                    if let Some(entity) = self.entity(&f.subject, s)?
                        && number(&entity.attrs, "start_byte")? == Some(operation.start)
                        && number(&entity.attrs, "end_byte")? == Some(operation.end)
                    {
                        elements.insert(f.object.clone());
                    }
                }
            }
            result = if node(current, arg(source, 0)?.value()).is_none() {
                unknown("callee_container_unknown")
            } else {
                self.index_matches(
                    source,
                    &elements.into_iter().collect::<Vec<_>>(),
                    current,
                    updated,
                    false,
                    s,
                )?
            };
            if result.is_false() {
                return Ok(result);
            }
            target = None;
        }
        if flag(item, "qualify") {
            let place = current.get(&item.role);
            let unit = node(current, "unit").or_else(|| node(current, "$unit"));
            let qualifiers = if let Some(call) = &call {
                self.ids("TYPE_PARAMETER_RECEIVER", &call.id, s)?
            } else {
                BTreeSet::new()
            };
            let owners = if let Some(call) = &call {
                self.ids("TYPE_PARAMETER_OWNER", &call.id, s)?
            } else {
                BTreeSet::new()
            };
            let bound = place.and_then(|v| v.local_id().map(str::to_owned).or_else(|| v.text()));
            result = truth(
                !qualifiers.is_empty()
                    && unit.is_some_and(|u| owners.contains(&u.local_id))
                    && bound.is_some_and(|p| qualifiers.contains(&p)),
            );
            if result.is_false() {
                return Ok(result);
            }
            target = None;
        }
        if flag(item, "on") {
            let place = node(current, &item.role);
            let receivers = if let Some(call) = &call {
                self.ids("RECEIVER", &call.id, s)?
            } else {
                BTreeSet::new()
            };
            result = if let Some(place) = place {
                if let Some((loop_op, element)) = self.iteration.get(&place.local_id).cloned() {
                    if !receivers.contains(&element) {
                        if receivers.is_empty() {
                            unknown("call_receiver_missing")
                        } else {
                            truth(false)
                        }
                    } else if let Some(call) = &call {
                        truth(self.has("ITERATION_INVOKES_VALUE", &loop_op.id, &call.id, s)?)
                    } else {
                        truth(true)
                    }
                } else if receivers.is_empty() {
                    unknown("call_receiver_missing")
                } else {
                    truth(receivers.contains(&place.local_id))
                }
            } else {
                unknown("call_receiver_binding_unknown")
            };
            if result.is_false() {
                return Ok(result);
            }
            target = None;
        } else if let (Some(call), Some(Value::Node(selected))) = (&call, &target)
            && selected.kind != "CALLABLE"
        {
            result = truth(if selected.kind == "CALL" {
                call.id == selected.local_id
            } else {
                self.has("CALLEE_VALUE", &call.id, &selected.local_id, s)?
            });
            if !result.is_true()
                && selected.kind != "CALL"
                && let Some(producer) = self.producers.get(&selected.local_id).cloned()
            {
                result = truth(self.has("INVOKES_RESULT_OF", &call.id, &producer, s)?);
            }
            if !result.is_true()
                && let Some((_, element)) = self.iteration.get(&selected.local_id).cloned()
            {
                result = truth(self.has("CALLEE_VALUE", &call.id, &element, s)?);
            }
            target = None;
        }
        let Some(call) = call else {
            return Ok(unknown("call_resolution_missing"));
        };
        if let Some(target) = target {
            if let Value::Node(target) = target {
                let mut exact = self.ids("TARGET", &call.id, s)?;
                exact.extend(self.ids("DECLARED_TARGET", &call.id, s)?);
                let mut possible = exact.clone();
                possible.extend(self.ids("MAY_TARGET", &call.id, s)?);
                let mode = block(clause)
                    .iter()
                    .find(|c| c.kind == "property" && c.name == "dispatch")
                    .and_then(|c| c.expressions.first())
                    .map(|e| e.value().trim_matches('"'))
                    .unwrap_or("exact");
                if matches!(mode, "possible" | "contract") {
                    let receiver = block(clause)
                        .iter()
                        .find(|c| c.kind == "property" && c.name == "receiver")
                        .and_then(|c| c.expressions.first())
                        .and_then(|e| node(current, e.value()));
                    if let Some(receiver) = receiver
                        && let Some((loop_op, _)) = self.iteration.get(&receiver.local_id).cloned()
                    {
                        let typed = if self.keyed.contains(&loop_op.id) {
                            "KEY_TYPE"
                        } else {
                            "VALUE_TYPE"
                        };
                        for source in self.rows("ITERATION_SOURCE", Some(&loop_op.id), None, s)? {
                            let mut elements = self.rows(typed, Some(&source.object), None, s)?;
                            elements.extend(self.rows(
                                "ELEMENT_TYPE",
                                Some(&source.object),
                                None,
                                s,
                            )?);
                            for element in elements {
                                for method in
                                    self.rows("HAS_METHOD", Some(&element.object), None, s)?
                                {
                                    if target.name.as_deref() == Some(&call.name)
                                        && (method.object == target.local_id
                                            || (mode == "contract"
                                                && self.has(
                                                    "OVERRIDES",
                                                    &target.local_id,
                                                    &method.object,
                                                    s,
                                                )?))
                                    {
                                        possible.insert(target.local_id.clone());
                                    }
                                }
                            }
                            if mode == "contract"
                                && target.name.as_deref() == Some(&call.name)
                                && self.has("ITERATED_CALL", &call.id, &source.object, s)?
                            {
                                possible.insert(target.local_id.clone());
                            }
                        }
                    }
                    result = if possible.is_empty() {
                        unknown("call_target_incomplete")
                    } else {
                        truth(possible.contains(&target.local_id))
                    };
                } else if exact.contains(&target.local_id) {
                    result = if exact.len() == 1 {
                        truth(true)
                    } else {
                        unknown("call_target_incomplete")
                    };
                } else {
                    result = truth(
                        self.ids("CONSTRUCTOR_TARGET", &call.id, s)?
                            == BTreeSet::from([target.local_id.clone()]),
                    );
                }
            } else {
                result = unknown("call_resolution_missing");
            }
        }
        if result.is_false() {
            return Ok(result);
        }
        for constraint in block(clause) {
            s.check()?;
            let matched = if constraint.kind == "argument" {
                self.argument_match(constraint, &call, operation, current, updated, s)?
            } else if constraint.kind == "property" {
                self.call_property(constraint, clause, &call, operation, current, updated, s)?
            } else {
                truth(true)
            };
            result = result.and(matched);
            if result.is_false() {
                break;
            }
        }
        if item.kind == "let" && !result.is_false() {
            let produced = self.ids("RESULT", &call.id, s)?;
            if produced.len() == 1 {
                let id = produced.into_iter().next().unwrap();
                updated.insert(item.role.clone(), self.value_node(&id, "VALUE"));
                self.producers.insert(id, call.id.clone());
                if !item.name.is_empty() {
                    let mut holder = Some(Arc::new(operation.clone()));
                    let mut place = None;
                    let mut saw_place = false;
                    for _ in 0..3 {
                        let Some(h) = holder else { break };
                        for f in self.rows("ASSIGNMENT_TARGET", Some(&h.id), None, s)? {
                            saw_place = true;
                            let counts =
                                self.rows("STORAGE_WRITE_COUNT", Some(&f.object), None, s)?;
                            if counts.len() != 1 || counts[0].object != item.name {
                                continue;
                            }
                            let statuses =
                                self.rows("STORAGE_WRITE_STATUS", Some(&f.object), None, s)?;
                            if !statuses.is_empty() && !supported(&statuses) {
                                continue;
                            }
                            place = Some(f.object.clone());
                            break;
                        }
                        if place.is_some() {
                            break;
                        }
                        holder = h
                            .parent
                            .as_ref()
                            .and_then(|id| self.operations.get(id))
                            .cloned();
                    }
                    if let Some(place) = place {
                        let kinds = self.rows("ENTITY", Some(&place), None, s)?;
                        updated.insert(
                            item.role.clone(),
                            self.value_node(
                                place,
                                if kinds.len() == 1 {
                                    &kinds[0].object
                                } else {
                                    "STORAGE"
                                },
                            ),
                        );
                    } else {
                        result = if saw_place {
                            truth(false)
                        } else {
                            result.and(unknown("call_result_place_unknown"))
                        };
                    }
                }
            } else {
                updated.insert(item.role.clone(), unknown("call_result_incomplete"));
                result = result.and(unknown("call_result_incomplete"));
            }
        }
        Ok(result)
    }
    #[expect(
        clippy::too_many_arguments,
        reason = "Source and semantic call identities and both binding environments are distinct inputs"
    )]
    fn call_property(
        &mut self,
        c: &Clause,
        clause: &Clause,
        call: &Entity,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let expected = op(c, 0)?;
        match c.name.as_str() {
            "dispatch" | "rebound" => Ok(truth(true)),
            "entry" | "receiver_input" => {
                let relation = if c.name == "entry" {
                    "CALL_ENTRY_BINDING"
                } else {
                    "CALL_RECEIVER_INPUT"
                };
                Ok(if let Some(place) = node(current, expected.value()) {
                    truth(self.has(relation, &call.id, &place.local_id, s)?)
                } else {
                    unknown(if c.name == "entry" {
                        "call_entry_binding_unknown"
                    } else {
                        "call_receiver_binding_unknown"
                    })
                })
            }
            "receiver" => {
                if expected.kind() == "member" {
                    let candidates = self.ids("CALLEE_VALUE", &call.id, s)?;
                    let resolved = self.member_place(expected, current, &candidates, s)?;
                    return Ok(if resolved.is_false() {
                        truth(false)
                    } else if matches!(resolved, Value::Node(_)) {
                        truth(true)
                    } else {
                        unknown("call_receiver_member_unknown")
                    });
                }
                let receivers = self.ids("RECEIVER", &call.id, s)?;
                if receivers.is_empty() {
                    return Ok(unknown("call_receiver_missing"));
                }
                let Some(place) = node(current, expected.value()) else {
                    return Ok(unknown("call_receiver_binding_unknown"));
                };
                if let Some((_, original)) = self.iteration.get(&place.local_id).cloned() {
                    let rebound = block(clause).iter().any(|c| {
                        c.kind == "property"
                            && c.name == "rebound"
                            && c.expressions
                                .first()
                                .is_some_and(|e| e.value().trim_matches('"') == "true")
                    });
                    if rebound {
                        return Ok(truth(receivers.contains(&original)));
                    }
                    let mut result = truth(false);
                    for receiver in receivers {
                        result = result.or(self.iteration_value_at(
                            &place.local_id,
                            &receiver,
                            operation,
                            s,
                        )?);
                    }
                    Ok(result)
                } else {
                    Ok(truth(receivers.contains(&place.local_id)))
                }
            }
            "name" => {
                let role = if expected.kind() == "role" {
                    expected.value()
                } else if expected.kind() == "binary" && expected.value() == "in" {
                    arg(expected, 0)?.value()
                } else {
                    ""
                };
                let inventory = if !role.is_empty() && expected.kind() == "binary" {
                    arg(expected, 1)?
                } else {
                    expected
                };
                let mut spelling = text(&call.attrs, "name")?;
                if spelling.is_empty() {
                    for f in self.rows("ENTITY", Some(&call.id), None, s)? {
                        spelling = text(&f.attrs, "name")?;
                        if !spelling.is_empty() {
                            break;
                        }
                    }
                }
                if spelling.is_empty() {
                    spelling = call.name.clone();
                }
                if !role.is_empty() {
                    updated.insert(role.into(), Value::string(spelling.as_str()));
                    if inventory.kind() == "role" {
                        return Ok(truth(true));
                    }
                }
                if inventory.kind() == "regex" {
                    return Ok(truth(s.name_regex(&spelling, &query(inventory))?));
                }
                let choices = if inventory.kind() == "list" {
                    inventory.args().collect::<Vec<_>>()
                } else {
                    vec![inventory]
                };
                Ok(truth(choices.into_iter().any(|e| {
                    if e.kind() == "literal" {
                        literal(e).ok().and_then(|v| v.text()).as_deref() == Some(&spelling)
                    } else {
                        e.value() == spelling
                    }
                })))
            }
            "resolution" => {
                let wanted = expected.value().trim_matches('"');
                if wanted == "any" {
                    return Ok(truth(true));
                }
                let mut status = text(&call.attrs, "resolution")?;
                if status.is_empty() {
                    for f in self.rows("ENTITY", Some(&call.id), None, s)? {
                        status = text(&f.attrs, "resolution")?;
                        if !status.is_empty() {
                            break;
                        }
                    }
                }
                Ok(if status.is_empty() {
                    unknown("call_resolution_status_missing")
                } else {
                    truth(status == wanted)
                })
            }
            "discarded" => Ok(truth(
                !self
                    .rows("DISCARDS_RESULT", None, Some(&call.id), s)?
                    .is_empty(),
            )),
            "returned" => {
                let mut operands = BTreeSet::new();
                let mut origins = BTreeSet::new();
                for statement in self.ordered.clone() {
                    operands.extend(self.ids("RETURN_OPERAND", &statement.id, s)?);
                    origins.extend(self.ids("RETURN_ORIGIN", &statement.id, s)?);
                }
                let casts = self
                    .rows("CAST_VALUE", None, Some(&call.id), s)?
                    .iter()
                    .map(|f| f.subject.clone())
                    .collect::<BTreeSet<_>>();
                let mut members = BTreeSet::new();
                let mut frontier = BTreeSet::from([call.id.clone()]);
                for _ in 0..2 {
                    let mut following = BTreeSet::new();
                    for base in frontier {
                        for f in self.rows("MEMBER_OF", None, Some(&base), s)? {
                            following.insert(f.subject.clone());
                        }
                    }
                    members.extend(following.iter().cloned());
                    frontier = following;
                }
                let owner = self.owner.local_id.clone();
                Ok(truth(
                    operands.contains(&call.id)
                        || origins.contains(&call.id)
                        || !operands.is_disjoint(&casts)
                        || !operands.is_disjoint(&members)
                        || self.has("RETURNS_CALL", &owner, &call.id, s)?,
                ))
            }
            "unreplaced" => {
                let role = block(clause)
                    .iter()
                    .find(|c| c.kind == "property" && c.name == "receiver")
                    .and_then(|c| c.expressions.first())
                    .map(Expression::value);
                Ok(
                    if let Some(place) = role.and_then(|role| node(current, role)) {
                        truth(self.has("RECEIVER_UNREPLACED", &call.id, &place.local_id, s)?)
                    } else {
                        unknown("call_receiver_binding_unknown")
                    },
                )
            }
            "receiver_version" => {
                let versions = self.ids("RECEIVER_BINDING_VERSION", &call.id, s)?;
                if versions.is_empty() {
                    return Ok(unknown("call_receiver_version_missing"));
                }
                if let Some(known) = node(current, expected.value()) {
                    Ok(truth(versions.contains(&known.local_id)))
                } else if current.contains_key(expected.value()) {
                    Ok(unknown("call_receiver_version_unknown"))
                } else {
                    updated.insert(
                        expected.value().into(),
                        self.value_node(versions.into_iter().next().unwrap(), "VALUE"),
                    );
                    Ok(truth(true))
                }
            }
            "wraps" | "empty" | "present" | "fallback" => {
                let relation = match c.name.as_str() {
                    "wraps" => "OPTIONAL_VALUE",
                    "empty" => "OPTIONAL_OR",
                    "present" => "OPTIONAL_PRESENT",
                    _ => "OPTIONAL_FALLBACK",
                };
                let facts = self.rows(relation, Some(&call.id), None, s)?;
                if facts.is_empty() {
                    return Ok(truth(false));
                }
                if expected.kind() == "role" {
                    if let Some(bound) = node(current, expected.value()) {
                        return Ok(truth(facts.iter().any(|f| f.object == bound.local_id)));
                    }
                    if current.contains_key(expected.value()) {
                        return Ok(unknown("optional_handler_unknown"));
                    }
                    updated.insert(
                        expected.value().into(),
                        self.value_node(&facts[0].object, "VALUE"),
                    );
                    Ok(truth(true))
                } else {
                    let wanted = expected.value().trim_matches('"').to_uppercase();
                    Ok(truth(
                        facts.iter().any(|f| f.object.to_uppercase() == wanted),
                    ))
                }
            }
            _ => Err(invalid(format!(
                "unsupported BODY call property {}",
                c.name
            ))),
        }
    }
    pub fn argument_match(
        &mut self,
        c: &Clause,
        call: &Entity,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let arguments = self.rows("ARGUMENT", Some(&call.id), None, s)?;
        let mut matched = truth(false);
        let mut positions = BTreeSet::new();
        if !c.role.is_empty() {
            if let Some(parameter) = node(current, &c.role) {
                for binding in self.rows("CALL_BINDING", Some(&call.id), None, s)? {
                    if self.has("BINDING_PARAMETER", &binding.object, &parameter.local_id, s)?
                        && let Some(p) = number(&binding.attrs, "position")?
                    {
                        positions.insert(p);
                    }
                }
                if positions.is_empty() && !self.has("BINDING_STATUS", &call.id, "supported", s)? {
                    let mut targets = self.ids("TARGET", &call.id, s)?;
                    targets.extend(self.ids("DECLARED_TARGET", &call.id, s)?);
                    for target in targets {
                        let parameters = self.rows("HAS_PARAMETER", Some(&target), None, s)?;
                        for declared in &parameters {
                            if declared.object != parameter.local_id {
                                continue;
                            }
                            if let Some(position) = number(&declared.attrs, "position")? {
                                let mut passed = 0;
                                for other in &parameters {
                                    if attr(&other.attrs, "receiver")?.truthy()
                                        && number(&other.attrs, "position")?.unwrap_or(0) < position
                                    {
                                        passed += 1;
                                    }
                                }
                                positions.insert(position - passed);
                            }
                        }
                    }
                }
                if positions.is_empty() {
                    matched = unknown("parameter_binding_incomplete");
                }
            } else {
                matched = unknown("parameter_binding_incomplete");
            }
        }
        for argument in &arguments {
            let position = number(&argument.attrs, "position")?;
            let kind = text(&argument.attrs, "kind")?;
            let selected = if !c.role.is_empty() {
                position.is_some_and(|p| positions.contains(&p))
            } else if c.name == "any" {
                true
            } else if c.name.starts_with('"') {
                text(&argument.attrs, "name")?
                    == serde_json::from_str::<String>(&c.name).unwrap_or_default()
            } else {
                kind == "positional"
                    && c.name
                        .parse::<i64>()
                        .ok()
                        .is_some_and(|p| Some(p) == position)
            };
            if kind.starts_with("spread") {
                matched = matched.or(unknown("argument_pack_unresolved"));
                continue;
            }
            if !selected {
                continue;
            }
            if c.name.chars().all(|c| c.is_ascii_digit()) && !c.name.is_empty() {
                let mut earlier = false;
                for a in &arguments {
                    if text(&a.attrs, "kind")?.starts_with("spread")
                        && number(&a.attrs, "position")?.unwrap_or(0) < position.unwrap_or(0)
                    {
                        earlier = true;
                    }
                }
                if earlier {
                    matched = matched.or(unknown("argument_position_after_pack"));
                    continue;
                }
            }
            if let Some(derivation) = c
                .expressions
                .iter()
                .map(O::from)
                .find(|e| e.kind() == "from")
            {
                let origins = self
                    .rows("ARGUMENT_VALUE_ORIGIN", Some(&call.id), None, s)?
                    .into_iter()
                    .filter(|f| number(&f.attrs, "position").ok().flatten() == position)
                    .collect::<Vec<_>>();
                matched = matched.or(self.derived_from(
                    current.get(derivation.value()),
                    &objects(&origins),
                    s,
                )?);
                continue;
            }
            let mut expected = op(c, 0)?;
            if expected.kind() == "call" && expected.value() == "read" {
                expected = arg(arg(expected, 0)?, 0)?;
            }
            let candidate = if expected.kind() == "index" {
                let mut candidates = vec![argument.object.clone()];
                candidates.extend(
                    self.rows("VALUE", Some(&argument.object), None, s)?
                        .iter()
                        .map(|f| f.object.clone()),
                );
                self.index_matches(expected, &candidates, current, updated, true, s)?
            } else if expected.kind() == "role" {
                if let Some(binding) = node(current, expected.value()) {
                    if self.iteration.contains_key(&binding.local_id) {
                        self.iteration_value_at(&binding.local_id, &argument.object, operation, s)?
                    } else if binding.kind == "VALUE" {
                        let origins = self
                            .rows("ARGUMENT_VALUE_ORIGIN", Some(&call.id), None, s)?
                            .into_iter()
                            .filter(|f| number(&f.attrs, "position").ok().flatten() == position)
                            .collect::<Vec<_>>();
                        if origins.is_empty() {
                            unknown("argument_origin_missing")
                        } else {
                            let truth =
                                self.captured_reaches(&binding.local_id, &objects(&origins), s)?;
                            if truth.is_true()
                                && origins.iter().any(|f| {
                                    text(&f.attrs, "modality").ok().as_deref() == Some("may")
                                })
                            {
                                unknown("argument_origin_may")
                            } else {
                                truth
                            }
                        }
                    } else if binding.kind == "CALLABLE" {
                        truth(
                            argument.object == binding.local_id
                                || self.callable_reaches(
                                    &binding.local_id,
                                    &argument.object,
                                    operation,
                                    s,
                                )?,
                        )
                    } else {
                        let mut same = argument.object == binding.local_id;
                        if !same && binding.kind == "CALL" {
                            let results = self.ids("RESULT", &binding.local_id, s)?;
                            same = !results.is_empty()
                                && !self
                                    .ids("VALUE", &argument.object, s)?
                                    .is_disjoint(&results);
                        }
                        truth(same)
                    }
                } else if current
                    .get(expected.value())
                    .and_then(Value::text)
                    .is_some()
                {
                    unknown("captured_value_argument_unsupported")
                } else {
                    unknown("argument_binding_unknown")
                }
            } else if expected.kind() == "wildcard" {
                truth(true)
            } else {
                let entity = self.entity(&argument.object, s)?;
                let span = entity
                    .as_ref()
                    .map(|e| {
                        Ok::<_, ExecutionError>((
                            number(&e.attrs, "start_byte")?.unwrap_or(-1),
                            number(&e.attrs, "end_byte")?.unwrap_or(-1),
                        ))
                    })
                    .transpose()?;
                let operation = span.and_then(|span| self.spans.get(&span).cloned());
                if let Some(operation) = operation {
                    let mut current = current.clone();
                    self.source_matches(expected, &operation, &mut current, None, s)?
                } else {
                    unknown("argument_expression_missing")
                }
            };
            matched = matched.or(candidate);
        }
        Ok(matched)
    }
}
