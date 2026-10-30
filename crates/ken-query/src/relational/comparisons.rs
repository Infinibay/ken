//! Semantic relations own their witness chains and positive-binding requirements.
use super::{
    ir::*,
    lower::Context,
    terms::{operand, text_literal},
    vocabulary,
};
use crate::{Result, ast::*, capabilities, expression_check::unsupported};
use std::collections::{BTreeMap, BTreeSet};

/// Candidate hints belong to a block, whose bound set only grows. Branches get
/// their own hints so alternatives retain the original private naming order.
#[derive(Default)]
pub(super) struct WitnessNames {
    next: BTreeMap<String, String>,
}
impl Context<'_, '_> {
    pub(super) fn comparison(
        &mut self,
        e: &Expr,
        bound: &mut BTreeSet<String>,
        nodes: &mut Vec<Node>,
        witnesses: &mut WitnessNames,
    ) -> Result<()> {
        crate::with_stack(|| {
            self.charge_expression(e)?;
            if e.kind == "binary" && e.value == "and" {
                for a in &e.args {
                    self.comparison(a, bound, nodes, witnesses)?;
                }
                return Ok(());
            }
            let name = e.value.as_str();
            let caps = capabilities::vocabulary();
            let fail = |m| unsupported(m, &e.span);
            if e.kind == "call" {
                if let Some((relation, expected)) = caps.unary_relations.get(name) {
                    let a = arguments(e, 1, false, "unary semantic relation requires one role")?;
                    positive(&a, bound, e)?;
                    nodes.push(fact(
                        Term::Text(a[0].clone()),
                        relation,
                        text_literal(expected, &e.span)?,
                        vec![],
                    ));
                    return Ok(());
                }
                if let Some((relation, _, _)) = caps.relations.get(name) {
                    let a = arguments(
                        e,
                        2,
                        true,
                        "semantic relation requires two named source roles",
                    )?;
                    positive(&a, bound, e)?;
                    nodes.push(fact(
                        Term::Text(a[0].clone()),
                        relation,
                        Term::Text(a[1].clone()),
                        vocabulary()
                            .semantic_attrs
                            .get(name)
                            .cloned()
                            .unwrap_or_default(),
                    ));
                    return Ok(());
                }
                if name == "initialized_with" {
                    if !matches!(e.args.len(), 2 | 3) {
                        return Err(fail(
                            "initialized_with requires two roles and an optional name",
                        ));
                    }
                    let a = argument_slice(
                        &e.args[..2],
                        false,
                        "initialized_with requires two roles and an optional name",
                        e,
                    )?;
                    positive(&a, bound, e)?;
                    let call = witnesses.fresh("initializer_call", bound, self)?;
                    let argument = witnesses.fresh("initializer_argument", bound, self)?;
                    nodes.push(fact(
                        Term::Text(a[0].clone()),
                        "ASSIGNED_FROM",
                        Term::Text(call.clone()),
                        vec![],
                    ));
                    nodes.push(fact(
                        Term::Text(call.clone()),
                        "ARGUMENT",
                        Term::Text(argument.clone()),
                        vec![],
                    ));
                    nodes.push(fact(
                        Term::Text(argument),
                        "VALUE",
                        Term::Text(a[1].clone()),
                        vec![],
                    ));
                    if let Some(third) = e.args.get(2) {
                        if third.value != "name"
                            || third.args.len() != 1
                            || third.args[0].kind != "literal"
                        {
                            return Err(fail("initialized_with name requires a string pattern"));
                        }
                        let pattern = serde_json::from_str::<String>(&third.args[0].value)
                            .map_err(|_| fail("initialized_with name requires a string pattern"))?;
                        super::regex_pattern::validate(&pattern, &e.span)?;
                        nodes.push(fact(
                            Term::Text(call),
                            "ENTITY",
                            text_literal("CALL", &e.span)?,
                            vec![("name".into(), "regex".into(), pattern)],
                        ));
                    }
                    return Ok(());
                }
                if name == "receives" {
                    let a = arguments(e, 2, false, "receives requires two named roles")?;
                    positive(&a, bound, e)?;
                    let binding = witnesses.fresh("receives_binding", bound, self)?;
                    let values = [
                        witnesses.fresh("receives_value", bound, self)?,
                        witnesses.fresh("receives_allocation", bound, self)?,
                    ];
                    nodes.push(fact(
                        Term::Text(binding.clone()),
                        "BINDING_PARAMETER",
                        Term::Text(a[0].clone()),
                        vec![],
                    ));
                    let mut branches = vec![];
                    for (value, relation) in values.into_iter().zip(["TYPE", "ALLOCATES_TYPE"]) {
                        branches.push(vec![
                            fact(
                                Term::Text(binding.clone()),
                                "BINDING_VALUE",
                                Term::Text(value.clone()),
                                vec![],
                            ),
                            fact(
                                Term::Text(value),
                                relation,
                                Term::Text(a[1].clone()),
                                vec![],
                            ),
                        ]);
                    }
                    nodes.push(Node::branches("any", PlanValue::None, branches));
                    return Ok(());
                }
                if name == "instance_slot" {
                    let a = arguments(e, 2, false, "instance_slot requires two named roles")?;
                    positive(&a, bound, e)?;
                    nodes.push(fact(
                        Term::Text(a[0].clone()),
                        "INSTANCE_SLOT",
                        Term::Text(a[1].clone()),
                        vec![],
                    ));
                    return Ok(());
                }
                if name == "preserves" {
                    let a = arguments(e, 2, false, "preserves requires two named roles")?;
                    positive(&a, bound, e)?;
                    let identity = witnesses.fresh("preserved_return_return", bound, self)?;
                    let mut names = Vec::with_capacity(4);
                    for n in ["return", "wrapper", "argument", "loaded"] {
                        names.push(witnesses.fresh(
                            &format!("preserved_wrapper_{n}"),
                            bound,
                            self,
                        )?);
                    }
                    let attrs = vec![("execution".into(), "literal".into(), "possible".into())];
                    let text = |v: &str| Term::Text(v.into());
                    nodes.push(Node::branches(
                        "any",
                        PlanValue::None,
                        vec![
                            vec![
                                fact(text(&a[0]), "HAS_OPERATION", text(&identity), attrs.clone()),
                                fact(text(&identity), "RETURN_ORIGIN", text(&a[1]), vec![]),
                            ],
                            vec![
                                fact(text(&a[0]), "HAS_OPERATION", text(&names[0]), attrs),
                                fact(text(&names[0]), "RETURN_ORIGIN", text(&names[1]), vec![]),
                                fact(text(&names[1]), "ARGUMENT", text(&names[2]), vec![]),
                                fact(text(&names[2]), "VALUE", text(&names[3]), vec![]),
                                fact(text(&names[3]), "LOADED_FROM", text(&a[1]), vec![]),
                            ],
                        ],
                    ));
                    return Ok(());
                }
                if let Some((relation, expected)) = caps.statement_unary.get(name) {
                    let a = arguments(e, 1, false, "statement relation requires one named role")?;
                    positive(&a, bound, e)?;
                    nodes.push(fact(
                        Term::Text(a[0].clone()),
                        relation,
                        text_literal(expected, &e.span)?,
                        vec![],
                    ));
                    return Ok(());
                }
                if let Some(relation) = caps.statement_relations.get(name) {
                    let a = arguments(e, 2, false, "statement relation requires two named roles")?;
                    positive(&a, bound, e)?;
                    if name == "returns_operand" {
                        if !bound.insert("returned_operand".into()) {
                            return Err(fail("statement relation witness requires a fresh role"));
                        }
                        nodes.push(Node::new(
                            "path",
                            PlanValue::tuple(vec![
                                PlanValue::text(&a[1]),
                                PlanValue::text(relation),
                                PlanValue::text(&a[0]),
                                PlanValue::number(1),
                                PlanValue::number(4),
                                PlanValue::text("$returned_operand"),
                            ]),
                        ));
                    } else {
                        nodes.push(fact(
                            Term::Text(a[0].clone()),
                            relation,
                            Term::Text(a[1].clone()),
                            if name == "runs" {
                                vec![("execution".into(), "literal".into(), "possible".into())]
                            } else {
                                vec![]
                            },
                        ));
                    }
                    return Ok(());
                }
            }
            if e.kind != "binary"
                || !matches!(name, "==" | "!=" | "<" | "<=" | ">" | ">=")
                || e.args.len() != 2
            {
                return Err(fail(
                    "graph where currently requires comparisons joined by and",
                ));
            }
            let values = e.args.iter().map(operand).collect::<Result<Vec<_>>>()?;
            positive(&values, bound, e)?;
            if name == "!=" && e.args.iter().all(|e| e.kind == "role") {
                nodes.push(Node::new(
                    "different",
                    PlanValue::tuple(values.into_iter().map(PlanValue::text).collect()),
                ));
            } else {
                nodes.push(Node::new(
                    "where",
                    PlanValue::tuple(vec![
                        PlanValue::text(&values[0]),
                        PlanValue::text(match name {
                            "==" => "literal",
                            "!=" => "not_literal",
                            v => v,
                        }),
                        PlanValue::text(&values[1]),
                    ]),
                ));
            }
            Ok(())
        })
    }
}
fn arguments(e: &Expr, count: usize, members: bool, message: &str) -> Result<Vec<String>> {
    if e.args.len() != count {
        return Err(unsupported(message, &e.span));
    }
    argument_slice(&e.args, members, message, e)
}
fn argument_slice(args: &[Expr], members: bool, message: &str, e: &Expr) -> Result<Vec<String>> {
    let mut values = vec![];
    for a in args {
        if a.kind != "argument"
            || !a.value.is_empty()
            || a.args.len() != 1
            || !(a.args[0].kind == "role"
                || members
                    && a.args[0].kind == "member"
                    && a.args[0].args.first().is_some_and(|e| e.kind == "role"))
        {
            return Err(unsupported(message, &e.span));
        }
        values.push(operand(&a.args[0])?);
    }
    Ok(values)
}
fn positive(values: &[String], bound: &BTreeSet<String>, e: &Expr) -> Result<()> {
    if values
        .iter()
        .filter_map(|v| v.strip_prefix('$'))
        .any(|v| !bound.contains(v.split('.').next().unwrap_or("")))
    {
        return Err(unsupported(
            "where requires positively bound roles",
            &e.span,
        ));
    }
    Ok(())
}
impl WitnessNames {
    fn fresh(
        &mut self,
        base: &str,
        bound: &mut BTreeSet<String>,
        context: &mut Context<'_, '_>,
    ) -> Result<String> {
        let mut name = self
            .next
            .get(base)
            .cloned()
            .unwrap_or_else(|| base.to_owned());
        while bound.contains(&name) {
            context.charge_work(1 + name.len() / 64)?;
            name.push('_');
        }
        // Account for every copied generated token, including its growing suffix.
        context.charge_work(1 + name.len() / 64)?;
        bound.insert(name.clone());
        self.next.insert(base.into(), format!("{name}_"));
        Ok(format!("${name}"))
    }
}
