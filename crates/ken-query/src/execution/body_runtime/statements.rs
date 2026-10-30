use super::*;
use context::*;
use ken_program::{Operation, value::GraphValue as S};
impl Context<'_> {
    pub fn simple_match(
        &mut self,
        item: &Clause,
        operation: &Operation,
        group: &str,
        current: &Bindings,
        snapshot: Option<&Snapshot>,
        s: &mut dyn BodyServices,
    ) -> Result<Vec<Witness>> {
        let mut updated = current.clone();
        let mut result = truth(false);
        if item.kind == "macro" {
            if id_value(current, &item.role).as_deref() == Some(&operation.id)
                && operation.native_kind == "macro_invocation"
            {
                result = truth(true);
            }
        } else if item.kind == "break" {
            let loop_id = id_value(current, &item.role);
            let mut ancestor = operation
                .parent
                .as_ref()
                .and_then(|id| self.ordered.iter().find(|o| &o.id == id))
                .cloned();
            let mut seen = BTreeSet::new();
            while let Some(op) = ancestor.clone() {
                if !seen.insert(op.id.clone()) {
                    ancestor = None;
                    break;
                }
                if matches!(op.kind.as_str(), "LOOP" | "SWITCH" | "MATCH")
                    || matches!(
                        op.native_kind.as_str(),
                        "switch_statement" | "switch_expression"
                    )
                {
                    break;
                }
                ancestor = op
                    .parent
                    .as_ref()
                    .and_then(|id| self.ordered.iter().find(|o| &o.id == id))
                    .cloned();
            }
            if let Some(ancestor) = ancestor {
                result = truth(
                    ancestor.kind == "LOOP"
                        && Some(&ancestor.id) == loop_id.as_ref()
                        && self
                            .rows("CFG_NEXT", Some(&operation.id), None, s)?
                            .iter()
                            .any(|f| text(&f.attrs, "kind").ok().as_deref() == Some("break")),
                );
            }
        } else if item.kind == "yield" && operation.kind == "YIELD" {
            if strings(&operation.attrs, "tokens")?
                .iter()
                .any(|t| t == "break")
                || attr(&operation.attrs, "delegated")?.truthy() != flag(item, "from")
            {
                return Ok(vec![]);
            }
            let children = self.clean_children(&operation.id);
            let expected = op(item, 0)?;
            if expected.kind() == "wildcard" {
                result = truth(true);
            } else if children.len() == 1 {
                if let (Some(snapshot), Some(produced)) = (
                    snapshot,
                    node(current, expected.value())
                        .filter(|n| expected.kind() == "role" && n.kind == "VALUE"),
                ) {
                    result = self.path_matches(&produced, &children[0], snapshot, s)?;
                } else {
                    let mut input = current.clone();
                    result = self.source_matches(expected, &children[0], &mut input, None, s)?;
                }
            } else if children.is_empty() {
                result = truth(expected.kind() == "literal" && expected.value() == "null");
            }
        } else if item.kind == "return" && operation.kind == "RETURN" {
            if self.deferred.contains(&operation.id)
                && self
                    .events
                    .get(group)
                    .map(|e| text(e, "action"))
                    .transpose()?
                    .as_deref()
                    != Some("return-complete")
            {
                return Ok(vec![]);
            }
            result = self.return_match(item, operation, current, &mut updated, snapshot, s)?;
        } else if item.kind == "assign" {
            result = self.assign_match(item, operation, current, &mut updated, s)?;
        } else if item.kind == "let"
            && item
                .expressions
                .first()
                .is_some_and(|e| e.kind() == "index")
        {
            result = self.index_capture(item, operation, current, &mut updated, s)?;
        } else if item.kind == "insert" {
            result = self.insert_match(item, operation, current, &mut updated, s)?;
        } else if item.kind == "clear" {
            if let Some(collection) = node(current, &item.role) {
                let mut subjects = vec![operation.id.clone()];
                if operation.kind == "CALL"
                    && let Some(call) = self.call(operation)
                {
                    subjects.push(call.id.clone());
                }
                let mut cleared = false;
                let mut after = item.name.is_empty();
                let loop_id = id_value(current, &item.name);
                for subject in subjects {
                    cleared |= self.has("CLEARS_COLLECTION", &subject, &collection.local_id, s)?;
                    if let Some(id) = &loop_id {
                        after |= self.has("AFTER_ITERATION", &subject, id, s)?;
                    }
                }
                result = truth(cleared && after);
            }
        } else if item.kind == "selector" && operation.id == group {
            return Err(invalid("selector requires a streaming clause cursor"));
        } else {
            let clause = if item.kind == "let" && !item.blocks.is_empty() {
                block(item).first().unwrap_or(item)
            } else {
                item
            };
            if clause.kind == "construct" && operation.kind == "CALL" {
                result = self.construct_match(item, clause, operation, current, &mut updated, s)?;
            }
            if clause.kind == "call"
                && (operation.kind == "CALL" || self.foreign.contains(&operation.id))
            {
                result = self.call_match(item, clause, operation, current, &mut updated, s)?;
            }
        }
        if result.is_false() {
            return Ok(vec![]);
        }
        if item.kind == "let" && !updated.contains_key(&item.role) {
            updated.insert(item.role.clone(), unknown("produced_value_unknown"));
        }
        Ok(vec![Witness {
            bindings: updated,
            unknown: result.is_unknown(),
            operation: operation.id.clone(),
        }])
    }
    pub fn clean_children(&self, id: &str) -> Vec<Op> {
        self.children
            .get(id)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .filter(|o| !o.native_kind.contains("comment"))
            .collect()
    }
    fn return_match(
        &mut self,
        item: &Clause,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        snapshot: Option<&Snapshot>,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let expressions = self.clean_children(&operation.id);
        let selected = item
            .expressions
            .first()
            .map(O::from)
            .filter(|e| e.kind() == "role")
            .and_then(|e| node(current, e.value()));
        let mut result = truth(false);
        let derivation = block(item).first().filter(|c| c.kind == "from");
        if let Some(derivation) = derivation {
            let mut origins = self.rows("RETURN_ORIGIN", Some(&operation.id), None, s)?;
            if origins.is_empty() {
                origins = self.rows("RETURN_OPERAND", Some(&operation.id), None, s)?;
            }
            result = self.derived_from(current.get(&derivation.role), &objects(&origins), s)?;
            if result.is_false()
                && !origins.is_empty()
                && origins
                    .iter()
                    .all(|f| text(&f.attrs, "modality").ok().as_deref() == Some("may"))
            {
                result = unknown("derivation_may");
            }
        } else if item.expressions.is_empty() {
            result = truth(expressions.is_empty());
        } else if op(item, 0)?.kind() == "index" && expressions.len() == 1 {
            let source = op(item, 0)?;
            if node(current, arg(source, 0)?.value()).is_none() {
                result = unknown("returned_element_container_unknown");
            } else {
                let mut returned = self.rows("RETURN_ORIGIN", Some(&operation.id), None, s)?;
                if returned.is_empty() {
                    returned = self.rows("RETURN_OPERAND", Some(&operation.id), None, s)?;
                }
                let mut candidates = vec![];
                for candidate in returned {
                    candidates.push(candidate.object.clone());
                    candidates.extend(
                        self.rows("VALUE", Some(&candidate.object), None, s)?
                            .iter()
                            .map(|f| f.object.clone()),
                    );
                }
                result = self.index_matches(source, &candidates, current, updated, true, s)?;
            }
        } else if let Some(selected) = selected.as_ref().filter(|n| n.kind == "CALLABLE") {
            let operands = self.rows("RETURN_OPERAND", Some(&operation.id), None, s)?;
            result = if operands.is_empty() {
                unknown("returned_callable_unknown")
            } else {
                truth(operands.iter().any(|f| f.object == selected.local_id))
            };
            if result.is_false() {
                for operand in operands {
                    let counts =
                        self.rows("STORAGE_WRITE_COUNT", Some(&operand.object), None, s)?;
                    if counts.len() != 1
                        || counts[0].object != "1"
                        || !supported(&self.rows(
                            "STORAGE_WRITE_STATUS",
                            Some(&operand.object),
                            None,
                            s,
                        )?)
                    {
                        continue;
                    }
                    for write in self.operations.values().cloned().collect::<Vec<_>>() {
                        if write.parent == operation.parent
                            && write.end < operation.start
                            && self.has("ASSIGNMENT_TARGET", &write.id, &operand.object, s)?
                            && self.has("ASSIGNMENT_VALUE", &write.id, &selected.local_id, s)?
                        {
                            result = truth(true);
                        }
                    }
                }
            }
        } else if expressions.len() == 1 {
            let expected = op(item, 0)?;
            let produced = if expected.kind() == "role" {
                node(current, expected.value())
            } else {
                None
            };
            let origins = if produced.as_ref().is_some_and(|n| n.kind == "VALUE") {
                self.rows("RETURN_ORIGIN", Some(&operation.id), None, s)?
            } else {
                vec![]
            };
            let targets = if origins.is_empty() {
                self.ids("RETURN_OPERAND", &operation.id, s)?
            } else {
                objects(&origins)
            };
            result = if !origins.is_empty() {
                self.captured_reaches(&produced.as_ref().unwrap().local_id, &targets, s)?
            } else {
                let mut input = current.clone();
                self.source_matches(
                    expected,
                    &expressions[0],
                    &mut input,
                    if targets.is_empty() {
                        None
                    } else {
                        Some(targets)
                    },
                    s,
                )?
            };
            if result.is_false()
                && let Some(produced) = produced.as_ref().filter(|n| {
                    matches!(
                        n.kind.as_str(),
                        "STORAGE" | "PARAMETER" | "MEMBER" | "FIELD"
                    )
                })
            {
                let yielded = self.ids("RETURN_ORIGIN", &operation.id, s)?;
                let held = self.ids("ASSIGNED_FROM", &produced.local_id, s)?;
                if !yielded.is_empty() && !held.is_empty() {
                    result = truth(!yielded.is_disjoint(&held));
                }
            }
            if let (Some(snapshot), Some(produced)) =
                (snapshot, produced.filter(|n| n.kind == "VALUE"))
            {
                if self.implied.as_ref().is_none_or(|o| o.id != operation.id) {
                    result = self.path_matches(&produced, operation, snapshot, s)?;
                } else if result.is_true()
                    && origins
                        .iter()
                        .any(|f| text(&f.attrs, "modality").ok().as_deref() == Some("may"))
                {
                    result = unknown("return_origin_may");
                }
            } else if result.is_true()
                && origins
                    .iter()
                    .any(|f| text(&f.attrs, "modality").ok().as_deref() == Some("may"))
            {
                result = unknown("return_origin_may");
            }
        }
        if !result.is_false()
            && let Some(copy) = block(item).first().filter(|c| c.kind == "copies")
        {
            if let Some(field) = node(current, &copy.role) {
                let mut copied = vec![];
                for state in self.rows("RETURN_FIELD_STATE", Some(&operation.id), None, s)? {
                    if text(&state.attrs, "field")? != field.name.clone().unwrap_or_default() {
                        continue;
                    }
                    let mut matches = false;
                    for link in self.rows("FIELD_STATE_WRITE", Some(&state.object), None, s)? {
                        matches |=
                            self.has("ASSIGNMENT_VALUE", &link.object, &field.local_id, s)?;
                    }
                    if matches {
                        copied.push(state);
                    }
                }
                result = if copied.is_empty() {
                    truth(false)
                } else if copied
                    .iter()
                    .all(|f| text(&f.attrs, "modality").ok().as_deref() == Some("may"))
                {
                    unknown("copied_field_state_may")
                } else {
                    result
                };
            } else {
                result = unknown("copied_field_unbound");
            }
        }
        Ok(result)
    }
    fn assign_match(
        &mut self,
        item: &Clause,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let expected = op(item, 0)?;
        let targets = self.ids("ASSIGNMENT_TARGET", &operation.id, s)?;
        let operators = self.rows("OPERATOR", Some(&operation.id), None, s)?;
        let target = if expected.kind() == "member" {
            self.member_place(expected, current, &targets, s)?
        } else if expected.kind() == "index" {
            let mut target = truth(false);
            let key = arg(expected, 1)?;
            let supported_key = key.kind() == "wildcard"
                || (key.kind() == "role" && node(current, key.value()).is_some());
            for candidate in &targets {
                if !supported_key {
                    continue;
                }
                let mut input = updated.clone();
                if self
                    .index_matches(
                        expected,
                        std::slice::from_ref(candidate),
                        current,
                        &mut input,
                        false,
                        s,
                    )?
                    .is_true()
                {
                    target = self.value_node(candidate, "VALUE");
                    break;
                }
            }
            target
        } else {
            current
                .get(expected.value())
                .cloned()
                .unwrap_or_else(|| unknown("assignment_target_unknown"))
        };
        let Value::Node(target) = target else {
            return Ok(truth(false));
        };
        if !targets.contains(&target.local_id)
            || operators.first().map_or("=", |f| f.object.as_str()) != item.name
        {
            return Ok(truth(false));
        }
        let mut operands = self.rows("OPERAND", Some(&operation.id), None, s)?;
        operands.sort_by_key(|f| number(&f.attrs, "position").ok().flatten().unwrap_or(0));
        let rhs = if let Some(last) = operands.last() {
            self.operation(&last.object, s)?
        } else {
            self.children
                .get(&operation.id)
                .into_iter()
                .flatten()
                .find(|o| matches!(o.role.as_str(), "right" | "value"))
                .cloned()
        };
        let source = op(item, 1)?;
        if let Some(rhs) = rhs {
            let produced = if source.kind() == "role" {
                node(current, source.value())
            } else {
                None
            };
            let origins = if produced.as_ref().is_some_and(|n| n.kind == "VALUE") {
                self.rows("ASSIGNMENT_ORIGIN", Some(&operation.id), None, s)?
            } else {
                vec![]
            };
            let values = if origins.is_empty() {
                self.ids("ASSIGNMENT_VALUE", &operation.id, s)?
            } else {
                objects(&origins)
            };
            let landing = if expected.kind() == "index" {
                self.landed_place(
                    source
                        .kind()
                        .eq("role")
                        .then(|| current.get(source.value()))
                        .flatten(),
                    s,
                )?
            } else {
                String::new()
            };
            let result = if !landing.is_empty() && values.contains(&landing) {
                truth(true)
            } else if !origins.is_empty() {
                self.captured_reaches(&produced.as_ref().unwrap().local_id, &values, s)?
            } else {
                self.source_matches(
                    source,
                    &rhs,
                    updated,
                    if values.is_empty() {
                        None
                    } else {
                        Some(values)
                    },
                    s,
                )?
            };
            Ok(
                if result.is_true()
                    && origins
                        .iter()
                        .any(|f| text(&f.attrs, "modality").ok().as_deref() == Some("may"))
                {
                    unknown("assignment_origin_may")
                } else {
                    result
                },
            )
        } else {
            let stored = self.ids("ASSIGNMENT_VALUE", &operation.id, s)?;
            Ok(truth(
                node(current, source.value()).is_some_and(|n| stored.contains(&n.local_id)),
            ))
        }
    }
    fn index_capture(
        &mut self,
        item: &Clause,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let expected = op(item, 0)?;
        if node(current, arg(expected, 0)?.value()).is_none() {
            return Ok(unknown("index_container_unknown"));
        }
        for row in self.rows("ASSIGNMENT_VALUE", Some(&operation.id), None, s)? {
            let mut candidates = self
                .rows("VALUE", Some(&row.object), None, s)?
                .iter()
                .map(|f| f.object.clone())
                .collect::<Vec<_>>();
            candidates.push(row.object.clone());
            for candidate in candidates {
                if !self
                    .index_matches(expected, &[candidate], current, updated, true, s)?
                    .is_true()
                {
                    continue;
                }
                for target in self.ids("ASSIGNMENT_TARGET", &operation.id, s)? {
                    let counts = self.rows("STORAGE_WRITE_COUNT", Some(&target), None, s)?;
                    if counts.len() != 1
                        || counts[0].object
                            != if item.name.is_empty() {
                                "1"
                            } else {
                                &item.name
                            }
                    {
                        continue;
                    }
                    let statuses = self.rows("STORAGE_WRITE_STATUS", Some(&target), None, s)?;
                    if !statuses.is_empty() && !supported(&statuses) {
                        continue;
                    }
                    let kinds = self.rows("ENTITY", Some(&target), None, s)?;
                    updated.insert(
                        item.role.clone(),
                        self.value_node(
                            target,
                            if kinds.len() == 1 {
                                &kinds[0].object
                            } else {
                                "STORAGE"
                            },
                        ),
                    );
                    return Ok(truth(true));
                }
                break;
            }
        }
        Ok(truth(false))
    }
    pub fn selector_from(
        &mut self,
        item: &Clause,
        operation: &Operation,
        current: &Bindings,
        start: &mut usize,
        s: &mut dyn BodyServices,
    ) -> Result<Option<Witness>> {
        while let Some(n) = self.locals.get(*start).cloned() {
            *start += 1;
            s.check()?;
            if n.kind != "STORAGE"
                || current
                    .get(&item.role)
                    .is_some_and(|v| v != &Value::Node(n.clone()))
            {
                continue;
            }
            let props = self.graph.source_properties(&n)?;
            if props.get("declared") != Some(&S::Bool(true)) {
                continue;
            }
            let start = match props.get("start_byte") {
                Some(S::Int(v)) => v.parse::<i64>().ok(),
                _ => None,
            };
            let Some(start) = start else { continue };
            let mut declaration = self
                .operations
                .values()
                .filter(|o| o.start <= start && start < o.end)
                .min_by_key(|o| o.end - o.start)
                .cloned();
            let mut seen = BTreeSet::new();
            while let Some(candidate) = declaration.clone() {
                if !seen.insert(candidate.id.clone()) {
                    declaration = None;
                    break;
                }
                if !self.successors(&candidate.id, s)?.is_empty() {
                    break;
                }
                declaration = candidate
                    .parent
                    .as_ref()
                    .and_then(|id| self.operations.get(id))
                    .cloned();
            }
            if declaration.as_ref().is_none_or(|o| o.id != operation.id) {
                continue;
            }
            let mut ok = truth(true);
            for prop in block(item) {
                let expected = op(prop, 0)?;
                if expected.kind() == "wildcard" {
                    continue;
                }
                ok = ok.and(match prop.name.as_str() {
                    "type" => self.matches_type(&n.local_id, expected, s)?,
                    "type_status" => {
                        let status = if self.type_known(&n.local_id, s)? {
                            "known"
                        } else {
                            "unknown"
                        };
                        truth(status == expected.value().trim_matches('"'))
                    }
                    _ => {
                        let name = n.name.as_deref().unwrap_or("");
                        truth(if expected.kind() == "regex" {
                            s.regex(name, &query(expected))?
                        } else {
                            literal(expected)?.text().as_deref() == Some(name)
                        })
                    }
                });
            }
            if !ok.is_false() {
                let mut bindings = current.clone();
                bindings.insert(item.role.clone(), Value::Node(n));
                if !item.alias.is_empty() {
                    bindings.insert(item.alias.clone(), self.reference(operation));
                }
                return Ok(Some(Witness {
                    bindings,
                    unknown: ok.is_unknown(),
                    operation: operation.id.clone(),
                }));
            }
        }
        Ok(None)
    }
}
