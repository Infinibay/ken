//! Calls preserve callee values, explicit arguments and conservative API shapes.
use super::*;
const MAP_READS: &[&str] = &[
    "get",
    "Get",
    "fetch",
    "Fetch",
    "lookup",
    "Lookup",
    "getOrDefault",
    "GetValueOrDefault",
    "find",
];
const MAP_WRITES: &[&str] = &[
    "put",
    "Put",
    "set",
    "Set",
    "add",
    "Add",
    "insert",
    "Insert",
    "store",
    "Store",
    "emplace",
    "Emplace",
    "try_emplace",
    "insert_or_assign",
    "AddOrUpdate",
    "GetOrAdd",
    "setdefault",
    "setDefault",
];
impl<'a, 's> Unit<'a, 's> {
    fn loop_binding(&self, node: SyntaxNode<'a>) -> Option<SyntaxNode<'a>> {
        let mut n = field(Some(node), &["left", "name", "pattern", "declarator"])?;
        while matches!(
            n.kind(),
            "reference_declarator"
                | "pointer_declarator"
                | "init_declarator"
                | "variable_declarator"
        ) {
            n = *n.named_children().first()?;
        }
        Some(n)
    }
    fn argument_value(&mut self, node: SyntaxNode<'a>, scope: &str, cls: &str) -> String {
        let mut value = if matches!(node.kind(), "keyword_argument" | "argument") {
            field(Some(node), &["value", "expression"])
        } else {
            None
        };
        if value.is_none() && node.kind() == "argument" {
            value = node.named_children().last().copied();
        }
        self.value(value.or(Some(node)), scope, cls)
    }
    fn pair_arguments(&self, node: SyntaxNode<'a>) -> Option<Vec<SyntaxNode<'a>>> {
        if !vocabulary().calls.contains(node.kind()) {
            return None;
        }
        let callee = field(Some(node), &["function", "name", "type"]);
        let spelling = self.text(callee.or(Some(node)));
        if !spelling.contains("pair") {
            return None;
        }
        let items = node
            .field("arguments")?
            .named_children()
            .into_iter()
            .filter(|n| !matches!(n.kind(), "comment" | "line_comment" | "block_comment"))
            .collect::<Vec<_>>();
        (items.len() >= 2).then(|| items[..2].to_vec())
    }
    pub(super) fn call_facts(&mut self, node: SyntaxNode<'a>, scope: &str, cls: &str) {
        let ev = self.evidence(node);
        let kind = node.kind();
        let cid = self.value(Some(node), scope, cls);
        if self.language == Language::Go && kind == "composite_literal" {
            for item in node
                .field("body")
                .map(|n| n.named_children())
                .unwrap_or_default()
            {
                if item.kind() != "keyed_element" {
                    continue;
                }
                let (Some(mut key), Some(mut initial)) = (item.field("key"), item.field("value"))
                else {
                    continue;
                };
                if key.kind() == "literal_element" && key.named_children().len() == 1 {
                    key = key.named_children()[0];
                }
                if initial.kind() == "literal_element" && initial.named_children().len() == 1 {
                    initial = initial.named_children()[0];
                }
                if key.kind() != "identifier" {
                    continue;
                }
                let id = source::operation_id(&self.ir.path, item);
                self.add(&cid, "HAS_INITIALIZER", &id, &ev, json!({}));
                self.add(&id, "FIELD_NAME", &self.text(Some(key)), &ev, json!({}));
                let value = self.value(Some(initial), scope, cls);
                self.add(&id, "STORES_VALUE", &value, &ev, json!({}));
            }
        }
        if self.language == Language::Rust && kind == "struct_expression" {
            for item in node
                .field("body")
                .map(|n| n.named_children())
                .unwrap_or_default()
            {
                let mut key = item.field("field");
                let mut initial = item.field("value");
                if item.kind() == "shorthand_field_initializer" {
                    key = item
                        .named_children()
                        .into_iter()
                        .find(|n| n.kind() == "identifier");
                    initial = key;
                }
                let (Some(key), Some(initial)) = (key, initial) else {
                    continue;
                };
                if !matches!(key.kind(), "field_identifier" | "identifier") {
                    continue;
                }
                let attributed = item
                    .previous_named_sibling()
                    .is_some_and(|n| n.kind() == "attribute_item")
                    || item
                        .named_children()
                        .iter()
                        .any(|n| n.kind() == "attribute_item");
                let attrs = if attributed {
                    json!({"modality":"may"})
                } else {
                    json!({})
                };
                let id = source::operation_id(&self.ir.path, item);
                self.add(
                    &cid,
                    "HAS_INITIALIZER",
                    &id,
                    &self.evidence(item),
                    attrs.clone(),
                );
                self.add(
                    &id,
                    "FIELD_NAME",
                    &self.text(Some(key)),
                    &self.evidence(item),
                    attrs.clone(),
                );
                let value = self.value(Some(initial), scope, cls);
                self.add(&id, "STORES_VALUE", &value, &self.evidence(item), attrs);
            }
        }
        self.call_nodes.insert(cid.clone(), node);
        let mut function = field(Some(node), &["function", "constructor", "type", "name"]);
        if kind == "constructor_initializer" {
            function = node
                .children()
                .into_iter()
                .find(|n| matches!(n.kind(), "base" | "this"));
        }
        let mut receiver_node = node.field("object");
        if receiver_node.is_none() && self.language == Language::Ruby {
            function = function.or_else(|| node.field("method"));
            receiver_node = node.field("receiver");
        }
        let mut name = self.text(function);
        if self.language == Language::Cpp
            && let Some(function) = function.filter(|n| n.kind() == "qualified_identifier")
            && let Some(qualifier) = function.field("scope")
        {
            let parameter = self.text(Some(qualifier));
            let mut ancestor = node.parent();
            while let Some(a) = ancestor {
                if a.kind() == "template_declaration" {
                    let parameters = a.field("parameters");
                    let declared = parameters
                        .map(|n| n.named_children())
                        .unwrap_or_default()
                        .into_iter()
                        .filter(|n| {
                            matches!(
                                n.kind(),
                                "type_parameter_declaration"
                                    | "variadic_type_parameter_declaration"
                            )
                        })
                        .flat_map(|n| n.named_children())
                        .filter(|n| n.kind() == "type_identifier")
                        .map(|n| self.text(Some(n)))
                        .collect::<BTreeSet<_>>();
                    if declared.contains(&parameter) {
                        if let Some(decl) = a
                            .named_children()
                            .into_iter()
                            .find_map(|n| self.declarations.nodes.get(&n.id()).cloned())
                        {
                            self.add(
                                &cid,
                                "TYPE_PARAMETER_RECEIVER",
                                &parameter,
                                &ev,
                                json!({"owner":decl,"basis":"lexical-template-qualifier"}),
                            );
                            self.add(&cid, "TYPE_PARAMETER_OWNER", &decl, &ev, json!({}));
                        }
                        break;
                    }
                }
                ancestor = a.parent();
            }
        }
        if let Some(f) = function.filter(|n| vocabulary().members.contains(n.kind())) {
            (receiver_node, name) = self.member_parts(f);
        } else if let Some(f) = function.filter(|n| n.kind() == "conditional_access_expression") {
            let parts = f.named_children();
            if parts.len() == 2 {
                receiver_node = Some(parts[0]);
                name = self.text(Some(parts[1])).trim_start_matches('.').into();
            }
        }
        let receiver = if receiver_node.is_some() {
            self.value(receiver_node, scope, cls)
        } else {
            String::new()
        };
        if let Some(receiver_node) = receiver_node.filter(|_| !cls.is_empty()) {
            let native = (matches!(
                self.language,
                Language::Java | Language::JavaScript | Language::TypeScript
            ) && receiver_node.kind() == "super")
                || (self.language == Language::CSharp && self.text(Some(receiver_node)) == "base");
            let base_function = receiver_node.field("function");
            let base_arguments = receiver_node.field("arguments");
            let python = self.language == Language::Python
                && receiver_node.kind() == "call"
                && base_function
                    .is_some_and(|f| f.kind() == "identifier" && self.text(Some(f)) == "super")
                && base_arguments.is_some_and(|a| a.named_children().is_empty())
                && !self.bindings.names.keys().any(|(owner, name)| {
                    name == "super" && (scope == owner || scope.starts_with(&format!("{owner}/")))
                });
            if (native || python)
                && self.positions.contains_key(scope)
                && self.entity_ref(scope).kind == "CALLABLE"
                && !self.flag(scope, "static")
                && scope
                    .rsplit_once("/CALLABLE:")
                    .is_some_and(|(owner, _)| owner == cls)
            {
                self.set(&cid, "base_dispatch_owner", cls.into());
            }
        }
        self.add(scope, "HAS_CALL", &cid, &ev, json!({}));
        self.add(&cid, "CALLEE_NAME", &name, &ev, json!({}));
        if let Some(callee) = function
            .map(|f| self.unwrap(f))
            .filter(|f| vocabulary().calls.contains(f.kind()))
        {
            let value = self.value(Some(callee), scope, cls);
            self.add(&cid, "INVOKES_RESULT_OF", &value, &ev, json!({}));
        }
        let mut binding = function;
        while let Some(n) = binding.filter(|n| n.kind() == "parenthesized_expression") {
            let inner = n
                .named_children()
                .into_iter()
                .filter(|n| !n.kind().contains("comment"))
                .collect::<Vec<_>>();
            if inner.len() != 1 {
                break;
            }
            binding = Some(inner[0]);
        }
        if receiver_node.is_none()
            && let Some(b) = binding.filter(|n| n.kind() == "identifier")
        {
            if let Some(value) = self.resolve(&self.text(Some(b)), scope) {
                self.add(&cid, "CALLEE_VALUE", &value, &ev, json!({}));
            }
        } else if let Some(b) = binding.filter(|n| {
            vocabulary().members.contains(n.kind()) || super::semantics::index_kind(n.kind())
        }) {
            let value = self.value(Some(b), scope, cls);
            self.add(&cid, "CALLEE_VALUE", &value, &ev, json!({}));
        }
        let looping = self.enclosing(node, &vocabulary().loops);
        if self.language == Language::Go
            && let Some(looping) = looping
        {
            let clause = looping
                .named_children()
                .into_iter()
                .find(|n| n.kind() == "range_clause");
            let bindings = clause.and_then(|n| n.field("left"));
            let iterable = clause.and_then(|n| n.field("right"));
            let slots = bindings.map(|n| n.named_children()).unwrap_or_default();
            let invoked = receiver_node.or(function);
            if let (Some(first), Some(iterable)) = (slots.first().copied(), iterable)
                && self.text(Some(first)) != "_"
                && self.value(Some(first), scope, cls) == self.value(invoked, scope, cls)
            {
                let value = self.value(Some(iterable), scope, cls);
                self.add(scope, "ITERATES_KEYS_CALLS", &value, &ev, json!({}));
            }
            if slots.len() == 2
                && iterable.is_some()
                && self.text(Some(slots[1])) != "_"
                && self.value(Some(slots[1]), scope, cls) == self.value(invoked, scope, cls)
            {
                let collection = self.value(iterable, scope, cls);
                self.add(
                    scope,
                    "ITERATES_CALLS",
                    &collection,
                    &ev,
                    json!({"name":name}),
                );
                self.add(&cid, "ITERATED_CALL", &collection, &ev, json!({}));
            }
        }
        self.extend(&cid,json!({"name":name,"owner":scope,"construction":matches!(kind,"new_expression"|"object_creation_expression"|"struct_expression"|"composite_literal")}));
        if !name.is_empty() {
            self.entity_mut(&cid).name = name.clone();
        }
        if !receiver.is_empty() {
            self.add(&cid, "RECEIVER", &receiver, &ev, json!({}));
            self.add(scope, "DELEGATES_TO", &receiver, &ev, json!({"name":name}));
            if let Some(looping) = looping {
                let iterable = field(Some(looping), &["right", "value", "iterable"]);
                let binding = self.loop_binding(looping);
                if iterable.is_some()
                    && binding.is_some()
                    && self.value(binding, scope, cls) == receiver
                {
                    let value = self.value(iterable, scope, cls);
                    self.add(scope, "ITERATES_CALLS", &value, &ev, json!({"name":name}));
                    let value = self.value(iterable, scope, cls);
                    self.add(&cid, "ITERATED_CALL", &value, &ev, json!({}));
                }
            }
            if self.enclosing(node, &vocabulary().branches).is_some() {
                self.add(
                    scope,
                    "CONDITIONAL_DELEGATION",
                    &receiver,
                    &ev,
                    json!({"name":name}),
                );
            }
        }
        if let Some(looping) = looping.filter(|_| function.is_some() && receiver.is_empty()) {
            let iterable = field(Some(looping), &["right", "value", "iterable"]);
            let binding = self.loop_binding(looping);
            if iterable.is_some()
                && binding.is_some()
                && self.value(binding, scope, cls) == self.value(function, scope, cls)
            {
                let value = self.value(iterable, scope, cls);
                self.add(
                    scope,
                    "ITERATES_CALLS",
                    &value,
                    &ev,
                    json!({"name":"<callback>"}),
                );
            }
        }
        let arguments = node
            .field("arguments")
            .map(|n| n.named_children())
            .unwrap_or_default();
        for (position, arg) in arguments.iter().copied().enumerate() {
            let spelling = self.text(Some(arg));
            let kind = if spelling.starts_with("**") {
                "spread_named"
            } else if spelling.starts_with("...")
                || (matches!(self.language, Language::Python | Language::Ruby)
                    && spelling.starts_with('*'))
            {
                "spread_positional"
            } else if arg.kind() == "keyword_argument"
                || (arg.kind() == "argument" && arg.field("name").is_some())
            {
                "named"
            } else {
                "positional"
            };
            let mut value_node = if matches!(arg.kind(), "keyword_argument" | "argument") {
                field(Some(arg), &["value", "expression"])
            } else {
                None
            };
            if value_node.is_none() && arg.kind() == "argument" {
                value_node = arg.named_children().last().copied();
            }
            if value_node.is_none() && kind.starts_with("spread") {
                value_node = arg.named_children().last().copied();
            }
            let value = self.value(value_node.or(Some(arg)), scope, cls);
            self.add(
                &cid,
                "ARGUMENT",
                &value,
                &ev,
                json!({"position":position,"kind":kind,"name":self.text(arg.field("name"))}),
            );
            if self.language == Language::Python
                && name == "list"
                && receiver_node.is_none()
                && function.is_some_and(|n| n.kind() == "identifier")
                && self.resolve("list", scope).is_none()
                && self.block_local("list", scope, node).is_none()
                && arguments.len() == 1
                && kind == "positional"
            {
                self.add(
                    &cid,
                    "SHALLOW_COPY_SOURCE",
                    &value,
                    &ev,
                    json!({"model":"python-builtin-list"}),
                );
            }
            if self.language == Language::Python
                && receiver.is_empty()
                && name == "next"
                && position == 0
                && self.resolve("next", scope).is_none()
            {
                self.add(
                    &cid,
                    "ADVANCES_ITERATOR",
                    &value,
                    &ev,
                    json!({"model":"python-next"}),
                );
            }
            if !receiver.is_empty()
                && matches!(
                    name.as_str(),
                    "append" | "add" | "push" | "push_back" | "Add"
                )
                && position == 0
            {
                self.add(
                    &cid,
                    "INSERTS_INTO",
                    &receiver,
                    &ev,
                    json!({"model":"collection-api-shape"}),
                );
                self.add(&cid, "INSERTED_VALUE", &value, &ev, json!({}));
                self.add(scope, "WRITES_ELEMENT", &receiver, &ev, json!({}));
            }
            if receiver.is_empty()
                && self.language == Language::Go
                && name == "append"
                && position == 0
                && arguments.len() == 2
            {
                self.add(
                    &cid,
                    "INSERTS_INTO",
                    &value,
                    &ev,
                    json!({"model":"collection-api-shape"}),
                );
                let inserted = self.value(Some(arguments[1]), scope, cls);
                self.add(&cid, "INSERTED_VALUE", &inserted, &ev, json!({}));
                self.add(scope, "WRITES_ELEMENT", &value, &ev, json!({}));
            }
            if !receiver.is_empty() && value == format!("{cls}/THIS") {
                self.add(
                    scope,
                    "PASSES_SELF_TO",
                    &receiver,
                    &ev,
                    json!({"name":name}),
                );
            }
        }
        if !receiver.is_empty() && !receiver.contains("/CALLABLE:") {
            let supplied = arguments
                .iter()
                .map(|&arg| self.argument_value(arg, scope, cls))
                .collect::<Vec<_>>();
            if MAP_READS.contains(&name.as_str()) && (1..=2).contains(&supplied.len()) {
                for subject in [scope, cid.as_str()] {
                    self.add(
                        subject,
                        "LOOKS_UP",
                        &receiver,
                        &ev,
                        json!({"model":"map-api-shape"}),
                    );
                }
                self.add(
                    &cid,
                    "CONTAINER",
                    &receiver,
                    &ev,
                    json!({"model":"map-api-shape"}),
                );
                self.add(
                    &cid,
                    "INDEX",
                    &supplied[0],
                    &ev,
                    json!({"model":"map-api-shape"}),
                );
                if node
                    .parent()
                    .is_some_and(|n| matches!(n.kind(), "return_statement" | "return_expression"))
                {
                    self.add(
                        scope,
                        "RETURNS_LOOKUP",
                        &receiver,
                        &ev,
                        json!({"model":"map-api-shape"}),
                    );
                }
            }
            if MAP_WRITES.contains(&name.as_str()) {
                let mut written = supplied;
                if written.len() == 1
                    && let Some(pair) = self.pair_arguments(arguments[0])
                {
                    written = pair
                        .into_iter()
                        .map(|arg| self.argument_value(arg, scope, cls))
                        .collect();
                }
                if written.len() >= 2 {
                    for subject in [scope, cid.as_str()] {
                        self.add(
                            subject,
                            "WRITES_ELEMENT",
                            &receiver,
                            &ev,
                            json!({"model":"map-api-shape"}),
                        );
                    }
                    self.add(
                        &cid,
                        "CONTAINER",
                        &receiver,
                        &ev,
                        json!({"model":"map-api-shape"}),
                    );
                    self.add(
                        &cid,
                        "INDEX",
                        &written[0],
                        &ev,
                        json!({"model":"map-api-shape"}),
                    );
                    self.add(
                        &cid,
                        "STORES_VALUE",
                        &written[1],
                        &ev,
                        json!({"model":"map-api-shape"}),
                    );
                }
            }
        }
    }
}
