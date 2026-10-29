//! Lexical storage and expression values keep binding identity separate from syntax.
use super::*;

enum ValueStep<'a> {
    Ready(String),
    Alias(Option<SyntaxNode<'a>>),
    Assertion {
        node: SyntaxNode<'a>,
        inner: SyntaxNode<'a>,
    },
    Member {
        node: SyntaxNode<'a>,
        object: Option<SyntaxNode<'a>>,
        member: String,
    },
    Copy {
        node: SyntaxNode<'a>,
        collection: String,
        inner: SyntaxNode<'a>,
    },
    Expression {
        node: SyntaxNode<'a>,
        value: String,
        operator: String,
        operands: Vec<SyntaxNode<'a>>,
    },
    Cast {
        node: SyntaxNode<'a>,
        value: String,
        operand: SyntaxNode<'a>,
    },
}
enum ValueTask<'a> {
    Enter(Option<SyntaxNode<'a>>),
    Assertion(SyntaxNode<'a>),
    Member {
        node: SyntaxNode<'a>,
        member: String,
    },
    Copy {
        node: SyntaxNode<'a>,
        collection: String,
    },
    Operand {
        node: SyntaxNode<'a>,
        value: String,
        operator: String,
        position: usize,
    },
    Cast {
        node: SyntaxNode<'a>,
        value: String,
    },
}

impl<'a, 's> Unit<'a, 's> {
    pub(super) fn block_scope(&self, node: SyntaxNode<'a>) -> Option<SyntaxNode<'a>> {
        self.lexical_blocks.get(&node.id()).copied().flatten()
    }
    pub(super) fn block_local(
        &self,
        name: &str,
        scope: &str,
        node: SyntaxNode<'a>,
    ) -> Option<String> {
        let mut current = self.block_scope(node);
        while let Some(block) = current {
            if let Some(id) = self
                .bindings
                .blocks
                .get(&(scope.into(), block.id(), name.into()))
            {
                return Some(id.clone());
            }
            current = self.block_scope(block);
        }
        None
    }
    pub(super) fn block_storage(
        &mut self,
        name: &str,
        scope: &str,
        block: SyntaxNode<'a>,
        node: SyntaxNode<'a>,
    ) -> String {
        let key = (scope.into(), block.id(), name.into());
        if let Some(id) = self.bindings.blocks.get(&key) {
            return id.clone();
        }
        let id = format!("{scope}/STORAGE:{name}@{}", block.start_byte());
        if !self.positions.contains_key(&id) {
            self.insert(Entity{id:id.clone(),kind:"STORAGE".into(),name:name.into(),path:self.ir.path.clone(),line:(node.start_point()[0]+1)as i64,end_line:(node.end_point()[0]+1)as i64,attrs:attributes(json!({"static":false,"native_kind":node.kind(),"language":self.language.as_str(),"start_byte":node.start_byte(),"end_byte":node.end_byte(),"block_scope":block.id()}))});
            self.add(
                &id,
                "IS",
                "STORAGE",
                &self.evidence(node),
                json!({"static":false}),
            );
        }
        self.bindings.blocks.insert(key, id.clone());
        self.add(
            scope,
            "DECLARES",
            &id,
            &self.evidence(node),
            json!({"kind":"storage","name":name,"static":false}),
        );
        id
    }
    pub(super) fn storage(
        &mut self,
        name: &str,
        scope: &str,
        node: SyntaxNode<'a>,
        is_static: bool,
    ) -> String {
        if let Some(id) = self.bindings.names.get(&(scope.into(), name.into())) {
            return id.clone();
        }
        let id = self.entity("STORAGE", name, scope, node, json!({"static":is_static}));
        self.bindings
            .names
            .insert((scope.into(), name.into()), id.clone());
        self.add(
            scope,
            "DECLARES",
            &id,
            &self.evidence(node),
            json!({"kind":"storage","name":name,"static":is_static}),
        );
        if self.declarations.type_ids.contains(scope) {
            self.add(
                scope,
                "HAS_FIELD",
                &id,
                &self.evidence(node),
                json!({"name":name,"static":is_static}),
            );
            let mut declaration = node;
            while !matches!(
                declaration.kind(),
                "field_declaration" | "public_field_definition" | "property_declaration"
            ) && declaration.parent().is_some()
            {
                if vocabulary().functions.contains(declaration.kind())
                    || self.declarations.types[self.declarations.type_positions[scope]]
                        .1
                        .id()
                        == declaration.id()
                {
                    break;
                }
                declaration = declaration.parent().unwrap();
            }
            if matches!(
                declaration.kind(),
                "field_declaration" | "public_field_definition" | "property_declaration"
            ) {
                let mut access = self.callable_access(declaration, &self.entity_ref(scope).kind);
                access
                    .as_object_mut()
                    .unwrap()
                    .retain(|k, _| k.starts_with("visibility"));
                self.extend(&id, access);
            }
        }
        id
    }
    pub(super) fn member_parts(&self, node: SyntaxNode<'a>) -> (Option<SyntaxNode<'a>>, String) {
        let mut object = field(
            Some(node),
            &["object", "expression", "operand", "argument", "value"],
        );
        let member = field(Some(node), &["attribute", "property", "field", "name"]);
        if object.is_none() {
            object = node
                .children()
                .first()
                .filter(|n| n.kind() == "this")
                .copied();
        }
        (object, self.text(member))
    }
    pub(super) fn go_indexed_call(
        &self,
        node: SyntaxNode<'a>,
        scope: &str,
        cls: &str,
    ) -> Option<(String, String)> {
        if self.language != Language::Go
            || node.kind() != "type_conversion_expression"
            || cls.is_empty()
        {
            return None;
        }
        let generic = node.field("type")?;
        let qualified = generic.field("type")?;
        if generic.kind() != "generic_type"
            || qualified.kind() != "qualified_type"
            || self.bindings.receivers.get(scope) != Some(&self.text(qualified.field("package")))
        {
            return None;
        }
        let container = self
            .bindings
            .names
            .get(&(cls.into(), self.text(qualified.field("name"))))?
            .clone();
        let arguments = generic.field("type_arguments")?;
        let args = arguments.named_children();
        if args.len() != 1 {
            return None;
        }
        let annotation = self
            .declarations
            .annotations
            .iter()
            .find(|(subject, _, _)| subject == &container)
            .map(|(_, name, _)| name.as_str())
            .unwrap_or("");
        if !rx(r"\Amap\[[^\]]+\]func\s*\(").is_match(annotation) {
            return None;
        }
        self.resolve(&self.text(Some(args[0])), scope)
            .map(|index| (container, index))
    }
    pub(super) fn value(&mut self, node: Option<SyntaxNode<'a>>, scope: &str, cls: &str) -> String {
        let mut pending = vec![ValueTask::Enter(node)];
        let mut values = Vec::new();
        while let Some(task) = pending.pop() {
            match task {
                ValueTask::Enter(node) => match self.value_step(node, scope, cls) {
                    ValueStep::Ready(value) => values.push(value),
                    ValueStep::Alias(node) => pending.push(ValueTask::Enter(node)),
                    ValueStep::Assertion { node, inner } => {
                        pending.push(ValueTask::Assertion(node));
                        pending.push(ValueTask::Enter(Some(inner)));
                    }
                    ValueStep::Member {
                        node,
                        object,
                        member,
                    } => {
                        pending.push(ValueTask::Member { node, member });
                        pending.push(ValueTask::Enter(object));
                    }
                    ValueStep::Copy {
                        node,
                        collection,
                        inner,
                    } => {
                        pending.push(ValueTask::Copy { node, collection });
                        pending.push(ValueTask::Enter(Some(inner)));
                    }
                    ValueStep::Expression {
                        node,
                        value,
                        operator,
                        operands,
                    } => {
                        values.push(value.clone());
                        for (position, operand) in operands.into_iter().enumerate().rev() {
                            pending.push(ValueTask::Operand {
                                node,
                                value: value.clone(),
                                operator: operator.clone(),
                                position,
                            });
                            pending.push(ValueTask::Enter(Some(operand)));
                        }
                    }
                    ValueStep::Cast {
                        node,
                        value,
                        operand,
                    } => {
                        values.push(value.clone());
                        pending.push(ValueTask::Cast { node, value });
                        pending.push(ValueTask::Enter(Some(operand)));
                    }
                },
                ValueTask::Assertion(node) => {
                    let value = values.last().expect("assertion operand");
                    self.add(
                        &source::operation_id(&self.ir.path, node),
                        "TYPE_ASSERTION_VALUE",
                        value,
                        &self.evidence(node),
                        json!({"basis":"typescript-erased-assertion"}),
                    );
                }
                ValueTask::Member { node, member } => {
                    let base = values.pop().expect("member receiver");
                    let result = self.entity("MEMBER", &member, &base, node, json!({}));
                    self.add(&result, "MEMBER_OF", &base, &self.evidence(node), json!({}));
                    values.push(result);
                }
                ValueTask::Copy { node, collection } => {
                    let value = values.pop().expect("copy operand");
                    self.add(
                        &collection,
                        "SHALLOW_COPY_SOURCE",
                        &value,
                        &self.evidence(node),
                        json!({"model":"array-single-spread"}),
                    );
                    values.push(collection);
                }
                ValueTask::Operand {
                    node,
                    value,
                    operator,
                    position,
                } => {
                    let operand = values.pop().expect("expression operand");
                    self.add(
                        &value,
                        "EXPRESSION_OPERAND",
                        &operand,
                        &self.evidence(node),
                        json!({"position":position,"operator":operator}),
                    );
                }
                ValueTask::Cast { node, value } => {
                    let operand = values.pop().expect("cast operand");
                    self.add(
                        &value,
                        "CAST_VALUE",
                        &operand,
                        &self.evidence(node),
                        json!({"basis":"runtime-cast-operand"}),
                    );
                }
            }
        }
        debug_assert_eq!(values.len(), 1);
        values.pop().expect("projected expression")
    }
    fn value_step(
        &mut self,
        node: Option<SyntaxNode<'a>>,
        scope: &str,
        cls: &str,
    ) -> ValueStep<'a> {
        let Some(node) = node else {
            return ValueStep::Ready(format!("{scope}/UNKNOWN"));
        };
        let node = self.unwrap(node);
        let kind = node.kind();
        if matches!(kind, "unary_expression" | "unary_operator") {
            let operator = node
                .children()
                .into_iter()
                .filter(|n| !n.is_named())
                .map(|n| self.text(Some(n)))
                .collect::<Vec<_>>()
                .join(" ");
            let operands = node
                .named_children()
                .into_iter()
                .filter(|n| !n.kind().contains("comment"))
                .collect::<Vec<_>>();
            if matches!(operator.as_str(), "&" | "*") && operands.len() == 1 {
                return ValueStep::Alias(Some(operands[0]));
            }
        }
        if self.language == Language::TypeScript
            && matches!(
                kind,
                "as_expression" | "type_assertion" | "non_null_expression" | "satisfies_expression"
            )
        {
            let parts = node
                .named_children()
                .into_iter()
                .filter(|n| !n.kind().contains("comment"))
                .collect::<Vec<_>>();
            if !parts.is_empty() {
                let inner = if kind == "type_assertion" {
                    *parts.last().unwrap()
                } else {
                    parts[0]
                };
                return ValueStep::Assertion { node, inner };
            }
        }
        if (vocabulary().functions.contains(kind) || kind == "class")
            && let Some(id) = self.declarations.nodes.get(&node.id())
        {
            return ValueStep::Ready(id.clone());
        }
        let spelling = if !node.has_error()
            && matches!(
                kind,
                "binary_operator" | "binary_expression" | "unary_operator" | "unary_expression"
            ) {
            String::new()
        } else {
            self.text(Some(node))
        };
        let receiver = self
            .bindings
            .receivers
            .get(scope)
            .cloned()
            .unwrap_or_default();
        let base = (matches!(
            self.language,
            Language::Java | Language::Python | Language::JavaScript | Language::TypeScript
        ) && spelling == "super")
            || (self.language == Language::CSharp && spelling == "base");
        if !spelling.is_empty()
            && !cls.is_empty()
            && (spelling == receiver || matches!(spelling.as_str(), "this" | "self") || base)
        {
            let value = format!("{cls}/THIS");
            if self.positions.contains_key(scope)
                && self.entity_ref(scope).kind == "CALLABLE"
                && !self.flag(scope, "static")
            {
                self.add(
                    cls,
                    "INSTANCE_RECEIVER",
                    &value,
                    &self.evidence(node),
                    json!({"basis":"instance-relative"}),
                );
            }
            return ValueStep::Ready(value);
        }
        if matches!(kind, "instance_variable" | "class_variable") && !cls.is_empty() {
            return ValueStep::Ready(self.storage(
                spelling.trim_start_matches('@'),
                cls,
                node,
                false,
            ));
        }
        if kind == "global_variable" || (kind == "identifier" && spelling.starts_with('$')) {
            let module = self.module.clone();
            return ValueStep::Ready(self.storage(
                spelling.trim_start_matches('$'),
                &module,
                node,
                false,
            ));
        }
        if matches!(
            kind,
            "none" | "null" | "null_literal" | "nil" | "nil_literal"
        ) || matches!(spelling.as_str(), "None" | "null" | "nil" | "nullptr")
        {
            return ValueStep::Ready("NULL".into());
        }
        if vocabulary().calls.contains(kind) || self.go_indexed_call(node, scope, cls).is_some() {
            let call = self.entity(
                "CALL",
                &node.start_byte().to_string(),
                scope,
                node,
                json!({}),
            );
            if !vocabulary().calls.contains(kind) {
                self.set(&call, "owner", scope.into());
            }
            return ValueStep::Ready(call);
        }
        if vocabulary().members.contains(kind) {
            let (object, member) = self.member_parts(node);
            let objname = self.text(object);
            if !cls.is_empty()
                && (objname == receiver
                    || matches!(objname.as_str(), "this" | "self")
                    || objname == self.entity_ref(cls).name)
            {
                return ValueStep::Ready(self.storage(
                    &member,
                    cls,
                    node,
                    objname == self.entity_ref(cls).name || objname == "cls",
                ));
            }
            return ValueStep::Member {
                node,
                object,
                member,
            };
        }
        if matches!(kind, "qualified_identifier" | "scoped_identifier")
            && let (Some(qualifier), Some(constant)) =
                (field(Some(node), &["scope", "path"]), node.field("name"))
            && let Some(id) = self.resolve(&self.text(Some(qualifier)), scope)
            && self
                .declarations
                .enums
                .get(&id)
                .is_some_and(|names| names.contains(&self.text(Some(constant))))
        {
            let result = self.entity("MEMBER", &self.text(Some(constant)), &id, node, json!({}));
            self.add(&result, "MEMBER_OF", &id, &self.evidence(node), json!({}));
            return ValueStep::Ready(result);
        }
        if matches!(
            kind,
            "identifier"
                | "field_identifier"
                | "property_identifier"
                | "private_property_identifier"
                | "type_identifier"
                | "self"
        ) {
            if let Some(id) = self
                .block_local(&spelling, scope, node)
                .or_else(|| self.resolve(&spelling, scope))
            {
                return ValueStep::Ready(id);
            }
            return ValueStep::Ready(self.storage(&spelling, scope, node, false));
        }
        if matches!(
            kind,
            "list"
                | "list_expression"
                | "array"
                | "array_expression"
                | "array_creation_expression"
                | "dictionary"
                | "object"
                | "map_literal"
        ) {
            let collection_kind = if matches!(kind, "dictionary" | "map_literal") {
                "map"
            } else if kind == "object" {
                "record"
            } else if self.language == Language::Python {
                "list"
            } else {
                "array"
            };
            let collection = self.entity(
                "COLLECTION",
                &node.start_byte().to_string(),
                scope,
                node,
                json!({"collection_kind":collection_kind}),
            );
            if matches!(kind, "list" | "array" | "dictionary" | "object")
                && !node.children().iter().any(|n| n.kind() == ",")
                && !node
                    .named_children()
                    .iter()
                    .any(|n| !n.kind().contains("comment"))
            {
                self.add(
                    &collection,
                    "EMPTY_COLLECTION",
                    collection_kind,
                    &self.evidence(node),
                    json!({"basis":"literal"}),
                );
            }
            let elements = node
                .named_children()
                .into_iter()
                .filter(|n| !n.kind().contains("comment"))
                .collect::<Vec<_>>();
            if matches!(self.language, Language::JavaScript | Language::TypeScript)
                && kind == "array"
                && elements.len() == 1
                && elements[0].kind() == "spread_element"
                && elements[0].named_children().len() == 1
            {
                return ValueStep::Copy {
                    node,
                    collection,
                    inner: elements[0].named_children()[0],
                };
            }
            return ValueStep::Ready(collection);
        }
        let primitive = match kind {
            "integer"
            | "integer_literal"
            | "int_literal"
            | "decimal_integer_literal"
            | "hex_integer_literal"
            | "octal_integer_literal"
            | "binary_integer_literal" => "int",
            "float" | "float_literal" => "float",
            "string" | "string_literal" => "str",
            "true" | "false" | "boolean" => "bool",
            "number" => "number",
            "character_literal" | "char_literal" => "char",
            _ => "unknown",
        };
        let mut attrs = json!({"native_kind":kind,"type":primitive});
        if matches!(primitive, "int" | "float" | "number") {
            attrs["literal"] = spelling.into();
        }
        let result = self.entity("VALUE", &node.start_byte().to_string(), scope, node, attrs);
        if !self.expression_values.contains(&result)
            && matches!(
                kind,
                "binary_operator" | "binary_expression" | "unary_operator" | "unary_expression"
            )
        {
            self.expression_values.insert(result.clone());
            let operator = node
                .children()
                .into_iter()
                .filter(|n| !n.is_named())
                .map(|n| self.text(Some(n)))
                .collect::<Vec<_>>()
                .join(" ");
            if matches!(
                operator.as_str(),
                "+" | "-"
                    | "*"
                    | "/"
                    | "%"
                    | "**"
                    | "<"
                    | ">"
                    | "<="
                    | ">="
                    | "=="
                    | "!="
                    | "!"
                    | "~"
            ) {
                let operands = node
                    .named_children()
                    .into_iter()
                    .filter(|node| !node.kind().contains("comment"))
                    .collect();
                return ValueStep::Expression {
                    node,
                    value: result,
                    operator,
                    operands,
                };
            }
        }
        if kind == "cast_expression"
            && matches!(self.language, Language::Java | Language::CSharp)
            && let Some(operand) = node.field("value")
        {
            return ValueStep::Cast {
                node,
                value: result,
                operand,
            };
        }
        ValueStep::Ready(result)
    }
}
