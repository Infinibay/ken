use super::*;
use context::*;
use ken_program::{Operation, value::GraphValue as S};
impl Context<'_> {
    pub fn captured_reaches(
        &mut self,
        value: &str,
        targets: &BTreeSet<String>,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        if targets.contains(value)
            || self
                .producers
                .get(value)
                .is_some_and(|p| targets.contains(p))
        {
            return Ok(truth(true));
        }
        for target in targets {
            if self.has("RESULT", target, value, s)? {
                return Ok(truth(true));
            }
        }
        for target in targets {
            if self
                .entity(target, s)?
                .is_some_and(|e| matches!(e.kind.as_str(), "STORAGE" | "PARAMETER" | "MEMBER"))
                || !self.rows("LOADED_FROM", Some(target), None, s)?.is_empty()
            {
                return Ok(unknown("value_provenance_incomplete"));
            }
        }
        Ok(truth(false))
    }
    pub fn derived_from(
        &mut self,
        source: Option<&Value>,
        origins: &BTreeSet<String>,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let Some(source) = source else {
            return Ok(unknown("derivation_source_unknown"));
        };
        if source.is_unknown() {
            return Ok(source.clone());
        }
        let Value::Node(source) = source else {
            return Ok(unknown("derivation_source_unknown"));
        };
        if origins.is_empty() {
            return Ok(unknown("derivation_origin_missing"));
        }
        let mut occurrences = BTreeSet::new();
        for relation in ["TARGET", "DECLARED_TARGET", "MAY_TARGET"] {
            for f in self.rows(relation, None, Some(&source.local_id), s)? {
                occurrences.insert(f.subject.clone());
            }
        }
        let mut frontier = origins.clone();
        let mut seen = frontier.clone();
        let mut unsure = false;
        for _ in 0..8 {
            let mut reached = BTreeSet::new();
            for value in frontier {
                let mut links = self.rows("VALUE_DEPENDS_ON", Some(&value), None, s)?;
                links.extend(self.rows("ARGUMENT_VALUE_ORIGIN", Some(&value), None, s)?);
                for f in links {
                    unsure |= text(&f.attrs, "modality")? == "may";
                    reached.insert(f.object.clone());
                }
            }
            if reached.contains(&source.local_id) || !reached.is_disjoint(&occurrences) {
                return Ok(if unsure {
                    unknown("derivation_may")
                } else {
                    truth(true)
                });
            }
            frontier = reached.difference(&seen).cloned().collect();
            if frontier.is_empty() {
                return Ok(truth(false));
            }
            seen.extend(reached);
        }
        Ok(unknown("derivation_depth_exceeded"))
    }
    pub fn member_place(
        &mut self,
        expected: O<'_>,
        current: &Bindings,
        candidates: &BTreeSet<String>,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let object_role = arg(expected, 0)?.value();
        let Some(object) = node(current, object_role) else {
            return Ok(unknown("member_object_unknown"));
        };
        if expected.value() == "_" {
            for candidate in candidates {
                let mut reached = BTreeSet::from([candidate.clone()]);
                let mut frontier = vec![candidate.clone()];
                for _ in 0..8 {
                    let mut parents = BTreeSet::new();
                    for value in frontier {
                        parents.extend(self.ids("MEMBER_OF", &value, s)?);
                    }
                    if parents.contains(&object.local_id) {
                        let kinds = self.rows("ENTITY", Some(candidate), None, s)?;
                        return Ok(self.value_node(
                            candidate,
                            if kinds.len() == 1 {
                                &kinds[0].object
                            } else {
                                "MEMBER"
                            },
                        ));
                    }
                    frontier = parents.difference(&reached).cloned().collect();
                    reached.extend(parents);
                    if frontier.is_empty() {
                        break;
                    }
                }
            }
            return Ok(truth(false));
        }
        let declared = if expected.value().is_empty() && expected.len() == 2 {
            let Some(named) = node(current, arg(expected, 1)?.value()) else {
                return Ok(unknown("member_declaration_unknown"));
            };
            BTreeSet::from([named.local_id.clone()])
        } else {
            current
                .values()
                .filter_map(|v| {
                    if let Value::Node(n) = v {
                        if n.name.as_deref() == Some(expected.value()) {
                            Some(n.local_id.clone())
                        } else {
                            None
                        }
                    } else {
                        None
                    }
                })
                .collect()
        };
        for candidate in candidates {
            if !self.has("MEMBER_OF", candidate, &object.local_id, s)? {
                continue;
            }
            if self
                .ids("MEMBER_DECLARATION", candidate, s)?
                .is_disjoint(&declared)
            {
                continue;
            }
            let kinds = self.rows("ENTITY", Some(candidate), None, s)?;
            return Ok(self.value_node(
                candidate,
                if kinds.len() == 1 {
                    &kinds[0].object
                } else {
                    "MEMBER"
                },
            ));
        }
        Ok(truth(false))
    }
    pub fn index_matches(
        &mut self,
        expected: O<'_>,
        candidates: &[String],
        current: &Bindings,
        updated: &mut Bindings,
        capture_key: bool,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let Some(container) = node(current, arg(expected, 0)?.value()) else {
            return Ok(unknown("index_container_unknown"));
        };
        let key = arg(expected, 1)?;
        let bound = if key.kind() == "role" {
            node(current, key.value())
        } else {
            None
        };
        for candidate in candidates {
            if !self.has("CONTAINER", candidate, &container.local_id, s)? {
                continue;
            }
            let indices = self.rows("INDEX", Some(candidate), None, s)?;
            let passed = if key.kind() == "wildcard" {
                true
            } else if let Some(bound) = &bound {
                indices.iter().any(|f| f.object == bound.local_id)
            } else if key.kind() == "literal" {
                let wanted = literal(key)?;
                let mut hit = false;
                for f in &indices {
                    hit |= Value::Scalar(attr(&f.attrs, "text")?) == wanted;
                }
                hit
            } else if capture_key {
                if let Some(index) = indices.first() {
                    updated.insert(key.value().into(), self.value_node(&index.object, "VALUE"));
                    true
                } else {
                    false
                }
            } else {
                !indices.is_empty()
            };
            if passed {
                return Ok(truth(true));
            }
        }
        Ok(truth(false))
    }
    pub fn source_matches(
        &mut self,
        expected: O<'_>,
        actual: &Operation,
        current: &mut Bindings,
        resolved: Option<BTreeSet<String>>,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        crate::with_stack(|| self.source_match_inner(expected, actual, current, resolved, s))
    }
    fn source_match_inner(
        &mut self,
        expected: O<'_>,
        actual: &Operation,
        current: &mut Bindings,
        mut resolved: Option<BTreeSet<String>>,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        s.check()?;
        if expected.kind() == "call" && expected.value() == "read" {
            return self.source_matches(arg(arg(expected, 0)?, 0)?, actual, current, resolved, s);
        }
        if expected.kind() == "member" {
            let mut references = self.rows("BINDING_REFERENCE", Some(&actual.id), None, s)?;
            if references.is_empty() {
                references = self.rows("READ_ORIGIN", Some(&actual.id), None, s)?;
            }
            if references.len() != 1 {
                return Ok(unknown("member_reference_incomplete"));
            }
            return self.member_place(expected, current, &objects(&references), s);
        }
        if expected.kind() == "index" {
            let container = node(current, arg(expected, 0)?.value());
            if container.is_none() {
                return Ok(unknown("index_container_unknown"));
            }
            let key = arg(expected, 1)?;
            if key.kind() == "role" && node(current, key.value()).is_none() {
                return Ok(unknown("index_key_unknown"));
            }
            if !matches!(key.kind(), "role" | "literal" | "wildcard") {
                return Ok(truth(false));
            }
            let mut elements = self
                .rows("VALUE", Some(&actual.id), None, s)?
                .iter()
                .map(|f| f.object.clone())
                .collect::<Vec<_>>();
            for entity in self.entities.values() {
                if entity.kind == "VALUE"
                    && number(&entity.attrs, "start_byte")? == Some(actual.start)
                    && number(&entity.attrs, "end_byte")? == Some(actual.end)
                {
                    elements.push(entity.id.clone());
                }
            }
            let mut updated = current.clone();
            return self.index_matches(expected, &elements, current, &mut updated, false, s);
        }
        if expected.kind() == "wildcard" {
            return Ok(truth(true));
        }
        let nested = self.children.get(&actual.id).cloned().unwrap_or_default();
        if matches!(
            actual.native_kind.as_str(),
            "parenthesized_expression"
                | "expression_statement"
                | "expression_list"
                | "condition_clause"
        ) && nested.len() == 1
        {
            return self.source_matches(expected, &nested[0], current, resolved, s);
        }
        if expected.kind() == "role" {
            if !current.contains_key(expected.value()) {
                let mut referenced = self.rows("BINDING_REFERENCE", Some(&actual.id), None, s)?;
                if referenced.is_empty() {
                    referenced = self.rows("VALUE_DEPENDENCE_ORIGIN", Some(&actual.id), None, s)?;
                }
                if referenced.len() == 1 {
                    let id = &referenced[0].object;
                    let kinds = self.rows("ENTITY", Some(id), None, s)?;
                    current.insert(
                        expected.value().into(),
                        self.value_node(
                            id,
                            if kinds.len() == 1 {
                                &kinds[0].object
                            } else {
                                "VALUE"
                            },
                        ),
                    );
                    return Ok(truth(true));
                }
                if referenced.is_empty() {
                    current.insert(
                        expected.value().into(),
                        self.value_node(&actual.id, "VALUE"),
                    );
                    return Ok(truth(true));
                }
                return Ok(unknown("value_capture_incomplete"));
            }
            let value = current
                .get(expected.value())
                .cloned()
                .unwrap_or_else(|| unknown("binding_unknown"));
            if resolved.is_none() {
                let references = self.rows("BINDING_REFERENCE", Some(&actual.id), None, s)?;
                if !references.is_empty() {
                    resolved = Some(objects(&references));
                }
            }
            let captured = match &value {
                Value::Node(n) if n.kind == "VALUE" => Some(n.local_id.clone()),
                Value::Scalar(S::String(t)) => t.to_utf8(),
                _ => None,
            };
            if let Some(captured) = captured {
                let origins = self.rows("READ_ORIGIN", Some(&actual.id), None, s)?;
                if !origins.is_empty() {
                    let result = self.captured_reaches(&captured, &objects(&origins), s)?;
                    return if result.is_true()
                        && origins
                            .iter()
                            .any(|f| text(&f.attrs, "modality").ok().as_deref() != Some("must"))
                    {
                        Ok(unknown("condition_origin_may"))
                    } else {
                        Ok(result)
                    };
                }
                if actual.kind == "CALL"
                    && let Some(call) = self.call(actual)
                {
                    return self.captured_reaches(&captured, &BTreeSet::from([call.id.clone()]), s);
                }
                return if let Some(resolved) = resolved {
                    self.captured_reaches(&captured, &resolved, s)
                } else {
                    Ok(truth(false))
                };
            }
            let Value::Node(value) = value else {
                return Ok(unknown("binding_unknown"));
            };
            if let Some(resolved) = resolved {
                if resolved.contains(&value.local_id) {
                    return Ok(truth(true));
                }
                for candidate in resolved {
                    if self.has("ENTITY", &candidate, "MEMBER", s)?
                        && self.has("FLOWS_TO", &candidate, &value.local_id, s)?
                    {
                        return Ok(truth(true));
                    }
                }
                return Ok(truth(false));
            }
            if !matches!(actual.native_kind.as_str(), "identifier" | "name")
                || text(&actual.attrs, "text")? != value.name.clone().unwrap_or_default()
            {
                return Ok(truth(false));
            }
            let aliases: Vec<_> = self
                .locals
                .iter()
                .filter(|n| {
                    n.name == value.name && matches!(n.kind.as_str(), "STORAGE" | "PARAMETER")
                })
                .collect();
            return Ok(
                if aliases.len() == 1 && aliases[0].local_id == value.local_id {
                    truth(true)
                } else {
                    unknown("binding_resolution_incomplete")
                },
            );
        }
        if expected.kind() == "literal" {
            let source = text(&actual.attrs, "text")?;
            if source.is_empty() || actual.native_kind.contains("char") {
                return Ok(truth(false));
            }
            let parsed = source_literal(&source);
            let wanted = literal(expected)?;
            return Ok(truth(parsed.is_some_and(|v| same_literal(&v, &wanted))));
        }
        let operators = self.rows("OPERATOR", Some(&actual.id), None, s)?;
        let mut operator = operators
            .first()
            .map(|f| f.object.clone())
            .unwrap_or_default();
        operator = match operator.as_str() {
            "&&" => "and",
            "||" => "or",
            "!" => "not",
            "===" => "==",
            "!==" => "!=",
            _ => &operator,
        }
        .to_owned();
        if expected
            .args()
            .any(|e| e.kind() == "literal" && e.value() == "null")
        {
            operator = match operator.as_str() {
                "is" => "==",
                "is not" => "!=",
                _ => &operator,
            }
            .to_owned();
        }
        if expected.kind() == "binary"
            && expected.value() == "=="
            && expected.len() == 2
            && arg(expected, 0)?.kind() == "role"
            && arg(expected, 1)?.kind() == "literal"
            && arg(expected, 1)?.value() == "false"
            && operator == "not"
        {
            let operands = self.rows("OPERAND", Some(&actual.id), None, s)?;
            if operands.len() != 1 {
                return Ok(unknown("operand_operation_missing"));
            }
            let Some(operation) = self.operations.get(&operands[0].object).cloned() else {
                return Ok(unknown("operand_operation_missing"));
            };
            let matched = self.source_matches(arg(expected, 0)?, &operation, current, None, s)?;
            if matched.is_false() {
                return Ok(matched);
            }
            let selected = node(current, arg(expected, 0)?.value());
            let producer = selected
                .as_ref()
                .and_then(|n| self.producers.get(&n.local_id).cloned());
            let producer = if let Some(p) = producer {
                Some(p)
            } else if let Some(n) = selected {
                self.rows("RESULT", None, Some(&n.local_id), s)?
                    .first()
                    .map(|f| f.subject.clone())
            } else {
                None
            };
            if let Some(producer) = producer
                && self.boolean_result(&producer, s)?
            {
                return Ok(matched);
            }
            return Ok(unknown("boolean_result_unproven"));
        }
        let expected_operands = if expected.kind() == "call" && expected.value() == "binary" {
            let (left, wanted, right) =
                crate::body_check::binary_parts(expected).map_err(|e| invalid(e.message))?;
            let choices = if wanted.kind() == "list" {
                wanted.args().collect()
            } else {
                vec![wanted]
            };
            if operator.is_empty()
                || (wanted.kind() != "wildcard"
                    && !choices.iter().any(|e| {
                        literal(*e).ok().and_then(|v| v.text()).as_deref() == Some(&operator)
                    }))
            {
                return Ok(truth(false));
            }
            vec![left, right]
        } else {
            if operator != expected.value() {
                return Ok(truth(false));
            }
            expected.args().collect()
        };
        let mut operands = self.rows("OPERAND", Some(&actual.id), None, s)?;
        operands.sort_by_key(|f| number(&f.attrs, "position").ok().flatten().unwrap_or(0));
        if operands.len() != expected_operands.len() {
            return Ok(truth(false));
        }
        let mut result = truth(true);
        for (position, (expected, f)) in expected_operands.into_iter().zip(operands).enumerate() {
            let Some(operation) = self.operations.get(&f.object).cloned() else {
                return Ok(unknown("operand_operation_missing"));
            };
            let mut origins = vec![];
            if consumes_value(expected, current) {
                for value in resolved.as_ref().into_iter().flatten() {
                    for origin in self.rows("VALUE_DEPENDS_ON", Some(value), None, s)? {
                        if number(&origin.attrs, "position")? == Some(position as i64)
                            && text(&origin.attrs, "basis")? == "evaluated-expression-inputs/1"
                        {
                            origins.push(origin);
                        }
                    }
                }
            }
            let mut matched = self.source_matches(
                expected,
                &operation,
                current,
                if origins.is_empty() {
                    None
                } else {
                    Some(objects(&origins))
                },
                s,
            )?;
            if matched.is_true()
                && origins
                    .iter()
                    .any(|f| text(&f.attrs, "modality").ok().as_deref() != Some("must"))
            {
                matched = unknown("expression_origin_may");
            }
            result = result.and(matched);
        }
        Ok(result)
    }
    pub fn landed_place(
        &mut self,
        value: Option<&Value>,
        s: &mut dyn BodyServices,
    ) -> Result<String> {
        let Some(Value::Node(value)) = value else {
            return Ok(String::new());
        };
        if value.kind != "VALUE" {
            return Ok(String::new());
        }
        let Some(call) = self.producers.get(&value.local_id).cloned() else {
            return Ok(String::new());
        };
        let placed = self
            .rows("ASSIGNED_FROM", None, Some(&call), s)?
            .iter()
            .map(|f| f.subject.clone())
            .collect::<BTreeSet<_>>();
        Ok(if placed.len() == 1 {
            placed.into_iter().next().unwrap()
        } else {
            String::new()
        })
    }
    pub fn iteration_value_at(
        &mut self,
        value: &str,
        binding: &str,
        point: &Operation,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let Some((loop_op, original)) = self.iteration.get(value).cloned() else {
            return Ok(truth(false));
        };
        if binding != original {
            return Ok(truth(false));
        }
        if !supported(&self.rows("STORAGE_WRITE_STATUS", Some(&original), None, s)?) {
            return Ok(unknown("iteration_binding_writes_unknown"));
        }
        for candidate in self.ordered.clone() {
            if candidate.start <= loop_op.start || candidate.start >= point.start {
                continue;
            }
            if self.has("ASSIGNMENT_TARGET", &candidate.id, &original, s)?
                || self.has("ITERATION_BINDING", &candidate.id, &original, s)?
            {
                return Ok(truth(false));
            }
        }
        Ok(truth(true))
    }
    pub fn callable_reaches(
        &mut self,
        callable: &str,
        value: &str,
        point: &Operation,
        s: &mut dyn BodyServices,
    ) -> Result<bool> {
        fn region(context: &Context<'_>, operation: &Operation) -> Option<String> {
            let mut op = operation;
            let mut seen = BTreeSet::new();
            while seen.insert(op.id.clone()) {
                if matches!(
                    op.native_kind.as_str(),
                    "block" | "statement_block" | "compound_statement" | "statement_list"
                ) {
                    return Some(op.id.clone());
                }
                op = context.operations.get(op.parent.as_deref().unwrap_or(""))?;
            }
            None
        }
        let block = region(self, point);
        let mut before = point.start;
        let mut value = value.to_owned();
        let mut seen = BTreeSet::new();
        while value != callable {
            s.check()?;
            if seen.len() >= 16 || !seen.insert(value.clone()) {
                return Ok(false);
            }
            let loaded = self.rows("LOADED_FROM", Some(&value), None, s)?;
            if loaded.len() == 1 {
                value = loaded[0].object.clone();
                continue;
            }
            let counts = self.rows("STORAGE_WRITE_COUNT", Some(&value), None, s)?;
            if counts.len() != 1
                || !supported(&self.rows("STORAGE_WRITE_STATUS", Some(&value), None, s)?)
            {
                return Ok(false);
            }
            let Some(count) = counts[0].object.parse::<usize>().ok() else {
                return Ok(false);
            };
            let mut candidates = vec![];
            for op in self.operations.values().cloned().collect::<Vec<_>>() {
                if op.owner == point.owner && self.has("ASSIGNMENT_TARGET", &op.id, &value, s)? {
                    candidates.push(op);
                }
            }
            if candidates.len() != count {
                return Ok(false);
            }
            let earlier: Vec<_> = candidates
                .into_iter()
                .filter(|op| op.end < before)
                .collect();
            if earlier.is_empty()
                || block.is_none()
                || earlier.iter().any(|op| region(self, op) != block)
            {
                return Ok(false);
            }
            let write = earlier.into_iter().max_by_key(|o| o.end).unwrap();
            let values = self.rows("ASSIGNMENT_VALUE", Some(&write.id), None, s)?;
            if values.len() != 1 {
                return Ok(false);
            }
            value = values[0].object.clone();
            before = write.start;
        }
        Ok(true)
    }
    fn boolean_result(&mut self, selected: &str, s: &mut dyn BodyServices) -> Result<bool> {
        let mut call = selected.to_owned();
        if self.entity(&call, s)?.is_none_or(|e| e.kind != "CALL") {
            let mut candidates = BTreeSet::new();
            for f in self.rows("SYNTAX_NODE", None, Some(&call), s)? {
                if self
                    .entity(&f.subject, s)?
                    .is_some_and(|e| e.kind == "CALL")
                {
                    candidates.insert(f.subject.clone());
                }
            }
            if candidates.len() != 1 {
                return Ok(false);
            }
            call = candidates.into_iter().next().unwrap();
        }
        if !self.rows("MAY_TARGET", Some(&call), None, s)?.is_empty() {
            return Ok(false);
        }
        let mut targets = self.ids("TARGET", &call, s)?;
        targets.extend(self.ids("DECLARED_TARGET", &call, s)?);
        if targets.len() == 1 {
            let target = targets.into_iter().next().unwrap();
            let Some(entity) = self.entity(&target, s)?.filter(|e| e.kind == "CALLABLE") else {
                return Ok(false);
            };
            for key in ["async_", "async", "generator"] {
                if attr(&entity.attrs, key)?.truthy() {
                    return Ok(false);
                }
            }
            if !self.rows("HAS_YIELD", Some(&target), None, s)?.is_empty() {
                return Ok(false);
            }
            let language = text(&entity.attrs, "language")?;
            let refs = self.ids("RETURN_TYPE_REF", &target, s)?;
            if refs.len() != 1 {
                return Ok(false);
            }
            let reference = refs.into_iter().next().unwrap();
            let primitive = match language.as_str() {
                "java" | "typescript" => "boolean",
                "csharp" | "cpp" | "go" | "rust" | "python" => "bool",
                _ => return Ok(false),
            };
            if self.ids("TYPE_KIND", &reference, s)? != BTreeSet::from(["bool".into()])
                || self.ids("TYPE_NATIVE", &reference, s)? != BTreeSet::from([primitive.into()])
            {
                return Ok(false);
            }
            if matches!(language.as_str(), "go" | "python")
                && self.shadowed_bool(&entity.path, s)?
            {
                return Ok(false);
            }
            return Ok(true);
        }
        if !targets.is_empty() {
            return Ok(false);
        }
        let bindings = self.ids("CALLEE_VALUE", &call, s)?;
        if bindings.len() != 1 {
            return Ok(false);
        }
        let binding = bindings.into_iter().next().unwrap();
        let Some(entity) = self.entity(&binding, s)?.filter(|e| e.kind == "PARAMETER") else {
            return Ok(false);
        };
        let language = text(&entity.attrs, "language")?;
        if !matches!(language.as_str(), "go" | "typescript") {
            return Ok(false);
        }
        let counts = self.rows("STORAGE_WRITE_COUNT", Some(&binding), None, s)?;
        if counts.len() != 1
            || counts[0].object != "0"
            || !supported(&self.rows("STORAGE_WRITE_STATUS", Some(&binding), None, s)?)
        {
            return Ok(false);
        }
        let operations = self.unit_operations(s)?;
        let mut children = BTreeMap::<String, Vec<Op>>::new();
        for operation in &operations {
            children
                .entry(operation.parent.clone().unwrap_or_default())
                .or_default()
                .push(operation.clone());
        }
        let start = number(&entity.attrs, "start_byte")?;
        let end = number(&entity.attrs, "end_byte")?;
        let native = text(&entity.attrs, "native_kind")?;
        let declarations = operations
            .iter()
            .filter(|op| Some(op.start) == start && Some(op.end) == end && op.native_kind == native)
            .cloned()
            .collect::<Vec<_>>();
        if declarations.len() != 1 {
            return Ok(false);
        }
        let annotations = children
            .get(&declarations[0].id)
            .into_iter()
            .flatten()
            .filter(|o| o.role == "type")
            .cloned()
            .collect::<Vec<_>>();
        if annotations.len() != 1 {
            return Ok(false);
        }
        fn transparent(op: Op, children: &BTreeMap<String, Vec<Op>>) -> Option<Op> {
            let mut op = op;
            let mut seen = BTreeSet::new();
            while matches!(
                op.native_kind.as_str(),
                "type_annotation" | "parenthesized_type"
            ) {
                if !seen.insert(op.id.clone()) {
                    return None;
                }
                let items = children.get(&op.id)?;
                if items.len() != 1 {
                    return None;
                }
                op = items[0].clone();
            }
            Some(op)
        }
        let Some(function) = transparent(annotations[0].clone(), &children)
            .filter(|o| o.native_kind == "function_type")
        else {
            return Ok(false);
        };
        let role = if language == "go" {
            "result"
        } else {
            "return_type"
        };
        let results = children
            .get(&function.id)
            .into_iter()
            .flatten()
            .filter(|o| o.role == role)
            .cloned()
            .collect::<Vec<_>>();
        if results.len() != 1 {
            return Ok(false);
        }
        let Some(result) = transparent(results[0].clone(), &children) else {
            return Ok(false);
        };
        if language == "typescript" {
            return Ok(result.native_kind == "predefined_type"
                && text(&result.attrs, "text")? == "boolean");
        }
        Ok(!self.shadowed_bool(&entity.path, s)?
            && result.native_kind == "type_identifier"
            && text(&result.attrs, "text")? == "bool")
    }
    fn unit_operations(&self, s: &mut dyn BodyServices) -> Result<Vec<Op>> {
        let mut operations = vec![];
        self.graph.operations_checked(
            &super::super::OperationProbe::default(),
            &mut || s.check(),
            &mut |o| {
                operations.push(o);
                Ok(())
            },
        )?;
        Ok(operations)
    }
    fn shadowed_bool(&mut self, path: &str, s: &mut dyn BodyServices) -> Result<bool> {
        let mut shadowed = false;
        let probe = super::super::SourceProbe {
            name: Some("bool".into()),
            ..Default::default()
        };
        self.graph
            .source_scan(&probe, &mut || s.check(), &mut |n| {
                if n.name.as_deref() == Some("bool") && n.path == path {
                    shadowed = true;
                }
                Ok(())
            })?;
        if shadowed {
            return Ok(true);
        }
        let operations = self.unit_operations(s)?;
        for operation in &operations {
            if !matches!(operation.native_kind.as_str(), "type_spec" | "type_alias") {
                continue;
            }
            let named = operations
                .iter()
                .filter(|o| o.parent.as_deref() == Some(&operation.id) && o.role == "name")
                .any(|o| text(&o.attrs, "text").ok().as_deref() == Some("bool"));
            if named
                && self
                    .entity(&operation.owner, s)?
                    .is_some_and(|e| e.path == path)
            {
                return Ok(true);
            }
        }
        Ok(false)
    }
}
fn consumes_value(e: O<'_>, current: &Bindings) -> bool {
    (e.kind() == "role" && node(current, e.value()).is_some_and(|n| n.kind == "VALUE"))
        || e.args().any(|a| consumes_value(a, current))
}
fn same_literal(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Scalar(S::Int(a)), Value::Scalar(S::Int(b))) => a == b,
        (Value::Scalar(S::Float(a)), Value::Scalar(S::Float(b))) => a == b,
        (Value::Scalar(S::Bool(a)), Value::Scalar(S::Bool(b))) => a == b,
        (Value::Scalar(S::Null), Value::Scalar(S::Null)) => true,
        (Value::Scalar(S::String(a)), Value::Scalar(S::String(b))) => a == b,
        _ => false,
    }
}
fn source_literal(text: &str) -> Option<Value> {
    match text {
        "True" | "true" => Some(truth(true)),
        "False" | "false" => Some(truth(false)),
        "None" | "null" | "nil" | "undefined" => Some(Value::null()),
        _ => {
            if let Some(text) = crate::literal_strings::decode(text) {
                return Some(Value::Scalar(S::String(text)));
            }
            let trimmed = text.trim();
            match trimmed {
                "True" => return Some(truth(true)),
                "False" => return Some(truth(false)),
                "None" => return Some(Value::null()),
                _ => (),
            }
            let unsigned = trimmed.strip_prefix(['+', '-']).unwrap_or(trimmed);
            if unsigned.is_empty() {
                return None;
            }
            let radix = ["0x", "0X", "0o", "0O", "0b", "0B"]
                .iter()
                .any(|prefix| unsigned.starts_with(prefix));
            if radix {
                if !unsigned
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '_')
                {
                    return None;
                }
            } else {
                for (i, c) in unsigned.char_indices() {
                    if c.is_ascii_digit() || matches!(c, '_' | '.' | 'e' | 'E') {
                        continue;
                    }
                    if matches!(c, '+' | '-')
                        && i > 0
                        && matches!(unsigned.as_bytes()[i - 1], b'e' | b'E')
                    {
                        continue;
                    }
                    return None;
                }
            }
            match trimmed.parse::<py_literal::Value>().ok()? {
                py_literal::Value::Integer(n) => Some(Value::integer(n)),
                py_literal::Value::Float(n) => Some(Value::Scalar(S::Float(n))),
                _ => None,
            }
        }
    }
}
