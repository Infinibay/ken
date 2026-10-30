//! Private anti-join witnesses are bound before constraints are traversed.
use crate::{
    Result,
    ast::*,
    capabilities::*,
    expression_check::{Roles, unsupported},
    indexed::{expr, query_expr, remap_expr},
};
fn mapped(map: &Roles, name: &str) -> String {
    map.get(name).cloned().unwrap_or_else(|| name.into())
}
pub(crate) fn compile(
    clauses: &[Clause],
    map: &Roles,
    owner: Option<&str>,
    span: &Span,
    bound: &Roles,
    counter: &mut usize,
) -> Result<Expr> {
    let mut state = Existential {
        bound,
        counter,
        map: map.clone(),
        parameters: vec![],
        constraints: vec![],
        span,
    };
    state.declare(clauses)?;
    state.visit(clauses, owner)?;
    let mut formula = expr("literal", span, "true", vec![])?;
    for constraint in state.constraints {
        formula = expr("binary", span, "and", vec![formula, constraint])?;
    }
    Expr::checked(
        "quantifier".into(),
        span.clone(),
        "exists".into(),
        vec![formula],
        state.parameters,
    )
}
fn call(span: &Span, name: &str, args: Vec<Expr>) -> Result<Expr> {
    expr(
        "call",
        span,
        name,
        args.into_iter()
            .map(|a| expr("argument", span, "", vec![a]))
            .collect::<Result<_>>()?,
    )
}
struct Existential<'a> {
    bound: &'a Roles,
    counter: &'a mut usize,
    map: Roles,
    parameters: Vec<Parameter>,
    constraints: Vec<Expr>,
    span: &'a Span,
}
fn selector_domain(name: &str) -> Option<&'static str> {
    Some(match name {
        "class" | "interface" | "trait" | "type" => "TypeDecl",
        "callable" | "method" | "constructor" => "Callable",
        "field" => "Field",
        "param" => "Parameter",
        "receiver" => "Receiver",
        "module_decl" => "Module",
        "call" => "Call",
        "node" => "CodeNode",
        "expression" => "Expression",
        "statement" => "Statement",
        _ => return None,
    })
}
impl Existential<'_> {
    fn bind(&mut self, name: &str, domain: &str) -> String {
        let translated = mapped(&self.map, name);
        if self.bound.contains_key(&translated)
            || self.parameters.iter().any(|p| p.role == translated)
        {
            return translated;
        }
        *self.counter += 1;
        let translated = format!("@exists:{}:{name}", *self.counter);
        self.map.insert(name.into(), translated.clone());
        self.parameters.push(Parameter {
            r#type: TypeName {
                name: domain.into(),
                arguments: vec![],
            },
            role: translated.clone(),
            direction: "relation".into(),
        });
        translated
    }
    fn declare(&mut self, items: &[Clause]) -> Result<()> {
        crate::with_stack(|| {
            for c in items {
                if c.kind == "selector" {
                    if let Some(domain) = selector_domain(&c.name) {
                        self.bind(&c.role, domain);
                        self.declare(&c.blocks[0])?;
                    }
                } else if c.kind == "from" {
                    for p in &c.parameters {
                        if !vocabulary().types.contains_key(&p.r#type.name)
                            || !p.r#type.arguments.is_empty()
                        {
                            return Err(unsupported("unsupported existential domain", &c.span));
                        }
                        self.bind(&p.role, &p.r#type.name);
                    }
                } else if matches!(c.kind.as_str(), "fields" | "parameters") {
                    self.declare(&c.blocks[0])?;
                }
            }
            Ok(())
        })
    }
    fn visit(&mut self, items: &[Clause], parent: Option<&str>) -> Result<()> {
        crate::with_stack(|| {
            for c in items {
                match c.kind.as_str() {
                    "selector" => {
                        let Some(domain) = selector_domain(&c.name).filter(|_| c.alias.is_empty())
                        else {
                            return Err(unsupported("unsupported existential selector", &c.span));
                        };
                        if c.name == "method" && parent.is_none() {
                            return Err(unsupported(
                                "standalone method classification is not implemented",
                                &c.span,
                            ));
                        }
                        let role = self.bind(&c.role, domain);
                        let entity = expr("role", &c.span, &role, vec![])?;
                        self.constraints.push(call(
                            self.span,
                            "kind_is",
                            vec![
                                entity.clone(),
                                expr(
                                    "literal",
                                    &c.span,
                                    serde_json::to_string(&c.name).unwrap(),
                                    vec![],
                                )?,
                            ],
                        )?);
                        if let Some(parent) = parent {
                            self.constraints.push(call(
                                self.span,
                                "owns",
                                vec![expr("role", &c.span, parent, vec![])?, entity.clone()],
                            )?);
                        }
                        for child in &c.blocks[0] {
                            if child.kind == "property" {
                                if !vocabulary().properties[&c.name].contains_key(&child.name) {
                                    return Err(unsupported(
                                        format!(
                                            "unsupported existential property {}. {}",
                                            crate::parser::quote(&child.name),
                                            property_hint(&child.name)
                                        ),
                                        &child.span,
                                    ));
                                }
                                let mut expected = query_expr(child, 0)?.clone();
                                if expected.kind != "wildcard" {
                                    let prop = expr(
                                        "member",
                                        &child.span,
                                        &child.name,
                                        vec![entity.clone()],
                                    )?;
                                    let constraint =
                                        if matches!(child.name.as_str(), "type" | "return_type") {
                                            expr(
                                                "type_test",
                                                &child.span,
                                                "",
                                                vec![prop, expected],
                                            )?
                                        } else {
                                            if child.name.ends_with("type_status")
                                                && expected.kind == "name"
                                                && matches!(
                                                    expected.value.as_str(),
                                                    "known" | "unknown"
                                                )
                                            {
                                                expected = expr(
                                                    "literal",
                                                    &expected.span,
                                                    serde_json::to_string(&expected.value).unwrap(),
                                                    vec![],
                                                )?;
                                            }
                                            expr(
                                                "binary",
                                                &child.span,
                                                if expected.kind == "regex" {
                                                    "matches"
                                                } else {
                                                    "=="
                                                },
                                                vec![prop, remap_expr(&expected, &self.map)],
                                            )?
                                        };
                                    self.constraints.push(constraint);
                                }
                            } else {
                                self.visit(std::slice::from_ref(child), Some(&role))?;
                            }
                        }
                    }
                    "from" => {
                        for p in &c.parameters {
                            if !vocabulary().types.contains_key(&p.r#type.name)
                                || !p.r#type.arguments.is_empty()
                            {
                                return Err(unsupported("unsupported existential domain", &c.span));
                            }
                            self.bind(&p.role, &p.r#type.name);
                        }
                    }
                    "where" => self
                        .constraints
                        .push(remap_expr(query_expr(c, 0)?, &self.map)),
                    "fields" | "parameters" if c.flags.is_empty() => {
                        self.visit(&c.blocks[0], parent)?
                    }
                    _ => {
                        return Err(unsupported(
                            format!("{} in existential block is not implemented", c.kind),
                            &c.span,
                        ));
                    }
                }
            }
            Ok(())
        })
    }
}
