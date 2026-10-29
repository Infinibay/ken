//! Declaration collection owns symbol identity, signatures, exports and annotations.
use super::*;
impl<'a, 's> Unit<'a, 's> {
    pub(super) fn import_context(&mut self) {
        let nodes = source::descendants_with_roles(self.root);
        for &(node, _) in &nodes {
            if node.kind() == "import_from_statement" {
                let spelling = self.text(Some(node));
                if let Some(m) = full(r"(?s)from\s+contextlib\s+import\s+(.+)", &spelling) {
                    for imported in m[1].trim_matches(['(', ')', ' ', '\n']).split(',') {
                        let names = rx(r"\s+as\s+")
                            .split(trim(imported))
                            .map(str::to_owned)
                            .collect::<Vec<_>>();
                        if matches!(names[0].as_str(), "contextmanager" | "asynccontextmanager") {
                            self.context_decorators
                                .insert(names.last().unwrap().clone());
                        }
                    }
                }
            } else if node.kind() == "import_statement"
                && let Some(m) = full(
                    r"import\s+contextlib(?:\s+as\s+(\w+))?",
                    &self.text(Some(node)),
                )
            {
                let prefix = m.get(1).map_or("contextlib", |m| m.as_str());
                for name in ["contextmanager", "asynccontextmanager"] {
                    self.context_decorators.insert(format!("{prefix}.{name}"));
                }
            }
            if node.kind() == "export_statement" {
                self.exported_names.extend(self.export_clause_names(node));
            }
        }
        let mut shadowed = BTreeSet::new();
        for &(node, _) in &nodes {
            if vocabulary().functions.contains(node.kind())
                || vocabulary().types.contains(node.kind())
            {
                shadowed.insert(source::name(node, self.source));
            } else if vocabulary().assignments.contains(node.kind())
                && let Some(left) = field(Some(node), &["left", "name", "pattern"])
                && left.kind() == "identifier"
            {
                shadowed.insert(self.text(Some(left)));
            }
        }
        self.context_decorators
            .retain(|name| !shadowed.contains(name.split('.').next().unwrap()));
    }
    fn export_clause_names(&self, node: SyntaxNode<'a>) -> BTreeSet<String> {
        let spelling = self
            .text(Some(node))
            .split(ken_text::unicode::whitespace)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
        let mut names = BTreeSet::new();
        if let Some(m) = full(r"export\s*\{([^}]*)\}\s*;?", &spelling) {
            for item in m[1].split(',') {
                let name = rx(r"\s+as\s+")
                    .split(trim(item))
                    .next()
                    .unwrap()
                    .trim()
                    .to_owned();
                if full(r"[A-Za-z_$][\w$]*", &name).is_some() {
                    names.insert(name);
                }
            }
        }
        if let Some(m) = full(r"export\s+default\s+([A-Za-z_$][\w$]*)\s*;?", &spelling) {
            names.insert(m[1].into());
        }
        names
    }
    fn mark_export(&mut self, scope: &str, entity: &str, name: &str, node: SyntaxNode<'a>) {
        if scope != self.module {
            return;
        }
        let basis = match self.language {
            Language::JavaScript | Language::TypeScript => {
                if node
                    .parent()
                    .is_some_and(|p| p.kind() == "export_statement")
                {
                    Some("explicit-export")
                } else if self.exported_names.contains(name) {
                    Some("export-clause")
                } else {
                    None
                }
            }
            Language::Rust => node
                .children()
                .iter()
                .any(|c| {
                    c.kind() == "visibility_modifier"
                        && trim(&self.text(Some(*c))).starts_with("pub")
                })
                .then_some("visibility-modifier"),
            Language::Go => name
                .chars()
                .next()
                .is_some_and(ken_text::unicode::uppercase)
                .then_some("public-name"),
            Language::Python => {
                (!name.is_empty() && !name.starts_with('_')).then_some("public-name")
            }
            _ => None,
        };
        if let Some(basis) = basis {
            self.add(
                scope,
                "EXPORT",
                entity,
                &self.evidence(node),
                json!({"name":name,"basis":basis}),
            );
        }
    }
    pub(super) fn bound_type_parameters(&mut self, node: SyntaxNode<'a>) -> Vec<String> {
        let mut names = BTreeSet::new();
        let mut current = Some(node);
        for _ in 0..64 {
            let Some(n) = current else {
                break;
            };
            if !self.declarations.type_groups.contains_key(&n.id()) {
                let mut local = BTreeSet::new();
                let mut groups = vec![n.field("type_parameters"), n.field("type_parameter_list")];
                if n.kind() == "template_declaration" {
                    groups.push(n.field("parameters"));
                }
                if groups.iter().all(Option::is_none) {
                    groups.push(
                        n.named_children()
                            .into_iter()
                            .find(|c| c.kind() == "type_parameter_list"),
                    );
                }
                for group in groups.into_iter().flatten() {
                    for parameter in group.named_children() {
                        if matches!(
                            parameter.kind(),
                            "type_parameter" | "const_parameter" | "type_parameter_declaration"
                        ) {
                            let name = parameter.field("name").or_else(|| {
                                parameter
                                    .named_children()
                                    .into_iter()
                                    .find(|c| matches!(c.kind(), "type_identifier" | "identifier"))
                            });
                            if let Some(name) = name {
                                local.insert(self.text(Some(name)));
                            }
                        }
                    }
                }
                self.declarations
                    .type_groups
                    .insert(n.id(), local.into_iter().collect());
            }
            names.extend(self.declarations.type_groups[&n.id()].iter().cloned());
            current = n.parent();
        }
        names.into_iter().collect()
    }
    fn parameter_reference(&self, spelling: &str, bound: &[String]) -> Option<String> {
        if spelling.is_empty() || bound.is_empty() {
            return None;
        }
        let stripped =
            ken_text::unicode::replace_words(spelling, &["const", "mut", "ref", "volatile"], " ")
                .replace(['&', '*'], " ");
        let name = stripped
            .split(ken_text::unicode::whitespace)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
        bound.contains(&name).then_some(name)
    }
    pub(super) fn collect_declarations(&mut self) {
        let mut pending = vec![(self.root, self.module.clone(), String::new())];
        while let Some((node, mut scope, mut cls)) = pending.pop() {
            let kind = node.kind();
            let origin = (self.language == Language::Cpp && !cls.is_empty() && scope == cls)
                .then(|| source::prototype_origin(node))
                .flatten();
            if let Some(origin) = origin {
                self.owners.prototypes.insert(origin.id());
            }
            if vocabulary().types.contains(kind)
                && !(kind == "enum_specifier" && node.field("body").is_none())
            {
                let type_node = node.field("type");
                if !(kind == "type_spec"
                    && type_node
                        .is_some_and(|n| !matches!(n.kind(), "struct_type" | "interface_type")))
                {
                    let name = source::name(node, self.source);
                    let type_kind = if kind.contains("interface")
                        || kind == "trait_item"
                        || type_node.is_some_and(|n| n.kind() == "interface_type")
                    {
                        "INTERFACE"
                    } else {
                        "CLASS"
                    };
                    let expression = kind == "class"
                        && matches!(self.language, Language::JavaScript | Language::TypeScript);
                    let enclosing = scope.clone();
                    let declared = self.entity(
                        type_kind,
                        &name,
                        &scope,
                        node,
                        if expression {
                            json!({"expression":true})
                        } else {
                            json!({})
                        },
                    );
                    self.add(
                        &scope,
                        "DECLARES",
                        &declared,
                        &self.evidence(node),
                        json!({"kind":if expression{"type-expression"}else{"type"},"name":name}),
                    );
                    self.mark_export(&scope, &declared, &name, node);
                    if expression {
                        if node.field("name").is_some() {
                            self.bindings
                                .names
                                .insert((declared.clone(), name.clone()), declared.clone());
                        }
                        self.add(
                            &source::operation_id(&self.ir.path, node),
                            "CLASS_EXPRESSION",
                            &declared,
                            &self.evidence(node),
                            json!({"basis":"class-expression-syntax"}),
                        );
                    } else {
                        self.bindings
                            .names
                            .insert((scope.clone(), name.clone()), declared.clone());
                    }
                    if let Some(&position) = self.declarations.type_positions.get(&declared) {
                        self.declarations.types[position].1 = node;
                    } else {
                        self.declarations
                            .type_positions
                            .insert(declared.clone(), self.declarations.types.len());
                        self.declarations.types.push((declared.clone(), node));
                    }
                    self.declarations.type_ids.insert(declared.clone());
                    self.declarations.nodes.insert(node.id(), declared.clone());
                    if matches!(kind, "enum_specifier" | "enum_item" | "enum_declaration") {
                        let mut constants = BTreeSet::new();
                        if let Some(body) = node.field("body") {
                            for item in body.named_children() {
                                if matches!(
                                    item.kind(),
                                    "enumerator"
                                        | "enum_variant"
                                        | "enum_constant"
                                        | "enum_member_declaration"
                                        | "property_identifier"
                                ) {
                                    let spelling =
                                        self.text(Some(item.field("name").unwrap_or(item)));
                                    if full(r"[A-Za-z_$][\w$]*", &spelling).is_some() {
                                        constants.insert(spelling);
                                    }
                                }
                            }
                        }
                        self.declarations.enums.insert(declared.clone(), constants);
                    }
                    if self.language == Language::Rust {
                        let mut attribute = node.previous_named_sibling();
                        while let Some(a) = attribute.filter(|a| {
                            matches!(
                                a.kind(),
                                "attribute_item" | "line_comment" | "block_comment"
                            )
                        }) {
                            let spelling = self.text(Some(a));
                            if let Some(m) = full(r"#\[\s*derive\s*\(([^()]*)\)\s*\]", &spelling) {
                                for name in m[1].split(',').map(trim) {
                                    if full(r"\w+(?:::\w+)*", name).is_some() {
                                        self.add(
                                            &declared,
                                            "DERIVE_NAME",
                                            name,
                                            &self.evidence(a),
                                            json!({}),
                                        );
                                    }
                                }
                            }
                            attribute = a.previous_named_sibling();
                        }
                    }
                    cls = declared.clone();
                    scope = declared.clone();
                    for item in node.named_children() {
                        if matches!(
                            item.kind(),
                            "argument_list"
                                | "class_heritage"
                                | "superclass"
                                | "super_interfaces"
                                | "base_list"
                                | "base_class_clause"
                        ) {
                            let roots =
                                if matches!(item.kind(), "class_heritage" | "super_interfaces") {
                                    item.named_children()
                                        .into_iter()
                                        .flat_map(|part| {
                                            if matches!(
                                                part.kind(),
                                                "extends_clause"
                                                    | "implements_clause"
                                                    | "type_list"
                                            ) {
                                                part.named_children()
                                            } else {
                                                vec![part]
                                            }
                                        })
                                        .collect::<Vec<_>>()
                                } else {
                                    item.named_children()
                                };
                            for base in roots {
                                if base.kind() == "access_specifier" {
                                    continue;
                                }
                                self.declarations.bases.push((
                                    declared.clone(),
                                    self.text(Some(base)),
                                    self.evidence(base),
                                ));
                                if type_kind == "CLASS"
                                    && matches!(
                                        self.language,
                                        Language::Python
                                            | Language::JavaScript
                                            | Language::TypeScript
                                    )
                                    && base
                                        .parent()
                                        .is_none_or(|p| p.kind() != "implements_clause")
                                    && matches!(base.kind(), "identifier" | "type_identifier")
                                {
                                    let reference = if expression && self.text(Some(base)) == name {
                                        declared.clone()
                                    } else {
                                        enclosing.clone()
                                    };
                                    self.declarations.base_values.push((
                                        declared.clone(),
                                        base,
                                        reference,
                                    ));
                                }
                            }
                        }
                    }
                }
            } else if matches!(kind, "field_declaration" | "declaration")
                && self.language == Language::Cpp
                && scope == cls
            {
                self.cpp_field_declaration(node, &scope);
            } else if matches!(kind, "field_declaration" | "declaration")
                && self.language == Language::Cpp
            {
                for (child, role) in node.children_with_fields() {
                    if role != Some("declarator")
                        || source::descendants_with_roles(child)
                            .iter()
                            .any(|(n, _)| n.kind() == "function_declarator")
                    {
                        continue;
                    }
                    let mut name = child;
                    while let Some(nested) = name.field("declarator") {
                        name = nested;
                    }
                    if matches!(name.kind(), "field_identifier" | "identifier") {
                        self.storage(&self.text(Some(name)), &scope, name, false);
                    }
                }
            } else if vocabulary().file_declarations.contains(kind) && scope == self.module {
                let specs = if let Some(spec) = vocabulary().spec_declarations.get(kind) {
                    node.named_children()
                        .into_iter()
                        .filter(|c| c.kind() == spec)
                        .collect::<Vec<_>>()
                } else {
                    vec![node]
                };
                for spec in specs {
                    for name in source::declared_names(spec) {
                        if matches!(name.kind(), "identifier" | "field_identifier") {
                            self.storage(&self.text(Some(name)), &scope, name, false);
                        }
                    }
                }
            } else if kind == "impl_item" {
                let mut target = node.field("type");
                if target.is_some_and(|n| n.kind() == "generic_type") {
                    target = target.and_then(|n| n.field("type"));
                }
                cls = target
                    .filter(|n| n.kind() == "type_identifier")
                    .and_then(|n| {
                        self.bindings
                            .names
                            .get(&(scope.clone(), self.text(Some(n))))
                            .cloned()
                    })
                    .unwrap_or_default();
                if !cls.is_empty() {
                    scope = cls.clone();
                    let trait_name = self.text(node.field("trait"));
                    if !trait_name.is_empty() {
                        self.declarations.bases.push((
                            cls.clone(),
                            trait_name,
                            self.evidence(node),
                        ));
                    }
                }
            } else if vocabulary().functions.contains(kind) || origin.is_some() {
                scope = self.declare_function(node, &scope, &mut cls, origin);
            }
            self.owners.nodes.insert(node.id(), scope.clone());
            self.owners.classes.insert(node.id(), cls.clone());
            let mut children = node.named_children();
            children.sort_by_key(|c| {
                usize::from(
                    !vocabulary().types.contains(c.kind()) && c.kind() != "type_declaration",
                )
            });
            pending.extend(
                children
                    .into_iter()
                    .rev()
                    .map(|child| (child, scope.clone(), cls.clone())),
            );
        }
    }
    fn declare_function(
        &mut self,
        node: SyntaxNode<'a>,
        initial_scope: &str,
        cls: &mut String,
        origin: Option<SyntaxNode<'a>>,
    ) -> String {
        let mut scope = initial_scope.to_owned();
        let receiver = node.field("receiver");
        if let Some(receiver) = receiver {
            let parameter = receiver.named_children().first().copied();
            let target = rx(r"\[[^\]]*\]\s*$")
                .replace(&self.text(field(parameter, &["type"])), "")
                .trim_start_matches('*')
                .trim()
                .to_owned();
            *cls = self
                .bindings
                .names
                .get(&(self.module.clone(), target))
                .cloned()
                .unwrap_or_default();
            if !cls.is_empty() {
                scope = cls.clone();
            }
        }
        let kind = node.kind();
        let mut name = source::name(node, self.source);
        if self.language == Language::Cpp
            && let Some((_, named)) = source::function_parts(node)
        {
            name = self.text(Some(named));
        }
        let spelling = self.text(Some(node));
        let declaration = spelling
            .split('{')
            .next()
            .unwrap()
            .split('\n')
            .next()
            .unwrap();
        let mut is_static = ken_text::unicode::contains_word(declaration, "static");
        let decorators = node
            .parent()
            .filter(|n| n.kind() == "decorated_definition")
            .map(|n| {
                n.named_children()
                    .into_iter()
                    .filter(|n| n.kind() == "decorator")
                    .map(|n| self.text(Some(n)))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        is_static |= decorators
            .iter()
            .any(|d| d == "@classmethod" || d == "@staticmethod");
        let direct = !cls.is_empty()
            && scope == *cls
            && !matches!(
                kind,
                "lambda_expression"
                    | "lambda"
                    | "arrow_function"
                    | "func_literal"
                    | "function_expression"
            );
        let cpp_attrs = if self.language == Language::Cpp && direct {
            self.cpp_method_info(node, origin.unwrap_or(node))
        } else {
            json!({})
        };
        if let Some(v) = cpp_attrs.get("static") {
            is_static = v.as_bool().unwrap();
        }
        let constructor = matches!(name.as_str(), "__init__" | "__new__" | "constructor")
            || kind == "constructor_declaration"
            || (self.language == Language::Ruby && direct && name == "initialize")
            || (self.language == Language::Cpp && direct && name == self.entity_ref(cls).name);
        let async_ = if matches!(kind, "arrow_function" | "lambda_expression") {
            node.children()
                .iter()
                .any(|n| self.text(Some(*n)) == "async")
        } else {
            ken_text::unicode::contains_word(declaration, "async")
        };
        let context_manager = decorators.iter().any(|d| {
            self.context_decorators
                .contains(d.strip_prefix('@').unwrap_or(d))
        });
        let function=self.entity("CALLABLE",&name,&scope,node,json!({"static":is_static,"constructor":constructor,"async_":async_,"decorators":decorators,"context_manager":context_manager}));
        if direct {
            let access = self.callable_access(node, &self.entity_ref(cls).kind.clone());
            self.extend(&function, access);
        }
        let annotation = self.text(field(
            Some(node),
            &["return_type", "returns", "result", "type"],
        ));
        let normalized = annotation.trim_matches([':', ' ']);
        self.set(
            &function,
            "return_type",
            if normalized.is_empty() {
                "unknown".into()
            } else {
                normalized.into()
            },
        );
        self.set(&function, "native_return_type", normalized.into());
        if self.language == Language::Cpp && direct {
            self.extend(&function, cpp_attrs.clone());
            let ret = cpp_attrs["native_return_type"]
                .as_str()
                .filter(|s| !s.is_empty())
                .unwrap_or("unknown");
            self.set(&function, "return_type", ret.into());
        }
        let returning = self
            .attr(&function, "native_return_type")
            .as_str()
            .filter(|s| !s.is_empty())
            .unwrap_or(&annotation)
            .to_owned();
        if let Some(m) = full(r"\s*([A-Za-z_]\w*)\s*<\s*(.+?)\s*>\s*", &returning)
            && !cls.is_empty()
            && self.entity_ref(cls).name == m[1]
        {
            self.add(
                &function,
                "RETURN_TYPE_ARGUMENT",
                &m[2],
                &self.evidence(node),
                json!({}),
            );
        }
        self.set(&function, "generator", kind.contains("generator").into());
        self.declarations.nodes.insert(node.id(), function.clone());
        self.owners.functions.insert(node.id());
        self.bindings
            .names
            .insert((scope.clone(), name.clone()), function.clone());
        self.add(
            &scope,
            "DECLARES",
            &function,
            &self.evidence(node),
            json!({"kind":"callable","name":name,"static":is_static}),
        );
        self.mark_export(&scope, &function, &name, node);
        if direct {
            self.add(
                cls,
                "HAS_METHOD",
                &function,
                &self.evidence(node),
                json!({"name":name,"static":is_static}),
            );
            self.declarations
                .methods
                .entry(cls.clone())
                .or_default()
                .push(function.clone());
            self.add(&function, "IN_TYPE", cls, &self.evidence(node), json!({}));
        }
        self.add(
            &function,
            "OWNED_BY",
            &scope,
            &self.evidence(node),
            json!({}),
        );
        self.declare_parameters(node, &function, cls, &name, direct);
        if direct && self.language != Language::Python {
            self.bindings.receivers.insert(
                function.clone(),
                if self.language == Language::Rust {
                    "self"
                } else {
                    "this"
                }
                .into(),
            );
        }
        if let Some(receiver) = receiver {
            let parameter = receiver.named_children().first().copied();
            self.bindings
                .receivers
                .insert(function.clone(), self.text(field(parameter, &["name"])));
        }
        for decorator in decorators {
            self.add(
                &function,
                "DECORATED_BY",
                &decorator,
                &self.evidence(node),
                json!({}),
            );
        }
        function
    }
    fn declare_parameters(
        &mut self,
        node: SyntaxNode<'a>,
        function: &str,
        cls: &str,
        function_name: &str,
        direct: bool,
    ) {
        let parameters = source::parameters(node);
        let mut keyword = false;
        let mut positional = parameters.is_some_and(|p| {
            p.named_children()
                .iter()
                .any(|n| n.kind() == "positional_separator")
        });
        let mut nodes = parameters.map(|p| p.named_children()).unwrap_or_default();
        if self.language == Language::Cpp && nodes.len() == 1 && self.text(Some(nodes[0])) == "void"
        {
            nodes.clear();
        }
        if let Some(p) =
            parameters.filter(|p| matches!(p.kind(), "identifier" | "implicit_parameter"))
        {
            nodes = vec![p];
        }
        if parameters.is_none()
            && let Some(p) = node.field("parameter")
        {
            nodes = vec![p];
        }
        let bound = if matches!(
            self.language,
            Language::TypeScript
                | Language::Java
                | Language::CSharp
                | Language::Cpp
                | Language::Go
                | Language::Rust
        ) {
            self.bound_type_parameters(node)
        } else {
            Vec::new()
        };
        for (position, param) in nodes.into_iter().enumerate() {
            if param.kind() == "positional_separator" {
                positional = false;
                continue;
            }
            if param.kind() == "keyword_separator" {
                keyword = true;
                continue;
            }
            let spelling = self.text(Some(param));
            let pname_node =
                field(Some(param), &["name", "pattern", "declarator"]).unwrap_or_else(|| {
                    source::descendants_with_roles(param)
                        .into_iter()
                        .map(|(n, _)| n)
                        .find(|n| matches!(n.kind(), "identifier" | "self"))
                        .unwrap_or(param)
                });
            let mut name = self
                .text(Some(pname_node))
                .trim_start_matches(['*', '&', '.'])
                .to_owned();
            let (mut cpp_type, mut cpp_name, mut reference) = (String::new(), None, String::new());
            if self.language == Language::Cpp {
                let info = self.cpp_parameter_info(param);
                cpp_name = info.0;
                cpp_type = info.1;
                name = cpp_name
                    .map(|n| self.text(Some(n)))
                    .unwrap_or_else(|| format!("anonymous@{}", param.start_byte()));
                if let Some(d) = param
                    .field("declarator")
                    .filter(|d| d.kind() == "reference_declarator")
                {
                    reference = if d
                        .children()
                        .iter()
                        .any(|n| !n.is_named() && self.text(Some(*n)) == "&&")
                    {
                        "rvalue"
                    } else {
                        "lvalue"
                    }
                    .into();
                }
            }
            let variadic_keyword = spelling.starts_with("**");
            let variadic = spelling.starts_with('*')
                || spelling.contains("...")
                || source::descendants_with_roles(param)
                    .iter()
                    .any(|(n, _)| matches!(n.kind(), "rest_pattern" | "list_splat_pattern"));
            let kind = if variadic_keyword {
                "variadic_keyword"
            } else if variadic {
                "variadic_positional"
            } else if keyword {
                "keyword_only"
            } else if positional {
                "positional_only"
            } else {
                "positional"
            };
            let receiver = direct
                && position == 0
                && (matches!(name.as_str(), "self" | "cls") || param.kind() == "self_parameter");
            let id = self.entity(
                "PARAMETER",
                &name,
                function,
                param,
                json!({"kind_":kind,"position":position,"receiver":receiver}),
            );
            self.set(
                &id,
                "accepts_position",
                matches!(
                    kind,
                    "positional" | "positional_only" | "variadic_positional"
                )
                .into(),
            );
            if !reference.is_empty() {
                self.set(&id, "reference_kind", reference.into());
            }
            if !bound.is_empty() {
                let annotation = if !cpp_type.is_empty() {
                    cpp_type.clone()
                } else {
                    self.text(param.field("type"))
                };
                if let Some(reference) = self.parameter_reference(&annotation, &bound) {
                    self.add(
                        &id,
                        "TYPE_PARAMETER",
                        &reference,
                        &self.evidence(param),
                        json!({}),
                    );
                }
            }
            if self.language != Language::Cpp || cpp_name.is_some() {
                self.bindings
                    .names
                    .insert((function.into(), name.clone()), id.clone());
            }
            let mut default = field(Some(param), &["value", "default_value"]);
            if default.is_none() && self.language == Language::CSharp {
                let children = param.children();
                if let Some(equal) = children.iter().position(|c| c.kind() == "=") {
                    default = children[equal + 1..]
                        .iter()
                        .copied()
                        .find(|n| n.is_named() && n.kind() != "comment");
                }
            }
            let relative = position as i64
                - i64::from(
                    direct
                        && self.language == Language::Python
                        && !receiver
                        && self
                            .bindings
                            .receivers
                            .get(function)
                            .is_some_and(|s| !s.is_empty()),
                );
            self.add(function,"HAS_PARAMETER",&id,&self.evidence(param),json!({"kind":kind,"position":relative,"receiver":receiver,"default":self.text(default)}));
            let annotation = param.field("type");
            if self.language == Language::Cpp && !cpp_type.is_empty() {
                self.declarations.annotations.push((
                    id.clone(),
                    cpp_type.clone(),
                    self.evidence(param),
                ));
                let head = cpp::parameter_head(&cpp_type);
                self.add(
                    &id,
                    "TYPE_HEAD_STATUS",
                    if head.is_some() {
                        "supported"
                    } else {
                        "unsupported"
                    },
                    &self.evidence(param),
                    json!({"basis":"cpp-parameter-declarator-syntax"}),
                );
                if let Some(head) = head {
                    self.add(
                        &id,
                        "TYPE_HEAD",
                        &head,
                        &self.evidence(param),
                        json!({"basis":"cpp-parameter-declarator-syntax"}),
                    );
                }
            } else if let Some(annotation) = annotation {
                self.annotate(&id, annotation, &self.evidence(param));
            }
            let modifiers = param
                .children()
                .into_iter()
                .filter(|c| matches!(c.kind(), "accessibility_modifier" | "readonly"))
                .map(|c| self.text(Some(c)))
                .collect::<BTreeSet<_>>();
            if self.language == Language::TypeScript
                && direct
                && function_name == "constructor"
                && node.field("body").is_some()
                && pname_node.kind() == "identifier"
                && modifiers
                    .iter()
                    .any(|s| matches!(s.as_str(), "public" | "private" | "protected" | "readonly"))
            {
                let slot = self.storage(&name, cls, param, false);
                self.extend(&slot,json!({"declared":true,"parameter_property":true,"readonly":modifiers.contains("readonly")}));
                self.add(
                    &id,
                    "PARAMETER_INITIALIZES_FIELD",
                    &slot,
                    &self.evidence(param),
                    json!({"basis":"typescript-parameter-property"}),
                );
                self.add(
                    &slot,
                    "ASSIGNED_FROM",
                    &id,
                    &self.evidence(param),
                    json!({"basis":"typescript-parameter-property"}),
                );
                self.add(
                    function,
                    "WRITES",
                    &slot,
                    &self.evidence(param),
                    json!({"implicit":true}),
                );
                if let Some(annotation) = annotation {
                    self.annotate(&slot, annotation, &self.evidence(param));
                }
            }
            if receiver {
                self.bindings.receivers.insert(function.into(), name);
            }
            if variadic {
                keyword = true;
            }
        }
    }
}
