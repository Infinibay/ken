//! Statement, iteration, assignment and return facts over declared lexical bindings.
use super::*;
pub(super) fn index_kind(kind: &str) -> bool {
    matches!(
        kind,
        "subscript"
            | "subscript_expression"
            | "element_access_expression"
            | "index_expression"
            | "array_access"
            | "element_reference"
    )
}
impl<'a, 's> Unit<'a, 's> {
    pub(super) fn semantics(&mut self, node: SyntaxNode<'a>) {
        let scope = self.owners.nodes[&node.id()].clone();
        let cls = self.owners.classes[&node.id()].clone();
        let kind = node.kind();
        let ev = self.evidence(node);
        let callable =
            self.positions.contains_key(&scope) && self.entity_ref(&scope).kind == "CALLABLE";
        if kind == "field_initializer" && self.language == Language::Cpp {
            self.record_cpp_initializer(node, &scope, &cls);
        }
        if kind == "package_clause"
            && self.language == Language::Go
            && let Some(name) = node.named_children().first()
        {
            let module = self.module.clone();
            self.set(&module, "package", self.text(Some(*name)).into());
        }
        if callable
            && (vocabulary().members.contains(kind) || matches!(kind, "identifier" | "name"))
        {
            let referenced = if vocabulary().members.contains(kind) {
                Some(self.value(Some(node), &scope, &cls))
            } else {
                self.resolve(&self.text(Some(node)), &scope)
            };
            if let Some(entity) = referenced.filter(|id| {
                self.positions.contains_key(id)
                    && matches!(
                        self.entity_ref(id).kind.as_str(),
                        "STORAGE" | "PARAMETER" | "MEMBER"
                    )
            }) {
                self.add(
                    &source::operation_id(&self.ir.path, node),
                    "BINDING_REFERENCE",
                    &entity,
                    &ev,
                    json!({"basis":"lexical-reference"}),
                );
            }
        }
        if vocabulary().loops.contains(kind) {
            self.iteration_facts(node, &scope, &cls);
        }
        if matches!(
            kind,
            "if_statement"
                | "if_expression"
                | "ternary_expression"
                | "conditional_expression"
                | "elif_clause"
        ) {
            self.condition_facts(node, &scope, &cls);
        }
        if let Some((container, index)) = self.go_indexed_call(node, &scope, &cls) {
            let call = self.value(Some(node), &scope, &cls);
            let entry = self.entity("VALUE", "indexed-callee", &call, node, json!({}));
            self.add(&scope, "HAS_CALL", &call, &ev, json!({}));
            self.add(&call, "CALLEE_VALUE", &entry, &ev, json!({}));
            self.add(&entry, "CONTAINER", &container, &ev, json!({}));
            self.add(&entry, "INDEX", &index, &ev, json!({}));
            let value = self.value(node.field("operand"), &scope, &cls);
            self.add(
                &call,
                "ARGUMENT",
                &value,
                &ev,
                json!({"position":0,"kind":"positional"}),
            );
        }
        if matches!(kind, "arrow_function" | "lambda")
            && let Some(body) = node.field("body").filter(|b| b.kind() != "statement_block")
        {
            let value = self.value(Some(body), &scope, &cls);
            self.add(&scope, "RETURNS", &value, &ev, json!({}));
            let value = self.value(Some(body), &scope, &cls);
            self.add(&scope, "BODY_VALUE", &value, &ev, json!({}));
        }
        if kind == "lambda_expression"
            && let Some(body) = node
                .field("body")
                .filter(|b| !matches!(b.kind(), "block" | "compound_statement" | "statement_block"))
        {
            let value = self.value(Some(body), &scope, &cls);
            self.add(&scope, "BODY_VALUE", &value, &ev, json!({}));
        }
        if kind == "update_expression"
            && callable
            && let Some(operand) = field(Some(node), &["argument", "operand"])
                .or_else(|| node.named_children().first().copied())
        {
            let target = self.value(Some(operand), &scope, &cls);
            self.add(&scope, "READS", &target, &ev, json!({}));
            self.add(&scope, "WRITES", &target, &ev, json!({}));
        }
        if kind == "identifier" && callable {
            let value = self.resolve(&self.text(Some(node)), &scope);
            let parent = node.parent();
            let declared = parent.map(source::declared_names).unwrap_or_default();
            let defining = parent.is_some_and(|p| {
                vocabulary().functions.contains(p.kind())
                    || declared.iter().any(|n| n.id() == node.id())
                    || (vocabulary().assignments.contains(p.kind())
                        && field(Some(p), &["left", "name", "pattern"])
                            .is_some_and(|n| n.id() == node.id()))
            });
            if let Some(value) = value.filter(|id| {
                !defining && matches!(self.entity_ref(id).kind.as_str(), "STORAGE" | "PARAMETER")
            }) {
                self.add(&scope, "READS", &value, &ev, json!({}));
            }
        }
        if vocabulary().members.contains(kind) && callable {
            let value = self.value(Some(node), &scope, &cls);
            if self.positions.contains_key(&value) && self.entity_ref(&value).kind == "STORAGE" {
                self.add(&scope, "READS", &value, &ev, json!({}));
            }
        }
        if matches!(
            kind,
            "augmented_assignment" | "augmented_assignment_expression" | "compound_assignment_expr"
        ) && let (Some(left), Some(right)) = (node.field("left"), node.field("right"))
        {
            let id = source::operation_id(&self.ir.path, node);
            let target = self.value(Some(left), &scope, &cls);
            self.add(&id, "ASSIGNMENT_TARGET", &target, &ev, json!({}));
            let value = self.value(Some(right), &scope, &cls);
            self.add(&id, "ASSIGNMENT_VALUE", &value, &ev, json!({}));
            if callable {
                self.add(&scope, "READS", &target, &ev, json!({}));
                self.add(&scope, "WRITES", &target, &ev, json!({}));
            }
        }
        if vocabulary().assignments.contains(kind) && self.assignment_facts(node, &scope, &cls) {
            return;
        }
        if vocabulary().calls.contains(kind) {
            self.call_facts(node, &scope, &cls);
        }
        if index_kind(kind) {
            self.index_facts(node, &scope, &cls);
        }
        if matches!(kind, "return_statement" | "return_expression") {
            let value_node = node
                .named_children()
                .first()
                .copied()
                .or_else(|| node.children().into_iter().find(|n| n.kind() == "this"));
            let value = self.value(value_node, &scope, &cls);
            if value_node.is_some() {
                self.add(
                    &source::operation_id(&self.ir.path, node),
                    "RETURN_OPERAND",
                    &value,
                    &ev,
                    json!({}),
                );
            }
            self.add(&scope, "RETURNS", &value, &ev, json!({}));
            if value == format!("{cls}/THIS") {
                self.add(&scope, "RETURNS_SELF", &cls, &ev, json!({}));
            }
        }
        if self.language == Language::Rust
            && kind == "block"
            && node
                .parent()
                .is_some_and(|p| vocabulary().functions.contains(p.kind()))
        {
            self.rust_tail(node, &scope, &cls);
        }
        if matches!(
            kind,
            "import_from_statement" | "import_statement" | "import_declaration" | "use_declaration"
        ) {
            let module = self.module.clone();
            self.add(
                &module,
                "IMPORT_SYNTAX",
                &self.text(Some(node)),
                &ev,
                json!({"language":self.language.as_str()}),
            );
        }
        if kind == "package_declaration"
            && self.language == Language::Java
            && let Some(m) = word_capture(r"package\s+([\w.]+)\s*;", &self.text(Some(node)))
        {
            let module = self.module.clone();
            self.set(&module, "package", m[1].into());
        }
        if kind == "export_statement" {
            let module = self.module.clone();
            self.add(
                &module,
                "EXPORT_SYNTAX",
                &self.text(Some(node)),
                &ev,
                json!({}),
            );
        }
    }
    fn iteration_facts(&mut self, node: SyntaxNode<'a>, scope: &str, cls: &str) {
        let iteration = if self.language == Language::Go {
            node.named_children()
                .into_iter()
                .find(|n| n.kind() == "range_clause")
                .unwrap_or(node)
        } else {
            node
        };
        let foreach = matches!(
            node.kind(),
            "for"
                | "for_in_statement"
                | "enhanced_for_statement"
                | "for_each_statement"
                | "foreach_statement"
                | "for_expression"
                | "for_range_loop"
        ) || (self.language == Language::Python && node.kind() == "for_statement")
            || iteration.kind() == "range_clause";
        if !foreach {
            return;
        }
        let left = field(Some(iteration), &["left", "name", "pattern", "declarator"]);
        let mut right = field(Some(iteration), &["right", "value", "iterable"]);
        if self.language == Language::Ruby && right.is_some_and(|n| n.kind() == "in") {
            let parts = right
                .unwrap()
                .named_children()
                .into_iter()
                .filter(|n| !n.kind().contains("comment"))
                .collect::<Vec<_>>();
            right = (parts.len() == 1).then(|| parts[0]);
        }
        let (Some(left), Some(right), Some(body)) = (left, right, node.field("body")) else {
            return;
        };
        let id = source::operation_id(&self.ir.path, node);
        let ev = self.evidence(node);
        let value = self.value(Some(right), scope, cls);
        self.add(&id, "ITERATION_SOURCE", &value, &ev, json!({}));
        self.add(
            &id,
            "ITERATION_BODY",
            &source::operation_id(&self.ir.path, body),
            &ev,
            json!({}),
        );
        let bindings = if self.language == Language::Go && left.kind() == "expression_list" {
            left.named_children()
        } else {
            vec![left]
        };
        for (position, mut binding) in bindings.into_iter().enumerate() {
            if self.language == Language::Cpp {
                loop {
                    let mut nested = binding.field("declarator");
                    if nested.is_none() && binding.kind() == "reference_declarator" {
                        let parts = binding
                            .named_children()
                            .into_iter()
                            .filter(|n| !n.kind().contains("comment"))
                            .collect::<Vec<_>>();
                        if parts.len() == 1 {
                            nested = Some(parts[0]);
                        }
                    }
                    let Some(next) = nested else {
                        break;
                    };
                    binding = next;
                }
            }
            if !matches!(binding.kind(), "identifier" | "field_identifier")
                || (self.text(Some(binding)) == "_"
                    && matches!(self.language, Language::Go | Language::Rust))
            {
                continue;
            }
            let keyed = matches!(self.language, Language::JavaScript | Language::TypeScript)
                && node.children().iter().any(|n| n.kind() == "in");
            let role = if self.language == Language::Go && position == 0 {
                "first"
            } else if keyed {
                "key"
            } else {
                "value"
            };
            let value = self.value(Some(binding), scope, cls);
            self.add(
                &id,
                "ITERATION_BINDING",
                &value,
                &ev,
                json!({"position":position,"role":role}),
            );
        }
    }
    fn assignment_facts(&mut self, node: SyntaxNode<'a>, scope: &str, cls: &str) -> bool {
        let kind = node.kind();
        let ev = self.evidence(node);
        if self.language == Language::Cpp && scope == cls && kind == "field_declaration" {
            for (id, target, initial) in self
                .declarations
                .field_initializers
                .get(&node.id())
                .cloned()
                .unwrap_or_default()
            {
                let value = self.value(Some(initial), scope, cls);
                self.add(
                    &id,
                    "ASSIGNMENT_TARGET",
                    &target,
                    &ev,
                    json!({"basis":"field-initializer"}),
                );
                self.add(
                    &id,
                    "ASSIGNMENT_VALUE",
                    &value,
                    &ev,
                    json!({"basis":"field-initializer"}),
                );
                self.add(&target, "ASSIGNED_FROM", &value, &ev, json!({}));
                self.add(&value, "FLOWS_TO", &target, &ev, json!({}));
                self.add(scope, "WRITES", &target, &ev, json!({}));
                if value == "NULL" {
                    self.add(&target, "INITIALIZED_AS", "NULL", &ev, json!({}));
                }
            }
            return true;
        }
        let (left, mut right) = source::declaration_parts(node);
        if self.language == Language::Rust && kind == "let_declaration" && self.text(left) == "_" {
            if let Some(right) = right {
                let value = self.value(Some(right), scope, cls);
                self.add(
                    &source::operation_id(&self.ir.path, node),
                    "DISCARDS_RESULT",
                    &value,
                    &ev,
                    json!({"basis":"rust-wildcard"}),
                );
            }
            return true;
        }
        if right.is_none() && self.language == Language::CSharp && kind == "variable_declarator" {
            let children = node.children();
            if let Some(equal) = children.iter().position(|n| n.kind() == "=") {
                right = children[equal + 1..]
                    .iter()
                    .copied()
                    .find(|n| n.is_named() && n.kind() != "comment");
            }
        }
        if kind == "field_declaration"
            && (left.is_none() || left.is_some_and(|n| n.kind() == "variable_declarator"))
        {
            return true;
        }
        let Some(left) = left else {
            return false;
        };
        let left = self.unwrap(left);
        if left.kind() == "function_declarator" {
            return true;
        }
        if matches!(self.language, Language::JavaScript | Language::TypeScript)
            && scope == cls
            && matches!(kind, "field_definition" | "public_field_definition")
            && matches!(
                left.kind(),
                "property_identifier" | "private_property_identifier"
            )
        {
            let key = (scope.into(), self.text(Some(left)));
            if self
                .bindings
                .names
                .get(&key)
                .is_some_and(|id| self.entity_ref(id).kind != "STORAGE")
            {
                self.bindings.names.remove(&key);
            }
            self.storage(&self.text(Some(left)), scope, left, false);
        }
        let go = self.language == Language::Go
            && matches!(kind, "var_declaration" | "const_declaration");
        if left.kind() == "identifier"
            && self.entity_ref(scope).kind == "CALLABLE"
            && ((self.language == Language::Python && kind == "assignment")
                || (matches!(
                    self.language,
                    Language::JavaScript | Language::TypeScript | Language::Java | Language::CSharp
                ) && kind == "variable_declarator")
                || go)
        {
            let name = self.text(Some(left));
            let wrapper = node.parent();
            let block = self.block_scope(left);
            let block_declaration = wrapper.is_some_and(|p| match self.language {
                Language::JavaScript | Language::TypeScript => p.kind() == "lexical_declaration",
                Language::Java => p.kind() == "local_variable_declaration",
                Language::CSharp => p.kind() == "variable_declaration",
                _ => false,
            });
            if let Some(block) = block.filter(|b| {
                b.parent()
                    .is_none_or(|p| !vocabulary().functions.contains(p.kind()))
                    && (go || block_declaration)
                    && self
                        .bindings
                        .names
                        .contains_key(&(scope.into(), name.clone()))
            }) {
                self.block_storage(&name, scope, block, left);
            } else {
                self.storage(&name, scope, left, false);
            }
        }
        let target = self.value(Some(left), scope, cls);
        if self.positions.contains_key(&target) {
            self.set(&target, "declared", true.into());
        }
        if self.language == Language::Cpp
            && scope != cls
            && self.positions.contains_key(&target)
            && node
                .parent()
                .filter(|p| p.kind() == "declaration")
                .is_some_and(|p| {
                    p.children().iter().any(|c| {
                        c.kind() == "storage_class_specifier" && self.text(Some(*c)) == "static"
                    })
                })
        {
            self.set(&target, "static", true.into());
            self.update_declared_static(scope, &target, true, false);
        }
        if scope == cls && self.positions.contains_key(&target) {
            let declaration = node
                .parent()
                .filter(|p| p.kind() == "field_declaration")
                .unwrap_or(node);
            let mut is_static = self.language == Language::Python
                || ken_text::unicode::contains_word(&self.text(Some(declaration)), "static");
            if self.language == Language::CSharp {
                let mut declaration = node;
                while matches!(
                    declaration.kind(),
                    "variable_declarator" | "variable_declaration"
                ) && declaration.parent().is_some()
                {
                    declaration = declaration.parent().unwrap();
                }
                is_static = declaration.kind() == "field_declaration"
                    && declaration.named_children().iter().any(|c| {
                        c.kind() == "modifier"
                            && matches!(self.text(Some(*c)).as_str(), "static" | "const")
                    });
                if declaration.kind() == "event_field_declaration" {
                    self.set(&target, "event", true.into());
                    self.add(
                        cls,
                        "DECLARES_EVENT",
                        &target,
                        &ev,
                        json!({"name":self.text(Some(left))}),
                    );
                }
            }
            if self.language == Language::Python && right.is_some() {
                self.set(&target, "class_initialized", true.into());
            }
            if self.language == Language::Python && right.is_none() && node.field("type").is_some()
            {
                is_static = self.flag(&target, "class_initialized")
                    || word_capture(r"ClassVar\s*\[", &self.text(node.field("type"))).is_some();
            }
            self.set(&target, "static", is_static.into());
            self.update_declared_static(cls, &target, is_static, true);
        }
        if let Some(annotation) = node
            .field("type")
            .or_else(|| node.parent().and_then(|p| p.field("type")))
        {
            self.annotate(&target, annotation, &ev);
        }
        if scope == cls && self.positions.contains_key(&target) {
            self.record_field(node, &target, right.is_some());
        }
        if let Some(right) = right {
            let value = self.value(Some(right), scope, cls);
            let id = source::operation_id(&self.ir.path, node);
            self.add(&id, "ASSIGNMENT_TARGET", &target, &ev, json!({}));
            self.add(&id, "ASSIGNMENT_VALUE", &value, &ev, json!({}));
            self.add(&target, "ASSIGNED_FROM", &value, &ev, json!({}));
            self.add(&value, "FLOWS_TO", &target, &ev, json!({}));
            self.add(scope, "WRITES", &target, &ev, json!({}));
            if value == "NULL" {
                self.add(&target, "INITIALIZED_AS", "NULL", &ev, json!({}));
            }
            if let Some(branch) = self.enclosing(node, &vocabulary().branches)
                && let Some(condition) = branch.field("condition")
            {
                let mut guarded = false;
                for (n, _) in source::descendants_with_roles(condition) {
                    if (vocabulary().members.contains(n.kind()) || n.kind() == "identifier")
                        && self.value(Some(n), scope, cls) == target
                    {
                        guarded = true;
                        break;
                    }
                }
                if guarded {
                    self.add(&target, "GUARDS_WRITE", scope, &ev, json!({}));
                }
            }
        }
        false
    }
    fn index_facts(&mut self, node: SyntaxNode<'a>, scope: &str, cls: &str) {
        let ev = self.evidence(node);
        let base = field(
            Some(node),
            &["value", "object", "argument", "operand", "array"],
        )
        .or_else(|| node.named_children().first().copied());
        let container = self.value(base, scope, cls);
        self.add(scope, "LOOKS_UP", &container, &ev, json!({}));
        if node
            .parent()
            .is_some_and(|p| matches!(p.kind(), "return_statement" | "return_expression"))
        {
            self.add(scope, "RETURNS_LOOKUP", &container, &ev, json!({}));
        }
        if node.parent().is_some_and(|p| {
            vocabulary().assignments.contains(p.kind())
                && p.field("left").is_some_and(|n| n.id() == node.id())
        }) {
            self.add(scope, "WRITES_ELEMENT", &container, &ev, json!({}));
        }
        let mut key = field(Some(node), &["index", "subscript", "indices"]);
        if let Some(keys) = key.filter(|n| {
            matches!(
                n.kind(),
                "bracketed_argument_list" | "subscript_argument_list"
            )
        }) {
            let keys = keys
                .named_children()
                .into_iter()
                .filter(|n| !matches!(n.kind(), "comment" | "line_comment" | "block_comment"))
                .collect::<Vec<_>>();
            key = (keys.len() == 1).then(|| self.unwrap(keys[0]));
        }
        if key.is_none()
            && self.language == Language::Rust
            && node.kind() == "index_expression"
            && node.named_children().len() == 2
        {
            key = Some(node.named_children()[1]);
        }
        if let Some(key) = key {
            let access = self.value(Some(node), scope, cls);
            self.add(&access, "CONTAINER", &container, &ev, json!({}));
            let value = self.value(Some(key), scope, cls);
            self.add(&access, "INDEX", &value, &ev, json!({}));
        }
        let mut assignment = node.parent();
        if assignment.is_some_and(|n| n.kind() == "expression_list") {
            assignment = assignment.and_then(|n| n.parent());
        }
        let left = assignment.and_then(|n| n.field("left"));
        if let (Some(assignment), Some(left), Some(key)) = (assignment, left, key)
            && vocabulary().assignments.contains(assignment.kind())
            && self.unwrap(left).id() == node.id()
        {
            let id = source::operation_id(&self.ir.path, assignment);
            self.add(&id, "WRITES_ELEMENT", &container, &ev, json!({}));
            let value = self.value(Some(key), scope, cls);
            self.add(&id, "INDEX", &value, &ev, json!({}));
            if let Some(right) = field(Some(assignment), &["right", "value"])
                && assignment.children().iter().any(|n| n.kind() == "=")
            {
                let value = self.value(Some(right), scope, cls);
                self.add(&id, "STORES_VALUE", &value, &ev, json!({}));
            }
        }
    }
    fn rust_tail(&mut self, node: SyntaxNode<'a>, scope: &str, cls: &str) {
        let children = node.named_children();
        let Some(last) = children
            .iter()
            .rev()
            .copied()
            .find(|n| !n.kind().contains("comment"))
        else {
            return;
        };
        if matches!(
            last.kind(),
            "expression_statement" | "let_declaration" | "return_expression"
        ) {
            return;
        }
        for statement in children {
            if statement.kind() == "let_declaration"
                && let Some(binding) = source::declaration_parts(statement).0
            {
                let binding = self.unwrap(binding);
                let name = self.text(Some(binding));
                if binding.kind() == "identifier"
                    && !self
                        .bindings
                        .names
                        .contains_key(&(scope.into(), name.clone()))
                {
                    self.storage(&name, scope, binding, false);
                }
            }
        }
        let value = self.value(Some(last), scope, cls);
        self.add(scope, "RETURNS", &value, &self.evidence(last), json!({}));
        if !matches!(
            last.kind(),
            "if_expression" | "match_expression" | "block" | "loop_expression"
        ) {
            let id = source::operation_id(&self.ir.path, last);
            let index = self.operation_by_id[&id];
            let expression = self.ir.operations[index].clone();
            let return_id = format!("{id}/implicit-return");
            let mut returning = expression.clone();
            returning.id = return_id.clone();
            returning.kind = "RETURN".into();
            returning.native_kind = "implicit_return".into();
            returning.owner = scope.into();
            returning
                .attrs
                .insert("synthetic".into(), to_raw_value(&true).unwrap());
            self.ir.operations.push(returning);
            self.ir.operations[index].parent = Some(return_id.clone());
            self.ir.operations[index].role = "value".into();
            self.add(
                &return_id,
                "RETURN_OPERAND",
                &value,
                &self.evidence(last),
                json!({}),
            );
        }
        if value == format!("{cls}/THIS") {
            self.add(scope, "RETURNS_SELF", cls, &self.evidence(last), json!({}));
        }
    }
}
