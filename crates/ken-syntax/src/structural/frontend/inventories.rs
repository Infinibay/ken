//! Source-local construction, field declarations and hazards retain explicit coverage.
use super::*;
pub(super) fn behavior_relation(relation: &str) -> bool {
    matches!(
        relation,
        "HAS_CALL"
            | "DELEGATES_TO"
            | "CONDITIONAL_DELEGATION"
            | "ITERATES_CALLS"
            | "ITERATED_CALL"
            | "ITERATES_KEYS_CALLS"
            | "PASSES_SELF_TO"
            | "RETURNS"
            | "RETURNS_SELF"
            | "RETURNS_LOOKUP"
            | "READS"
            | "WRITES"
            | "ASSIGNMENT_TARGET"
            | "ASSIGNMENT_VALUE"
            | "GUARDS_WRITE"
            | "WRITES_ELEMENT"
            | "STORES_VALUE"
            | "INSERTS_INTO"
            | "INSERTED_VALUE"
    )
}
fn modifiers(node: SyntaxNode<'_>) -> BTreeSet<String> {
    let mut tokens = BTreeSet::new();
    for child in node.children() {
        if matches!(
            child.kind(),
            "modifier" | "accessibility_modifier" | "modifiers"
        ) {
            tokens.extend(
                child
                    .children()
                    .into_iter()
                    .filter(|c| !c.is_named())
                    .map(|c| c.kind().to_owned()),
            );
        } else if matches!(child.kind(), "static" | "get" | "set") {
            tokens.insert(child.kind().into());
        }
    }
    tokens
}
impl<'a, 's> Unit<'a, 's> {
    pub(super) fn callable_access(&self, node: SyntaxNode<'a>, owner_kind: &str) -> Value {
        if !matches!(
            self.language,
            Language::Java | Language::CSharp | Language::TypeScript
        ) {
            return json!({});
        }
        let tokens = modifiers(node);
        let access = tokens
            .iter()
            .filter(|s| matches!(s.as_str(), "public" | "private" | "protected" | "internal"))
            .cloned()
            .collect::<BTreeSet<_>>();
        let valid = access.len() <= 1
            || (self.language == Language::CSharp
                && (access == ["private".into(), "protected".into()].into_iter().collect()
                    || access
                        == ["protected".into(), "internal".into()]
                            .into_iter()
                            .collect()));
        let visibility = if !access.is_empty() {
            access.iter().cloned().collect::<Vec<_>>().join(" ")
        } else if owner_kind == "INTERFACE" {
            "public".into()
        } else {
            match self.language {
                Language::Java => "package",
                Language::CSharp => "private",
                _ => "public",
            }
            .into()
        };
        let name = node.field("name");
        let constructor = node.kind() == "constructor_declaration"
            || (self.language == Language::TypeScript
                && matches!(node.kind(), "method_definition" | "method_signature")
                && name.is_some_and(|n| {
                    n.kind() == "property_identifier" && self.text(Some(n)) == "constructor"
                })
                && !tokens.contains("get")
                && !tokens.contains("set"));
        json!({"visibility":if valid{visibility}else{"unknown".into()},"visibility_basis":if access.is_empty(){"language-default"}else{"explicit-modifier"},"visibility_status":if valid&&!node.has_error(){"supported"}else{"unsupported"},"instance_constructor":constructor&&!tokens.contains("static")})
    }
    pub(super) fn constructor_inventory(&mut self) {
        if !matches!(
            self.language,
            Language::Java | Language::CSharp | Language::TypeScript
        ) {
            return;
        }
        let mut members = BTreeMap::<String, BTreeSet<String>>::new();
        for fact in &self.ir.facts {
            if fact.relation == "HAS_METHOD" {
                members
                    .entry(fact.subject.clone())
                    .or_default()
                    .insert(fact.object.clone());
            }
        }
        for (id, node) in self.declarations.types.clone() {
            if self.entity_ref(&id).kind != "CLASS" {
                continue;
            }
            let constructors = members
                .get(&id)
                .into_iter()
                .flatten()
                .filter(|method| self.flag(method, "instance_constructor"))
                .cloned()
                .collect::<Vec<_>>();
            let mut supported = matches!(
                node.kind(),
                "class_declaration" | "abstract_class_declaration" | "class"
            ) && !node.has_error()
                && self.ir.diagnostics.is_empty();
            if self.language == Language::CSharp {
                supported &= !modifiers(node).contains("partial")
                    && !node
                        .named_children()
                        .iter()
                        .any(|c| c.kind() == "parameter_list");
            }
            supported &= constructors
                .iter()
                .all(|c| self.attr(c, "visibility_status") == "supported");
            let private = constructors
                .iter()
                .filter(|c| self.attr(c, "visibility") == "private")
                .count();
            self.add(&id,"CONSTRUCTOR_INVENTORY",if supported{"supported"}else{"unsupported"},&format!("{}:{}",self.ir.path,self.entity_ref(&id).line),json!({"explicit":constructors.len(),"private":private,"other":constructors.len()-private,"basis":"declared-instance-constructors"}));
        }
    }
    pub(super) fn record_field(&mut self, node: SyntaxNode<'a>, target: &str, initialized: bool) {
        let parent = node.parent();
        let mut annotation = node.field("type");
        match self.language {
            Language::Java => {
                if node.kind() != "variable_declarator"
                    || parent.is_none_or(|p| p.kind() != "field_declaration")
                {
                    return;
                }
                annotation = parent.and_then(|p| p.field("type"));
            }
            Language::CSharp => {
                if node.kind() != "variable_declarator"
                    || parent.is_none_or(|p| {
                        p.kind() != "variable_declaration"
                            || p.parent().is_none_or(|g| g.kind() != "field_declaration")
                    })
                {
                    return;
                }
                annotation = parent.and_then(|p| p.field("type"));
            }
            Language::JavaScript | Language::TypeScript => {
                if !matches!(node.kind(), "field_definition" | "public_field_definition")
                    || parent.is_none_or(|p| p.kind() != "class_body")
                {
                    return;
                }
                let name = field(Some(node), &["property", "name"]);
                if name.is_none_or(|n| {
                    !matches!(
                        n.kind(),
                        "property_identifier" | "private_property_identifier"
                    )
                }) {
                    return;
                }
            }
            Language::Python => {
                if node.kind() != "assignment"
                    || parent.is_none_or(|p| {
                        p.kind() != "expression_statement"
                            || p.parent().is_none_or(|g| {
                                g.kind() != "block"
                                    || g.parent().is_none_or(|c| c.kind() != "class_definition")
                            })
                    })
                    || node.field("left").is_none_or(|n| n.kind() != "identifier")
                {
                    return;
                }
            }
            _ => return,
        }
        let mut native = trim(
            self.text(annotation)
                .strip_prefix(':')
                .unwrap_or(&self.text(annotation)),
        )
        .to_owned();
        if self.language == Language::Java {
            native.push_str(&self.text(node.field("dimensions")));
        }
        let mut mode = if initialized { "explicit" } else { "implicit" };
        let tokens = node
            .children()
            .into_iter()
            .filter(|c| !c.is_named())
            .map(|c| c.kind())
            .collect::<BTreeSet<_>>();
        if (self.language == Language::Python && !initialized)
            || (self.language == Language::TypeScript
                && (tokens.contains("declare") || tokens.contains("abstract")))
        {
            mode = "absent";
        }
        let mut parameters = BTreeSet::new();
        let mut ancestor = node.parent();
        while let Some(a) = ancestor {
            for child in a.named_children() {
                if matches!(child.kind(), "type_parameter_list" | "type_parameters") {
                    for parameter in child.named_children() {
                        let name = self.text(parameter.field("name"));
                        parameters.insert(if name.is_empty() {
                            self.text(Some(parameter))
                        } else {
                            name
                        });
                    }
                }
            }
            ancestor = a.parent();
        }
        self.add(target,"FIELD_DECLARATION",&source::operation_id(&self.ir.path,node),&self.evidence(node),json!({"initialization":mode,"native_type":native,"type_parameters":parameters,"syntax_status":if node.has_error(){"unsupported"}else{"supported"}}));
    }
    fn hazard(&mut self, node: SyntaxNode<'a>, owner: &str, rule: &str) {
        let event = self.entity(
            "HAZARD",
            &format!("{rule}:{}", node.start_byte()),
            owner,
            node,
            json!({}),
        );
        let ev = self.evidence(node);
        self.add(&event, "HAS_HAZARD", rule, &ev, json!({}));
        self.add(&event, "OWNED_BY", owner, &ev, json!({}));
    }
    pub(super) fn syntax_effects(&mut self) {
        let finally = ["finally_clause".into()].into_iter().collect();
        for (node, _) in source::descendants_with_roles(self.root) {
            let owner = self.owners.nodes[&node.id()].clone();
            let kind = node.kind();
            let evidence = self.evidence(node);
            if self.language == Language::Python
                && matches!(kind, "default_parameter" | "typed_default_parameter")
                && node
                    .field("value")
                    .is_some_and(|n| matches!(n.kind(), "list" | "dictionary" | "set"))
            {
                self.hazard(node, &owner, "mutable-default-argument");
            }
            if kind == "except_clause"
                && node.field("value").is_none()
                && !node
                    .named_children()
                    .iter()
                    .any(|n| n.kind() == "as_pattern")
                && node.named_children().iter().any(|n| n.kind() == "block")
                && node.named_children().len() == 1
            {
                self.hazard(node, &owner, "bare-except");
            }
            if matches!(kind, "except_clause" | "catch_clause") {
                let body = node.field("body").or_else(|| {
                    node.named_children()
                        .into_iter()
                        .find(|n| matches!(n.kind(), "block" | "statement_block"))
                });
                if body.is_some_and(|b| {
                    b.named_children().iter().all(|n| {
                        matches!(n.kind(), "pass_statement" | "comment" | "empty_statement")
                    })
                }) {
                    self.hazard(node, &owner, "swallowed-exception");
                }
            }
            if matches!(kind, "return_statement" | "return_expression")
                && self.enclosing(node, &finally).is_some()
            {
                self.hazard(node, &owner, "return-in-finally");
            }
            if matches!(
                kind,
                "block" | "statement_block" | "compound_statement" | "statement_list"
            ) {
                let mut terminated = false;
                for child in node.named_children() {
                    if terminated
                        && child.kind() != "comment"
                        && !vocabulary().functions.contains(child.kind())
                    {
                        let event = self.entity(
                            "HAZARD",
                            &format!("unreachable:{}", child.start_byte()),
                            &owner,
                            child,
                            json!({}),
                        );
                        self.add(
                            &event,
                            "HAS_HAZARD",
                            "unreachable-statement",
                            &self.evidence(child),
                            json!({}),
                        );
                    }
                    if matches!(
                        child.kind(),
                        "return_statement"
                            | "return_expression"
                            | "throw_statement"
                            | "raise_statement"
                            | "break_statement"
                            | "continue_statement"
                    ) {
                        terminated = true;
                    }
                }
            }
            if vocabulary().assignments.contains(kind)
                && let (Some(left), Some(right)) = (node.field("left"), node.field("right"))
                && left.kind() == "identifier"
                && right.kind() == "identifier"
                && self.text(Some(left)) == self.text(Some(right))
            {
                self.hazard(node, &owner, "self-assignment");
            }
            if matches!(kind, "binary_expression" | "comparison_operator") {
                let mut op = self.text(node.field("operator"));
                if op.is_empty() {
                    op = node
                        .children()
                        .into_iter()
                        .filter(|n| !n.is_named())
                        .map(|n| n.kind())
                        .collect::<Vec<_>>()
                        .join(" ");
                }
                if matches!(self.language, Language::JavaScript | Language::TypeScript)
                    && matches!(op.as_str(), "==" | "===" | "!=" | "!==")
                    && node
                        .named_children()
                        .iter()
                        .any(|n| self.text(Some(*n)) == "NaN")
                    && self.resolve("NaN", &owner).is_none()
                {
                    self.hazard(node, &owner, "nan-equality");
                }
            }
            if self.language == Language::Python
                && kind == "assert_statement"
                && node
                    .named_children()
                    .first()
                    .is_some_and(|n| n.kind() == "tuple")
            {
                self.hazard(node, &owner, "tuple-assertion");
            }
            if kind == "go_statement" {
                self.add(
                    &owner,
                    "SPAWNS_CONTEXT",
                    &format!("{}::goroutine:{}", self.ir.path, node.start_byte()),
                    &evidence,
                    json!({"api":"go"}),
                );
            }
            if matches!(kind, "async_block" | "async_expression") {
                self.add(
                    &owner,
                    "HAS_ASYNC_SCOPE",
                    &format!("{}::async:{}", self.ir.path, node.start_byte()),
                    &evidence,
                    json!({}),
                );
            }
        }
        self.ir.capabilities.insert("syntax_hazards".into());
    }
}
