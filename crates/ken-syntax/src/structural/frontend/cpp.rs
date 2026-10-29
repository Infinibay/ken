//! C++ declaration shapes and direct initializer values, without overload inference.
use super::*;
use ken_program::{TypeRef, parse_type};
fn unqualified(mut value: &TypeRef) -> &TypeRef {
    while value.kind == "qualified" && !value.arguments.is_empty() {
        value = &value.arguments[0];
    }
    value
}
fn key(value: &TypeRef) -> Option<Value> {
    if matches!(
        value.kind.as_str(),
        "pointer" | "reference" | "rvalue_reference" | "qualified"
    ) && value.arguments.len() == 1
    {
        let mut qualifiers = value.qualifiers.clone();
        qualifiers.sort();
        Some(json!([value.kind, qualifiers, key(&value.arguments[0])?]))
    } else if matches!(
        value.kind.as_str(),
        "int" | "float" | "char" | "bool" | "nominal" | "void"
    ) {
        Some(json!([value.kind, value.native]))
    } else {
        None
    }
}
pub(super) fn parameter_head(annotation: &str) -> Option<String> {
    let parsed = parse_type(annotation, "cpp");
    let mut current = &parsed;
    let mut indirections = 0;
    while matches!(
        current.kind.as_str(),
        "qualified" | "pointer" | "reference" | "rvalue_reference"
    ) && !current.arguments.is_empty()
    {
        indirections += usize::from(current.kind != "qualified");
        current = &current.arguments[0];
    }
    if current.kind == "nominal"
        && indirections <= 1
        && full(r"[A-Za-z_]\w*", &current.native).is_some()
    {
        Some(current.native.clone())
    } else {
        None
    }
}
impl<'a, 's> Unit<'a, 's> {
    fn cpp_abstract_type(
        &self,
        origin: SyntaxNode<'a>,
        removed: Option<SyntaxNode<'a>>,
        decl: Option<SyntaxNode<'a>>,
    ) -> String {
        let annotation = origin.field("type");
        let mut parts = origin
            .named_children()
            .into_iter()
            .filter(|c| {
                annotation.is_some_and(|a| a.id() == c.id()) || c.kind() == "type_qualifier"
            })
            .map(|n| self.text(Some(n)))
            .collect::<Vec<_>>();
        if let Some(decl) = decl.or_else(|| origin.field("declarator")) {
            parts.push(if let Some(removed) = removed {
                String::from_utf8_lossy(
                    &[
                        &self.source[decl.start_byte()..removed.start_byte()],
                        &self.source[removed.end_byte()..decl.end_byte()],
                    ]
                    .concat(),
                )
                .into_owned()
            } else {
                self.text(Some(decl))
            });
        }
        trim(
            &parts
                .into_iter()
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
                .join(" "),
        )
        .into()
    }
    pub(super) fn cpp_parameter_info(
        &self,
        node: SyntaxNode<'a>,
    ) -> (Option<SyntaxNode<'a>>, String) {
        let mut current = node.field("declarator");
        for _ in 0..32 {
            if current.is_none_or(|n| matches!(n.kind(), "identifier" | "field_identifier")) {
                break;
            }
            current = current.and_then(source::nested);
        }
        let name = current.filter(|n| matches!(n.kind(), "identifier" | "field_identifier"));
        (name, self.cpp_abstract_type(node, name, None))
    }
    pub(super) fn cpp_method_info(&self, node: SyntaxNode<'a>, origin: SyntaxNode<'a>) -> Value {
        let Some((function, name)) = source::function_parts(node) else {
            return json!({"cpp_signature_syntax":false});
        };
        let parameters = function.field("parameters");
        let tokens = origin
            .children()
            .into_iter()
            .filter(|n| !n.is_named())
            .map(|n| self.text(Some(n)))
            .collect::<BTreeSet<_>>();
        let mut qualifiers = function
            .named_children()
            .into_iter()
            .filter(|n| n.kind() == "type_qualifier")
            .map(|n| self.text(Some(n)))
            .collect::<Vec<_>>();
        qualifiers.sort();
        let reference = function
            .named_children()
            .into_iter()
            .find(|n| n.kind() == "ref_qualifier")
            .map(|n| self.text(Some(n)))
            .unwrap_or_default();
        let specifiers = function
            .named_children()
            .into_iter()
            .filter(|n| n.kind() == "virtual_specifier")
            .map(|n| self.text(Some(n)))
            .collect::<BTreeSet<_>>();
        let mut root = function;
        while let Some(parent) = root.parent().filter(|p| p.id() != origin.id()) {
            root = parent;
        }
        let mut tail = Vec::new();
        let mut found = false;
        for child in origin.children() {
            if child.id() == root.id() {
                found = true;
                continue;
            }
            if found {
                if matches!(child.kind(), "," | ";") {
                    break;
                }
                if !child.kind().contains("comment") {
                    tail.push(self.text(Some(child)));
                }
            }
        }
        let mut returning = self.cpp_abstract_type(origin, Some(function), Some(root));
        if let Some(trailing) = function
            .named_children()
            .into_iter()
            .find(|n| n.kind() == "trailing_return_type")
        {
            returning = trim(
                self.text(Some(trailing))
                    .strip_prefix("->")
                    .unwrap_or(&self.text(Some(trailing))),
            )
            .into();
        }
        let mut ancestor = origin.parent();
        let mut templated = false;
        while let Some(node) = ancestor {
            templated |= node.kind() == "template_declaration";
            ancestor = node.parent();
        }
        json!({"cpp_signature_syntax":!origin.has_error()&&parameters.is_some()&&!templated&&name.kind()!="destructor_name","declaration_only":origin.field("body").is_none(),"explicit_virtual":tokens.contains("virtual"),"pure_virtual":tail==["=","0"],"override_specifier":specifiers.contains("override"),"final_specifier":specifiers.contains("final"),"cv_qualifiers":qualifiers,"ref_qualifier":reference,"cpp_variadic":parameters.is_some_and(|p|p.children().iter().any(|n|n.kind()=="...")),"static":origin.named_children().iter().any(|n|n.kind()=="storage_class_specifier"&&self.text(Some(*n))=="static"),"native_return_type":returning})
    }
    pub(super) fn cpp_field_declaration(&mut self, node: SyntaxNode<'a>, scope: &str) {
        let annotation = node.field("type");
        let (mut count, mut unsupported) = (0, false);
        let children = node.children_with_fields();
        for (i, &(declarator, role)) in children.iter().enumerate() {
            if role != Some("declarator") {
                continue;
            }
            let mut current = Some(declarator);
            let (mut indirections, mut complex) = (0, false);
            for _ in 0..32 {
                let Some(n) = current else {
                    break;
                };
                if matches!(n.kind(), "identifier" | "field_identifier") {
                    break;
                }
                if n.kind() == "function_declarator" {
                    let nested = source::declarator(Some(n));
                    if nested.is_none_or(|n| {
                        n.kind() != "parenthesized_declarator"
                            || !source::descendants_with_roles(n).iter().any(|(n, _)| {
                                matches!(n.kind(), "pointer_declarator" | "reference_declarator")
                            })
                    }) {
                        current = None;
                        break;
                    }
                    complex = true;
                } else if n.kind() == "array_declarator" {
                    complex = true;
                } else if matches!(n.kind(), "pointer_declarator" | "reference_declarator") {
                    indirections += 1;
                } else if n.kind() != "parenthesized_declarator" {
                    unsupported = true;
                    current = None;
                    break;
                }
                let mut nested = source::declarator(Some(n));
                if nested.is_none() && n.kind() == "parenthesized_declarator" {
                    nested = n
                        .named_children()
                        .into_iter()
                        .find(|c| c.kind() != "comment");
                }
                current = nested;
            }
            let Some(current) = current else {
                continue;
            };
            let Some(annotation) =
                annotation.filter(|_| matches!(current.kind(), "identifier" | "field_identifier"))
            else {
                unsupported = true;
                continue;
            };
            let target = self.storage(&self.text(Some(current)), scope, current, false);
            let is_static = node
                .named_children()
                .iter()
                .any(|n| n.kind() == "storage_class_specifier" && self.text(Some(*n)) == "static");
            self.extend(&target, json!({"declared":true,"static":is_static}));
            self.update_declared_static(scope, &target, is_static, true);
            let abstract_text = String::from_utf8_lossy(
                &[
                    &self.source[declarator.start_byte()..current.start_byte()],
                    &self.source[current.end_byte()..declarator.end_byte()],
                ]
                .concat(),
            )
            .into_owned();
            let mut parts = node
                .named_children()
                .into_iter()
                .filter(|c| c.id() == annotation.id() || c.kind() == "type_qualifier")
                .map(|n| self.text(Some(n)))
                .collect::<Vec<_>>();
            parts.push(abstract_text);
            let native = trim(&parts.join(" ")).to_owned();
            self.declarations
                .annotations
                .push((target.clone(), native, self.evidence(declarator)));
            let nominal = annotation.kind() == "type_identifier" && !complex && indirections <= 1;
            self.add(
                &target,
                "TYPE_HEAD_STATUS",
                if nominal { "supported" } else { "unsupported" },
                &self.evidence(declarator),
                json!({"basis":"cpp-declarator-syntax"}),
            );
            if nominal {
                self.add(
                    &target,
                    "TYPE_HEAD",
                    &self.text(Some(annotation)),
                    &self.evidence(declarator),
                    json!({"basis":"cpp-declarator-syntax"}),
                );
            }
            count += 1;
            for &(child, role) in &children[i + 1..] {
                if matches!(child.kind(), "," | ";") || role == Some("declarator") {
                    break;
                }
                if role != Some("default_value") {
                    continue;
                }
                let operation = source::operation_id(&self.ir.path, declarator);
                self.declarations
                    .field_initializers
                    .entry(node.id())
                    .or_default()
                    .push((operation, target.clone(), child));
                break;
            }
        }
        let operation = source::operation_id(&self.ir.path, node);
        self.add(
            &operation,
            "CPP_FIELD_DECL_STATUS",
            if unsupported {
                "unsupported"
            } else if count > 0 {
                "supported"
            } else {
                "not-storage"
            },
            &self.evidence(node),
            json!({"basis":"declarator-syntax","fields":count}),
        );
    }
    pub(super) fn record_cpp_initializer(&mut self, node: SyntaxNode<'a>, owner: &str, cls: &str) {
        if !self.positions.contains_key(owner)
            || !self.flag(owner, "constructor")
            || cls.is_empty()
            || node
                .parent()
                .is_none_or(|p| p.kind() != "field_initializer_list")
        {
            return;
        }
        let items = node
            .named_children()
            .into_iter()
            .filter(|n| !n.kind().contains("comment"))
            .collect::<Vec<_>>();
        if items.len() != 2 {
            return;
        }
        let (name, arguments) = (items[0], items[1]);
        let operation = source::operation_id(&self.ir.path, node);
        let ev = self.evidence(node);
        self.add(
            owner,
            "HAS_INITIALIZER",
            &operation,
            &ev,
            json!({"basis":"cpp-constructor-syntax"}),
        );
        self.add(
            &operation,
            "FIELD_NAME",
            &self.text(Some(name)),
            &ev,
            json!({}),
        );
        self.add(
            &operation,
            "INITIALIZER_FORM",
            arguments.kind(),
            &ev,
            json!({"packed":node.next_sibling().is_some_and(|n|n.kind()=="...")}),
        );
        if name.kind() == "field_identifier"
            && let Some(slot) = self
                .bindings
                .names
                .get(&(cls.into(), self.text(Some(name))))
                .cloned()
            && self.entity_ref(&slot).kind == "STORAGE"
            && !self.flag(&slot, "static")
        {
            self.add(
                &operation,
                "INITIALIZES_FIELD",
                &slot,
                &ev,
                json!({"basis":"cpp-constructor-syntax"}),
            );
        }
        for (position, arg) in arguments
            .named_children()
            .into_iter()
            .filter(|n| !n.kind().contains("comment"))
            .enumerate()
        {
            let value = self.value(Some(arg), owner, cls);
            self.add(
                &operation,
                "INITIALIZER_ARGUMENT",
                &value,
                &self.evidence(arg),
                json!({"position":position,"native_kind":arg.kind()}),
            );
        }
    }
    pub(super) fn cpp_initializer_values(&mut self) {
        if self.language != Language::Cpp {
            return;
        }
        let initializers = self
            .ir
            .facts
            .iter()
            .filter(|f| {
                f.relation == "HAS_INITIALIZER"
                    && f.attrs
                        .get("basis")
                        .is_some_and(|v| v.get() == "\"cpp-constructor-syntax\"")
            })
            .cloned()
            .collect::<Vec<_>>();
        let targets = self
            .ir
            .facts
            .iter()
            .filter(|f| f.relation == "INITIALIZES_FIELD")
            .map(|f| (f.subject.clone(), f.object.clone()))
            .collect::<BTreeMap<_, _>>();
        let mut counts = BTreeMap::<(String, String), usize>::new();
        for f in &initializers {
            if let Some(field) = targets.get(&f.object) {
                *counts
                    .entry((f.subject.clone(), field.clone()))
                    .or_default() += 1;
            }
        }
        let parameters = self
            .ir
            .facts
            .iter()
            .filter(|f| f.relation == "HAS_PARAMETER")
            .map(|f| (f.subject.clone(), f.object.clone()))
            .collect::<BTreeSet<_>>();
        let mut arguments_by_initializer = BTreeMap::<String, Vec<Fact>>::new();
        let mut forms_by_initializer = BTreeMap::<String, Vec<Fact>>::new();
        for fact in &self.ir.facts {
            let map = match fact.relation.as_str() {
                "INITIALIZER_ARGUMENT" => &mut arguments_by_initializer,
                "INITIALIZER_FORM" => &mut forms_by_initializer,
                _ => continue,
            };
            map.entry(fact.subject.clone())
                .or_default()
                .push(fact.clone());
        }
        for entry in initializers {
            let (owner, operation) = (&entry.subject, &entry.object);
            let field = targets.get(operation);
            let args = arguments_by_initializer
                .get(operation)
                .map_or(&[][..], Vec::as_slice);
            let forms = forms_by_initializer
                .get(operation)
                .map_or(&[][..], Vec::as_slice);
            let (mut reason, mut value, mut direct) = ("", None, false);
            if !self.ir.diagnostics.is_empty() || !self.flag(owner, "cpp_signature_syntax") {
                reason = "unsupported-constructor";
            } else if field.is_none() {
                reason = "not-direct-instance-field";
            } else if counts[&(owner.clone(), field.unwrap().clone())] != 1 {
                reason = "duplicate-initializer";
            } else if forms.len() != 1
                || forms[0]
                    .attrs
                    .get("packed")
                    .is_some_and(|v| v.get() == "true")
            {
                reason = "initializer-grammar";
            } else {
                let field = field.unwrap();
                let parsed = parse_type(
                    self.attr(field, "native_type").as_str().unwrap_or(""),
                    "cpp",
                );
                let r = unqualified(&parsed);
                let scalar = matches!(r.kind.as_str(), "int" | "float" | "char" | "bool");
                if args.is_empty() && (scalar || r.kind == "pointer") {
                    if r.kind == "pointer" {
                        value = Some("NULL".into());
                    }
                } else if args.len() == 1 {
                    let operand = &args[0].object;
                    let native = args[0]
                        .attrs
                        .get("native_kind")
                        .map(|v| serde_json::from_str::<String>(v.get()).unwrap())
                        .unwrap_or_default();
                    if (r.kind == "pointer" && operand == "NULL")
                        || (scalar
                            && matches!(
                                native.as_str(),
                                "number_literal" | "char_literal" | "true" | "false"
                            ))
                    {
                        value = Some(operand.clone());
                    } else if matches!(
                        r.kind.as_str(),
                        "pointer"
                            | "reference"
                            | "rvalue_reference"
                            | "int"
                            | "float"
                            | "char"
                            | "bool"
                    ) && parameters.contains(&(owner.clone(), operand.clone()))
                    {
                        let supplied = parse_type(
                            self.attr(operand, "native_type").as_str().unwrap_or(""),
                            "cpp",
                        );
                        if key(r).is_some() && key(r) == key(unqualified(&supplied)) {
                            value = Some(operand.clone());
                            direct = true;
                        } else {
                            reason = "parameter-type-conversion";
                        }
                    } else {
                        reason = "non-direct-value";
                    }
                } else {
                    reason = "unsupported-value-initialization";
                }
            }
            let ev = entry.evidence.first().map_or("", String::as_str);
            self.add(
                operation,
                "CONSTRUCTOR_INITIALIZER_STATUS",
                if reason.is_empty() {
                    "supported"
                } else {
                    "unsupported"
                },
                ev,
                json!({"analysis":"cpp-initializers/1","reason":reason}),
            );
            if !reason.is_empty() || field.is_none() {
                continue;
            }
            let field = field.unwrap();
            self.add(
                owner,
                "WRITES",
                field,
                ev,
                json!({"basis":"cpp-constructor-initializer"}),
            );
            if let Some(value) = value {
                self.add(
                    operation,
                    "STORES_VALUE",
                    &value,
                    ev,
                    json!({"basis":"cpp-constructor-initializer"}),
                );
                if direct {
                    self.add(
                        operation,
                        "CONSTRUCTOR_INITIALIZER_INPUT",
                        &value,
                        ev,
                        json!({"basis":"cpp-constructor-initializer"}),
                    );
                    self.add(
                        field,
                        "ASSIGNED_FROM",
                        &value,
                        ev,
                        json!({"basis":"cpp-constructor-initializer"}),
                    );
                    self.add(
                        &value,
                        "FLOWS_TO",
                        field,
                        ev,
                        json!({"basis":"cpp-constructor-initializer"}),
                    );
                }
            }
        }
    }
}
