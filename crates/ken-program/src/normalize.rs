//! Ordered source traversal introduces scopes before lexical binding is applied.
use crate::{
    Link, Node, Operation, Program, ProgramError, Scope, StructuralIr, attributes as attr, kinds,
    parse_type,
};
use std::collections::{BTreeMap, BTreeSet};
fn forest_error() -> ProgramError {
    ProgramError::Invalid("source operations do not form a rooted syntax forest")
}
type Children<'a> = BTreeMap<Option<&'a str>, Vec<&'a str>>;
struct Source<'a> {
    operations: BTreeMap<&'a str, &'a Operation>,
    children: Children<'a>,
}
impl<'a> Source<'a> {
    fn children(&self, key: &'a str) -> &[&'a str] {
        self.children.get(&Some(key)).map_or(&[], Vec::as_slice)
    }
    fn spelling(&self, key: &'a str) -> Result<String, ProgramError> {
        let mut pending = vec![key];
        let mut pieces = Vec::new();
        let mut seen = BTreeSet::new();
        while let Some(key) = pending.pop() {
            if !seen.insert(key) {
                return Err(forest_error());
            }
            let op = self.operations[key];
            if op.attrs.contains_key("text") {
                let text = attr::text(&op.attrs, "text", "")?;
                if !text.is_empty() {
                    pieces.push(text);
                }
            } else {
                pending.extend(self.children(key).iter().rev().copied());
            }
        }
        Ok(pieces.join("."))
    }
}
struct Entry<'a> {
    key: &'a str,
    parent: Option<usize>,
    ordinal: i64,
    inherited: usize,
    exit: bool,
}
pub fn normalize_syntax(ir: &StructuralIr) -> Result<Program, ProgramError> {
    if ir.version != crate::ir::IR_VERSION {
        return Err(ProgramError::Invalid("incompatible IR version"));
    }
    let operations: BTreeMap<_, _> = ir
        .operations
        .iter()
        .map(|op| (op.id.as_str(), op))
        .collect();
    let mut children: Children<'_> = BTreeMap::new();
    for op in &ir.operations {
        let parent = op.parent.as_deref().filter(|p| operations.contains_key(p));
        children.entry(parent).or_default().push(&op.id);
    }
    for siblings in children.values_mut() {
        siblings.sort_by(|a, b| {
            let aop = operations[a];
            let bop = operations[b];
            aop.start
                .cmp(&bop.start)
                .then_with(|| bop.end.cmp(&aop.end))
                .then_with(|| a.cmp(b))
        });
    }
    let source = Source {
        operations,
        children,
    };
    let mut package = String::new();
    for op in &ir.operations {
        if matches!(
            op.native_kind.as_str(),
            "package_clause" | "package_declaration"
        ) {
            package = source
                .children(&op.id)
                .iter()
                .map(|key| source.spelling(key))
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
                .join(".");
        }
    }
    let mut entities = BTreeMap::new();
    for (_, entity) in &ir.entities {
        if kinds::declaration(&entity.kind).is_some()
            && let (Some(start), Some(end), Some(native)) = (
                attr::get(&entity.attrs, "start_byte")?.and_then(|v| v.as_i64()),
                attr::get(&entity.attrs, "end_byte")?.and_then(|v| v.as_i64()),
                attr::get(&entity.attrs, "native_kind")?
                    .and_then(|v| v.as_str().map(str::to_owned)),
            )
        {
            entities.insert((start, end, native), entity);
        }
    }
    let mut operators: BTreeMap<&str, Vec<(i64, String)>> = BTreeMap::new();
    for fact in &ir.facts {
        if fact.relation == "OPERATOR" {
            operators.entry(&fact.subject).or_default().push((
                attr::integer(&fact.attrs, "position", 0)?,
                fact.object.clone(),
            ));
        }
    }
    for values in operators.values_mut() {
        values.sort();
    }
    let mut nodes: Vec<Node> = Vec::new();
    let mut scopes: Vec<Scope> = Vec::new();
    let mut ids: BTreeMap<&str, usize> = BTreeMap::new();
    let mut active = BTreeSet::new();
    let roots = source.children.get(&None).map_or(&[][..], Vec::as_slice);
    let mut stack: Vec<_> = roots
        .iter()
        .enumerate()
        .rev()
        .map(|(ordinal, &key)| Entry {
            key,
            parent: None,
            ordinal: ordinal as i64,
            inherited: 0,
            exit: false,
        })
        .collect();
    while let Some(Entry {
        key,
        parent,
        ordinal,
        inherited,
        exit,
    }) = stack.pop()
    {
        if exit {
            let i = ids[key];
            nodes[i].subtree_end = nodes.len();
            active.remove(key);
            continue;
        }
        if !active.insert(key) {
            return Err(forest_error());
        }
        let op = source.operations[key];
        let i = nodes.len();
        ids.insert(key, i);
        let (mut kind, mut category) = kinds::classify(op, parent.is_none());
        if ir.language == "ruby" && matches!(op.native_kind.as_str(), "do_block" | "block") {
            kind = "callable".into();
            category = "expression".into();
        }
        let entity = entities
            .get(&(op.start, op.end, op.native_kind.clone()))
            .copied();
        let mut name = entity.map_or_else(String::new, |e| e.name.clone());
        if let Some(entity) = entity {
            kind = kinds::declaration(&entity.kind).unwrap().into();
            category = "declaration".into();
        }
        if kind == "identifier" && parent.is_some_and(|p| nodes[p].kind == "parameters") {
            kind = "parameter".into();
            category = "declaration".into();
        }
        if kinds::declarator(&op.native_kind) {
            kind = "variable_declaration".into();
            category = "declaration".into();
        }
        if kind == "literal"
            && source.children(key).iter().any(|child| {
                matches!(
                    source.operations[child].native_kind.as_str(),
                    "interpolation" | "string_interpolation" | "interpolation_expression"
                )
            })
        {
            kind = "interpolated_string".into();
        }
        if name.is_empty()
            && matches!(
                kind.as_str(),
                "namespace" | "callable" | "type_declaration" | "implementation"
            )
            && let Some(child) = source.children(key).iter().find(|child| {
                source.operations[*child].role
                    == if kind == "implementation" {
                        "type"
                    } else {
                        "name"
                    }
            })
        {
            name = source.spelling(child)?;
        }
        if kind == "module" {
            name = ir.path.clone();
        }
        let text = attr::text(&op.attrs, "text", "")?;
        if kind == "identifier" {
            name = text.clone();
        }
        let tokens = attr::tokens(&op.attrs)?;
        let mut flags = BTreeSet::new();
        if attr::truth(&op.attrs, "async")?
            || tokens.iter().any(|t| t == "async")
            || kind == "deferred_block"
        {
            flags.insert("async".into());
        }
        if attr::truth(&op.attrs, "delegated")? {
            flags.insert("delegated".into());
        }
        if attr::text(&op.attrs, "execution", "")? == "unreachable" {
            flags.insert("unreachable".into());
        }
        if kinds::closure(&op.native_kind) && kind == "callable" {
            flags.insert("closure".into());
        }
        if let Some(entity) = entity {
            for field in ["static", "constructor", "generator", "receiver"] {
                if attr::truth(&entity.attrs, field)? {
                    flags.insert(field.into());
                }
            }
        }
        if kind == "opaque" {
            flags.insert("normalization_unknown".into());
        }
        let mut token_ops: Vec<_> = operators
            .get(key)
            .into_iter()
            .flatten()
            .map(|(_, v)| v.clone())
            .collect();
        if token_ops.is_empty()
            && matches!(
                kind.as_str(),
                "assignment" | "variable_declaration" | "binary" | "unary" | "compare" | "update"
            )
        {
            token_ops = tokens.into_iter().filter(|t| kinds::operator(t)).collect();
        }
        let joined = token_ops.join(" ");
        let operator = match joined.as_str() {
            "&&" => "and",
            "||" => "or",
            "!" => "not",
            ":=" => "=",
            _ => &joined,
        }
        .into();
        let type_kind = if let Some(entity) = entity {
            let field = if kind == "callable" {
                "native_return_type"
            } else {
                "native_type"
            };
            match attr::get(&entity.attrs, field)? {
                None => "unknown".into(),
                Some(value) if !attr::truth_value(&value) => "unknown".into(),
                Some(serde_json::Value::String(annotation)) => {
                    parse_type(&annotation, &ir.language).kind
                }
                Some(_) => {
                    return Err(ProgramError::Invalid("type annotation must be a string"));
                }
            }
        } else if kind == "literal" {
            literal_type(&op.native_kind, &text).into()
        } else if matches!(kind.as_str(), "array" | "map" | "tuple" | "set") {
            kind.clone()
        } else {
            String::new()
        };
        let mut scope = inherited;
        if parent.is_none() {
            scope = scopes.len();
            scopes.push(Scope {
                id: scope,
                parent: None,
                node: i,
                kind: "module".into(),
                name: ir.path.clone(),
                namespace: if package.is_empty() {
                    ir.path.clone()
                } else {
                    package.clone()
                },
                lookup_parent: None,
                global_names: vec![],
                nonlocal_names: vec![],
            });
        }
        let canonical_role = parent
            .map_or("", |p| kinds::role(&nodes[p].kind, &op.role))
            .into();
        let introduces = matches!(
            kind.as_str(),
            "namespace"
                | "callable"
                | "type_declaration"
                | "implementation"
                | "comprehension"
                | "deferred_block"
        ) || matches!(kind.as_str(), "block" | "for" | "catch")
            && kinds::block_language(&ir.language);
        let mut child_scope = scope;
        if parent.is_some() && introduces {
            let scope_kind = match kind.as_str() {
                "callable" => "callable",
                "type_declaration" | "implementation" => "type",
                _ => &kind,
            };
            let sid = scopes.len();
            let mut lookup = Some(scope);
            if ir.language == "python" && matches!(kind.as_str(), "callable" | "comprehension") {
                while let Some(id) = lookup {
                    if scopes[id].kind != "type" {
                        break;
                    }
                    lookup = scopes[id].lookup_parent;
                }
            }
            if ir.language == "ruby" && kind == "callable" && !flags.contains("closure") {
                lookup = None;
            }
            let namespace = scopes[scope].namespace.clone()
                + if name.is_empty() {
                    String::new()
                } else {
                    ".".to_owned() + &name
                }
                .as_str();
            scopes.push(Scope {
                id: sid,
                parent: Some(scope),
                node: i,
                kind: scope_kind.into(),
                name: name.clone(),
                namespace,
                lookup_parent: lookup,
                global_names: vec![],
                nonlocal_names: vec![],
            });
            child_scope = sid;
        }
        nodes.push(Node {
            id: i,
            kind: kind.clone(),
            category,
            parent,
            ordinal,
            role: canonical_role,
            native_role: op.role.clone(),
            native_kind: op.native_kind.clone(),
            source_id: key.into(),
            start: op.start,
            end: op.end,
            line: op.line,
            scope,
            owner: op.owner.clone(),
            name,
            text,
            operator,
            type_kind,
            flags: flags.into_iter().collect(),
            subtree_end: 0,
            argument_kind: String::new(),
            argument_name: String::new(),
            argument_position: None,
            source_position: None,
        });
        stack.push(Entry {
            key,
            parent,
            ordinal,
            inherited: scope,
            exit: true,
        });
        for (position, &child) in source.children(key).iter().enumerate().rev() {
            let native_role = source.operations[child].role.as_str();
            let mut selected = if introduces
                && matches!(
                    native_role,
                    "name" | "superclass" | "superclasses" | "interfaces" | "decorator"
                ) {
                scope
            } else {
                child_scope
            };
            if ir.language == "python"
                && kind == "parameter"
                && matches!(native_role, "value" | "type")
            {
                selected = scopes[scope].parent.unwrap_or(scope);
            }
            if ir.language == "python" && kind == "comprehension_clause" && native_role == "right" {
                let siblings = op.parent.as_deref().map_or(&[][..], |p| source.children(p));
                if siblings
                    .iter()
                    .find(|c| source.operations[*c].native_kind == "for_in_clause")
                    .copied()
                    == Some(key)
                    && scopes[scope].kind == "comprehension"
                {
                    selected = scopes[scope].parent.unwrap_or(scope);
                }
            }
            stack.push(Entry {
                key: child,
                parent: Some(i),
                ordinal: position as i64,
                inherited: selected,
                exit: false,
            });
        }
    }
    if nodes.len() != source.operations.len() {
        return Err(forest_error());
    }
    let mut links = BTreeSet::new();
    for fact in &ir.facts {
        let relation = match fact.relation.as_str() {
            "OPERAND" => "operand",
            "CONTROL_CONDITION" => "condition",
            "CONTROL_BODY" => "body",
            "CONTROL_ALTERNATIVE" => "else",
            "CONTROL_INITIALIZER" => "init",
            "CONTROL_UPDATE" => "step",
            _ => continue,
        };
        if let (Some(&from), Some(&to)) = (
            ids.get(fact.subject.as_str()),
            ids.get(fact.object.as_str()),
        ) {
            links.insert((
                from,
                relation.to_owned(),
                attr::integer(&fact.attrs, "position", 0)?,
                to,
            ));
        }
    }
    argument_metadata(&source, &mut nodes, &mut links)?;
    let program = Program {
        path: ir.path.clone(),
        language: ir.language.clone(),
        nodes,
        scopes,
        symbols: vec![],
        references: vec![],
        links: links
            .into_iter()
            .map(|(source, relation, ordinal, target)| Link {
                source,
                relation,
                target,
                ordinal,
            })
            .collect(),
        diagnostics: ir.diagnostics.clone(),
        version: crate::model::VERSION.into(),
    };
    program.validate()?;
    Ok(program)
}
fn literal_type(native: &str, text: &str) -> &'static str {
    if matches!(text, "true" | "false" | "True" | "False") {
        "bool"
    } else if matches!(text, "None" | "null" | "nil") {
        "null"
    } else if native.contains("char") || native.contains("rune") {
        "char"
    } else if native.contains("string") {
        "str"
    } else if native.contains("float")
        || native.contains("real")
        || matches!(native, "number" | "number_literal")
            && (text.contains('.')
                || !text.as_bytes().get(..2).is_some_and(|b| {
                    b[0] == b'0' && matches!(b[1].to_ascii_lowercase(), b'x' | b'o' | b'b')
                }) && text.contains(['e', 'E', 'f', 'F', 'd', 'D']))
    {
        "float"
    } else {
        "int"
    }
}
fn argument_metadata(
    source: &Source<'_>,
    nodes: &mut [Node],
    links: &mut BTreeSet<(usize, String, i64, usize)>,
) -> Result<(), ProgramError> {
    let mut children = vec![Vec::new(); nodes.len()];
    for node in nodes.iter() {
        if let Some(parent) = node.parent {
            children[parent].push(node.id);
        }
    }
    for call in 0..nodes.len() {
        if nodes[call].kind != "call" {
            continue;
        }
        for &group in &children[call] {
            if nodes[group].kind != "arguments" || nodes[group].native_role == "type_arguments" {
                continue;
            }
            let mut expanded = false;
            let arguments: Vec<_> = children[group]
                .iter()
                .copied()
                .filter(|&c| nodes[c].category != "trivia")
                .collect();
            for (position, argument) in arguments.into_iter().enumerate() {
                let node = &nodes[argument];
                let tokens = attr::tokens(&source.operations[node.source_id.as_str()].attrs)?;
                let keyword = children[argument]
                    .iter()
                    .find(|&&c| nodes[c].native_role == "name")
                    .filter(|_| {
                        matches!(
                            node.native_kind.as_str(),
                            "keyword_argument" | "named_argument" | "argument"
                        )
                    })
                    .map_or_else(String::new, |&c| nodes[c].text.clone());
                let spread = node.kind == "spread"
                    || tokens
                        .iter()
                        .any(|t| matches!(t.as_str(), "*" | "**" | "..."));
                let kind = if spread {
                    if tokens.iter().any(|t| t == "**") {
                        "spread_named"
                    } else {
                        "spread_positional"
                    }
                } else if !keyword.is_empty() {
                    "named"
                } else {
                    "positional"
                };
                let effective =
                    (!expanded && !spread && keyword.is_empty()).then_some(position as i64);
                expanded |= spread;
                let node = &mut nodes[argument];
                node.argument_kind = kind.into();
                node.argument_name = keyword;
                node.argument_position = effective;
                node.source_position = Some(position as i64);
                links.insert((call, "argument".into(), position as i64, argument));
            }
        }
    }
    Ok(())
}

/// Complete source model: structural normalization followed by shared lexical policy.
pub fn normalize(ir: &StructuralIr) -> Result<Program, ProgramError> {
    let mut program = normalize_syntax(ir)?;
    crate::bindings::bind(ir, &mut program)?;
    program.validate()?;
    Ok(program)
}
