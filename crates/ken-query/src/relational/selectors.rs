//! Source selector ownership and property rules lower to canonical graph clauses.
use super::{terms::json_string, vocabulary};
use crate::{
    Result, ast::*, capabilities, compile_budget::WorkBudget, expression_check::unsupported,
};
pub(crate) fn expr(
    kind: &str,
    span: &Span,
    value: impl Into<String>,
    args: Vec<Expr>,
) -> Result<Expr> {
    Expr::checked(kind.into(), span.clone(), value.into(), args, vec![])
}
fn literal(span: &Span, value: &str) -> Result<Expr> {
    expr("literal", span, json_string(value), vec![])
}
fn boolean(span: &Span, value: bool) -> Result<Expr> {
    expr(
        "literal",
        span,
        if value { "true" } else { "false" },
        vec![],
    )
}
fn role(span: &Span, value: &str) -> Result<Expr> {
    expr("role", span, value, vec![])
}
fn edge(span: &Span, name: &str, a: Expr, b: Expr, props: Vec<Clause>) -> Clause {
    let mut c = Clause::new("edge", span.clone());
    c.name = name.into();
    c.expressions = vec![Expression::Query(a), Expression::Query(b)];
    c.blocks = vec![props];
    c
}
fn property(span: &Span, name: &str, value: Expr) -> Clause {
    let mut c = Clause::new("property", span.clone());
    c.name = name.into();
    c.expressions = vec![Expression::Query(value)];
    c
}
fn value(c: &Clause) -> Result<&Expr> {
    crate::indexed::query_expr(c, 0)
}
fn source_type(span: &Span, owner: &str, name: &str, value: Expr) -> Clause {
    let mut c = Clause::new("source_type", span.clone());
    c.name = name.into();
    c.role = owner.into();
    c.expressions = vec![Expression::Query(value)];
    c
}
pub(crate) fn selector(
    c: &Clause,
    owner: Option<(&str, &str)>,
    budget: &mut WorkBudget,
) -> Result<Vec<Clause>> {
    budget.clause(c)?;
    let span = &c.span;
    let kind = c.name.as_str();
    let name = c.role.as_str();
    let fail = |m| unsupported(m, span);
    let Some(native) = vocabulary().kinds.get(kind) else {
        return Err(fail("unsupported source selector or selector alias"));
    };
    if !c.alias.is_empty() {
        return Err(fail("unsupported source selector or selector alias"));
    }
    let props = c.blocks.first().map_or(&[][..], Vec::as_slice);
    if kind == "type_parameter" {
        let Some((parent, domain)) = owner.filter(|(_, d)| {
            matches!(
                *d,
                "type"
                    | "class"
                    | "interface"
                    | "trait"
                    | "callable"
                    | "method"
                    | "function"
                    | "constructor"
            )
        }) else {
            return Err(fail("type parameters require a generic declaration"));
        };
        let _ = domain;
        if props.iter().any(|p| p.kind != "property") {
            return Err(fail("type parameters currently take no properties"));
        }
        return Ok(vec![edge(
            span,
            "BINDS_TYPE_PARAMETER",
            role(span, parent)?,
            role(span, name)?,
            vec![],
        )]);
    }
    if kind == "macro" {
        let Some((parent, _)) =
            owner.filter(|(_, d)| matches!(*d, "callable" | "method" | "constructor"))
        else {
            return Err(fail("macro requires a callable owner"));
        };
        if props
            .iter()
            .any(|p| p.kind != "property" || p.name != "name")
        {
            return Err(fail("macro currently supports name"));
        }
        if props.len() > 1 {
            return Err(fail("duplicate macro name property"));
        }
        let subject = role(span, name)?;
        let named = role(span, &format!("{name}__macro_name"))?;
        let mut names = vec![property(span, "role", literal(span, "macro")?)];
        for p in props {
            let mut p = p.clone();
            p.name = "text".into();
            names.push(p);
        }
        return Ok(vec![
            edge(
                span,
                "HAS_OPERATION",
                role(span, parent)?,
                subject.clone(),
                vec![],
            ),
            edge(
                span,
                "OPERATION",
                subject.clone(),
                expr("wildcard", span, "_", vec![])?,
                vec![property(
                    span,
                    "native_kind",
                    literal(span, "macro_invocation")?,
                )],
            ),
            edge(span, "SYNTAX_PARENT", named.clone(), subject, vec![]),
            edge(span, "OPERATION", named, literal(span, "NATIVE")?, names),
        ]);
    }
    if kind == "receiver" {
        let Some((parent, _)) =
            owner.filter(|(_, d)| matches!(*d, "callable" | "method" | "constructor"))
        else {
            return Err(fail("receiver requires a callable owner"));
        };
        let mut c = Clause::new("source_receiver", span.clone());
        c.role = name.into();
        c.name = parent.into();
        let mut result = vec![c];
        for p in props {
            let v = value(p)?;
            if p.kind != "property"
                || p.name != "escapes"
                || v.kind != "literal"
                || !matches!(v.value.as_str(), "true" | "false")
            {
                return Err(unsupported(
                    "receiver accepts escapes: true or false",
                    &p.span,
                ));
            }
            result.push(source_type(
                span,
                name,
                &format!("escapes:{parent}"),
                v.clone(),
            ));
        }
        return Ok(result);
    }
    let mut properties: Vec<_> = props.iter().collect();
    if kind == "field" {
        let effective: Vec<_> = properties
            .iter()
            .copied()
            .filter(|p| p.kind == "property" && p.name == "effective")
            .collect();
        if !effective.is_empty() {
            if effective.len() != 1
                || value(effective[0])?.kind != "literal"
                || !matches!(value(effective[0])?.value.as_str(), "true" | "false")
            {
                return Err(fail("effective requires a boolean literal"));
            }
            properties.retain(|p| !effective.contains(p));
            if value(effective[0])?.value == "true" {
                let Some((parent, _)) =
                    owner.filter(|(_, d)| matches!(*d, "type" | "class" | "interface" | "trait"))
                else {
                    return Err(fail("effective field requires a type owner"));
                };
                if properties.iter().any(|p| {
                    p.kind != "property"
                        || !matches!(
                            p.name.as_str(),
                            "name" | "type" | "static" | "visibility" | "declaration"
                        )
                }) {
                    return Err(fail(
                        "effective field supports name, type, static, visibility and declaration",
                    ));
                }
                let names: std::collections::BTreeSet<_> =
                    properties.iter().map(|p| &p.name).collect();
                if names.len() != properties.len() {
                    return Err(fail("duplicate effective field property"));
                }
                let mut c = Clause::new("source_effective_field", span.clone());
                c.role = name.into();
                c.name = parent.into();
                c.blocks = vec![properties.into_iter().cloned().collect()];
                return Ok(vec![c]);
            }
        }
        if properties
            .iter()
            .any(|p| p.kind == "property" && p.name == "declaration")
        {
            return Err(fail("declaration requires effective: true"));
        }
    }
    let subject = role(span, name)?;
    let mut rows = vec![];
    let mut filters = vec![];
    let mut scalar = vec![];
    let mut nested = vec![];
    let mut seen = std::collections::BTreeSet::new();
    let mut endpoint = if native.contains('|') {
        expr(
            "list",
            span,
            "",
            native
                .split('|')
                .map(|v| literal(span, v))
                .collect::<Result<_>>()?,
        )?
    } else {
        literal(span, native)?
    };
    if kind == "operation" {
        endpoint = expr("wildcard", span, "_", vec![])?;
    }
    for child in properties {
        if child.kind != "property" {
            nested.push(child);
            continue;
        }
        if !capabilities::vocabulary()
            .properties
            .get(kind)
            .is_some_and(|p| p.contains_key(&child.name))
        {
            return Err(unsupported(
                format!("unknown {kind} property {}", child.name),
                &child.span,
            ));
        }
        if !seen.insert(&child.name) {
            return Err(unsupported(
                format!("duplicate {kind} property {}", child.name),
                &child.span,
            ));
        }
        let mut prop = child.clone();
        let mut v = value(child)?.clone();
        if child.name == "visibility" && v.kind == "name" {
            if !matches!(
                v.value.as_str(),
                "public" | "private" | "protected" | "internal" | "package"
            ) {
                return Err(unsupported("unknown visibility", &child.span));
            }
            v = literal(span, &v.value)?;
            prop.expressions = vec![Expression::Query(v.clone())];
        }
        if v.kind == "wildcard" {
            continue;
        }
        let prop_fail = |m| unsupported(m, &child.span);
        match child.name.as_str() {
            "captures" => {
                if v.kind != "role" {
                    return Err(prop_fail("captures requires a binding role"));
                }
                let mut c = Clause::new("source_capture", child.span.clone());
                c.role = v.value.clone();
                rows.push(c);
                rows.push(edge(span, "CAPTURES", subject.clone(), v, vec![]));
            }
            "exported" => {
                if v.kind != "literal" || v.value != "true" {
                    return Err(prop_fail(
                        "exported currently requires true; absence of exports is not closed",
                    ));
                }
                let exporter = if let Some((p, "module_decl")) = owner {
                    role(span, p)?
                } else {
                    expr("wildcard", span, "_", vec![])?
                };
                rows.push(edge(span, "EXPORT", exporter, subject.clone(), vec![]));
            }
            "result_family" if kind == "call" => {
                let family = v.value.trim_matches('"');
                if !matches!(v.kind.as_str(), "name" | "literal")
                    || !matches!(family, "scalar" | "unknown")
                {
                    return Err(prop_fail(
                        "result_family currently supports scalar or unknown",
                    ));
                }
                rows.push(edge(
                    span,
                    "CALL_RESULT_KIND",
                    subject.clone(),
                    literal(span, family)?,
                    vec![],
                ));
            }
            "derive" if kind == "type" => {
                if !matches!(v.kind.as_str(), "literal" | "name") {
                    return Err(prop_fail("derive requires a name"));
                }
                let spelling = if v.kind == "literal" && v.value.starts_with('"') {
                    serde_json::from_str::<String>(&v.value)
                        .map_err(|_| prop_fail("derive requires a name"))?
                } else {
                    v.value.clone()
                };
                rows.push(edge(
                    span,
                    "DERIVE_NAME",
                    subject.clone(),
                    literal(span, &spelling)?,
                    vec![],
                ));
            }
            "entry" | "receiver" if kind == "call" => {
                if v.kind != "role" {
                    return Err(prop_fail(if child.name == "entry" {
                        "entry requires a place role"
                    } else {
                        "receiver requires a place role"
                    }));
                }
                rows.push(edge(
                    span,
                    if child.name == "entry" {
                        "CALL_ENTRY_BINDING"
                    } else {
                        "RECEIVER"
                    },
                    subject.clone(),
                    v,
                    vec![],
                ));
            }
            "resolution" if kind == "call" => {
                let status = v.value.trim_matches('"');
                if !matches!(v.kind.as_str(), "name" | "literal")
                    || !matches!(status, "resolved" | "unresolved" | "ambiguous")
                {
                    return Err(prop_fail(
                        "resolution requires resolved, unresolved or ambiguous",
                    ));
                }
                scalar.push(property(span, "resolution", literal(span, status)?));
            }
            "discarded" if kind == "call" => {
                if v.kind != "literal" || v.value != "true" {
                    return Err(prop_fail(
                        "discarded currently requires true; the default is that the result is consumed",
                    ));
                }
                rows.push(edge(
                    span,
                    "DISCARDS_RESULT",
                    expr("wildcard", span, "_", vec![])?,
                    subject.clone(),
                    vec![],
                ));
            }
            "target" if kind == "call" => {
                if v.kind != "role" {
                    return Err(prop_fail("call target requires a Callable role"));
                }
                let mut c = Clause::new("either", span.clone());
                c.blocks = vec![
                    vec![edge(span, "TARGET", subject.clone(), v.clone(), vec![])],
                    vec![edge(span, "DECLARED_TARGET", subject.clone(), v, vec![])],
                ];
                rows.push(c);
            }
            "base" if matches!(kind, "class" | "interface" | "trait" | "type") => {
                if v.kind != "role" {
                    return Err(prop_fail("base requires a place role"));
                }
                rows.push(edge(span, "BASE_INPUT", subject.clone(), v, vec![]));
            }
            "initial" | "writes" => {
                if child.name == "initial" {
                    if v.kind != "literal" || v.value != "null" {
                        return Err(prop_fail("initial currently supports null"));
                    }
                } else if v.kind != "call"
                    || v.value != "exactly"
                    || v.args.len() != 2
                    || v.args
                        .iter()
                        .any(|a| a.kind != "argument" || !a.value.is_empty() || a.args.len() != 1)
                    || v.args[0].args[0].kind != "role"
                    || v.args[1].args[0].kind != "literal"
                    || v.args[1].args[0].value.is_empty()
                    || !v.args[1].args[0].value.bytes().all(|b| b.is_ascii_digit())
                {
                    return Err(prop_fail(
                        "writes requires exactly($binding, nonnegative_integer)",
                    ));
                }
                filters.push(source_type(span, name, &child.name, v));
            }
            "reassigned" | "completes" => {
                if v.kind != "literal" || !matches!(v.value.as_str(), "true" | "false") {
                    return Err(prop_fail(if child.name == "reassigned" {
                        "reassigned requires a boolean"
                    } else {
                        "completes requires a boolean"
                    }));
                }
                filters.push(source_type(span, name, &child.name, v));
            }
            "type" | "return_type" | "type_status" | "return_type_status" => {
                if child.name == "return_type"
                    && v.kind == "call"
                    && v.value == "applied"
                    && v.args.len() == 2
                {
                    if v.args.iter().any(|a| {
                        a.kind != "argument"
                            || !a.value.is_empty()
                            || a.args.len() != 1
                            || a.args[0].kind != "role"
                    }) {
                        return Err(prop_fail(
                            "applied requires the declaring type and a type argument role",
                        ));
                    }
                    if owner.is_some_and(|(p, _)| v.args[0].args[0].value != p) {
                        return Err(prop_fail("applied requires the enclosing type as its base"));
                    }
                    rows.push(edge(
                        span,
                        "RETURN_TYPE_ARGUMENT",
                        subject.clone(),
                        role(span, &v.args[1].args[0].value)?,
                        vec![],
                    ));
                    continue;
                }
                let argument = if v.kind == "call" && v.args.len() == 1 {
                    v.args.first().filter(|a| {
                        a.kind == "argument"
                            && a.value.is_empty()
                            && a.args.len() == 1
                            && a.args[0].kind == "role"
                    })
                } else {
                    None
                };
                if child.name == "type"
                    && matches!(v.value.as_str(), "nominal" | "parameter")
                    && let Some(a) = argument
                {
                    let relation = if v.value == "nominal" {
                        "TYPE"
                    } else if matches!(kind, "param" | "receiver") {
                        "TYPE_PARAMETER"
                    } else {
                        "TYPE_NAME"
                    };
                    rows.push(edge(
                        span,
                        relation,
                        subject.clone(),
                        role(span, &a.args[0].value)?,
                        vec![],
                    ));
                    continue;
                }
                if child.name.ends_with("_status") {
                    if !matches!(v.value.trim_matches('"'), "known" | "unknown") {
                        return Err(prop_fail("type status requires known or unknown"));
                    }
                } else {
                    crate::source_matcher::validate_matcher(&v)
                        .map_err(|e| unsupported(e.to_string(), &child.span))?;
                }
                filters.push(source_type(span, name, &child.name, v));
            }
            "kind" if kind == "operation" => {
                if !matches!(v.kind.as_str(), "name" | "literal") {
                    return Err(prop_fail("operation kind requires a name"));
                }
                endpoint = literal(span, &v.value.trim_matches('"').to_uppercase())?;
            }
            _ => scalar.push(prop),
        }
    }
    if kind == "constructor" {
        scalar.push(property(span, "constructor", boolean(span, true)?));
    }
    if kind == "trait" {
        scalar.push(property(span, "native_kind", literal(span, "trait_item")?));
    }
    if matches!(kind, "param" | "receiver") {
        scalar.push(property(
            span,
            "receiver",
            boolean(span, kind == "receiver")?,
        ));
    }
    rows.push(edge(
        span,
        if kind == "operation" {
            "OPERATION"
        } else {
            "ENTITY"
        },
        subject.clone(),
        endpoint,
        scalar,
    ));
    if let Some((parent, parent_kind)) = owner {
        let type_owner = matches!(parent_kind, "type" | "class" | "interface" | "trait");
        let callable = matches!(parent_kind, "callable" | "method" | "constructor");
        let relation = if type_owner && matches!(kind, "method" | "constructor" | "callable") {
            Some("HAS_METHOD")
        } else if type_owner && kind == "field" {
            Some("HAS_FIELD")
        } else if callable && matches!(kind, "param" | "receiver") {
            Some("HAS_PARAMETER")
        } else if callable && kind == "operation" {
            Some("HAS_OPERATION")
        } else if callable && kind == "call" {
            Some("HAS_CALL")
        } else if parent_kind == "module_decl"
            || callable
                && matches!(
                    kind,
                    "var" | "callable" | "class" | "interface" | "trait" | "type"
                )
        {
            Some("DECLARES")
        } else {
            None
        };
        let Some(relation) = relation else {
            return Err(unsupported(
                format!("{parent_kind} cannot immediately own {kind}"),
                span,
            ));
        };
        rows.push(edge(span, relation, role(span, parent)?, subject, vec![]));
    } else if matches!(kind, "method" | "constructor" | "field") {
        rows.push(edge(
            span,
            if kind == "field" {
                "HAS_FIELD"
            } else {
                "HAS_METHOD"
            },
            expr("wildcard", span, "_", vec![])?,
            subject,
            vec![],
        ));
    }
    let mut bodies = vec![];
    for child in nested {
        if child.kind == "body" {
            bodies.push(child);
            continue;
        }
        if matches!(child.kind.as_str(), "fields" | "parameters") {
            if !child.flags.is_empty() {
                return Err(unsupported(
                    "exact member inventory in relational selectors is not implemented",
                    &child.span,
                ));
            }
            for c in child.blocks.first().map_or(&[][..], Vec::as_slice) {
                rows.push(owned(c, name, kind));
            }
        } else {
            rows.push(owned(child, name, kind));
        }
    }
    rows.extend(filters);
    for child in bodies {
        rows.push(owned(child, name, kind));
    }
    Ok(rows)
}
fn owned(c: &Clause, name: &str, kind: &str) -> Clause {
    let mut result = Clause::new("source_owned", c.span.clone());
    result.role = name.into();
    result.name = kind.into();
    result.blocks = vec![vec![c.clone()]];
    result
}
