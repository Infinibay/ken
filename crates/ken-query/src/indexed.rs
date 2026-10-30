//! Indexed capability lowering: ordered bindings, hygienic patterns and checks.
use crate::{
    Predicate, Result,
    ast::*,
    capabilities::*,
    checked::*,
    expression_check::{ExpressionChecker, Roles, unsupported, wrapped},
};
use std::collections::{BTreeMap, BTreeSet};
pub fn compile_indexed(tree: &File, query: Option<&str>) -> Result<IndexedProgram> {
    crate::validation::tree(tree)?;
    crate::syntax_shape::tree(tree)?;
    let declarations: BTreeMap<_, _> = tree
        .declarations
        .iter()
        .map(|d| (d.name.as_str(), d))
        .collect();
    let fail = |message| unsupported(message, &tree.span);
    if declarations.len() != tree.declarations.len() {
        return Err(fail("duplicate declaration"));
    }
    if tree.imports.iter().any(|n| n != "ken.core") {
        return Err(fail("external library resolver is not implemented"));
    }
    if tree.declarations.iter().any(|d| {
        !matches!(d.kind.as_str(), "query" | "pattern" | "predicate" | "enum")
            || !d.generics.is_empty()
    }) {
        return Err(fail("model/generic compilation is not implemented"));
    }
    let enums: Vec<_> = tree
        .declarations
        .iter()
        .filter(|d| d.kind == "enum")
        .map(|d| (d.name.clone(), d.values.clone()))
        .collect();
    if enums.iter().any(|(n, v)| {
        vocabulary().types.contains_key(n) || v.iter().collect::<BTreeSet<_>>().len() != v.len()
    }) {
        return Err(fail("duplicate enum value or reserved domain name"));
    }
    let mut domains = vocabulary().types.clone();
    for (n, _) in &enums {
        domains.insert(n.clone(), format!("enum:{n}"));
    }
    let predicates: Vec<_> = tree
        .declarations
        .iter()
        .filter(|d| d.kind == "predicate")
        .filter_map(|d| {
            d.formula.as_ref().map(|f| Predicate {
                name: d.name.clone(),
                parameters: d.parameters.clone(),
                formula: f.clone(),
            })
        })
        .collect();
    for p in &predicates {
        if p.parameters
            .iter()
            .map(|p| &p.role)
            .collect::<BTreeSet<_>>()
            .len()
            != p.parameters.len()
        {
            return Err(unsupported(
                "duplicate predicate parameter",
                &p.formula.span,
            ));
        }
        if p.parameters
            .iter()
            .any(|p| !domains.contains_key(&p.r#type.name) || !p.r#type.arguments.is_empty())
        {
            return Err(unsupported(
                "predicate parameters require finite domains",
                &p.formula.span,
            ));
        }
    }
    crate::predicate_components(&predicates).map_err(wrapped)?;
    let queries: Vec<_> = tree
        .declarations
        .iter()
        .filter(|d| d.kind == "query" && query.is_none_or(|q| q == d.name))
        .collect();
    if queries.len() != 1 {
        return Err(fail("choose exactly one query"));
    }
    let selected = queries[0];
    let mut lowering = Lowering {
        tree,
        declarations,
        domains: &domains,
        roles: Roles::new(),
        scans: vec![],
        filters: vec![],
        actions: vec![],
        optional: vec![],
        steps: vec![],
        counter: 0,
        budget: crate::compile_budget::WorkBudget::new(&tree.span),
    };
    lowering.lower(&selected.clauses, &Roles::new(), None, &[], None)?;
    if lowering.steps.len() > 256 {
        return Err(crate::ParseError::resource(
            "execution pipeline depth limit exceeded",
            tree.span.clone(),
        ));
    }
    if lowering.scans.len() > 96 {
        return Err(fail("structural join depth limit exceeded"));
    }
    let mut computed = Roles::new();
    let saved = lowering.roles.clone();
    {
        let mut checker = ExpressionChecker {
            roles: &mut lowering.roles,
            computed: &mut computed,
            domains: &domains,
            enums: &enums,
            predicates: &predicates,
        };
        for p in &predicates {
            checker.roles.clear();
            checker.roles.extend(
                p.parameters
                    .iter()
                    .map(|p| (p.role.clone(), domains[&p.r#type.name].clone())),
            );
            if checker.check(&p.formula)? != "Bool" {
                return Err(unsupported(
                    "predicate formula must be Bool",
                    &p.formula.span,
                ));
            }
        }
        *checker.roles = saved;
        for (role, e) in &lowering.actions {
            let t = checker.check(e)?;
            if !role.is_empty() {
                checker.computed.insert(role.clone(), t);
            } else if t != "Bool" {
                return Err(unsupported("where requires Bool", &e.span));
            }
        }
        for scan in &lowering.scans {
            for (prop, value) in &scan.properties {
                if value.kind == "wildcard" {
                    continue;
                }
                let expected = &vocabulary().properties[&scan.selector][prop];
                if expected == "SourceType" {
                    crate::source_matcher::validate_matcher(value).map_err(wrapped)?;
                    continue;
                }
                let actual = checker.check(value)?;
                if actual != *expected && !(actual == "Regex" && expected == "String") {
                    return Err(unsupported(
                        format!("property {prop} expects {expected}, got {actual}"),
                        &value.span,
                    ));
                }
            }
        }
        for e in &lowering.filters {
            if checker.check(e)? != "Bool" {
                return Err(unsupported("where requires Bool", &e.span));
            }
        }
        for e in &lowering.optional {
            if checker.check(e)? != "Bool" {
                return Err(unsupported("optional evidence requires Bool", &e.span));
            }
        }
        for step in &lowering.steps {
            if let Step::Body(body) = step {
                for item in &body.clauses {
                    if item.kind == "where" {
                        let e = query_expr(item, 0)?;
                        if checker.check(e)? != "Bool" {
                            return Err(unsupported("BODY where requires Bool", &e.span));
                        }
                    }
                }
            }
        }
        let Some(project) = selected.clauses.iter().find(|c| c.kind == "select") else {
            return Err(fail("query requires exactly one select"));
        };
        let projection: Vec<_> = project
            .expressions
            .iter()
            .filter_map(|e| {
                if let Expression::Query(e) = e {
                    Some(e.clone())
                } else {
                    None
                }
            })
            .collect();
        let ordering: Vec<_> = selected
            .clauses
            .iter()
            .find(|c| c.kind == "order")
            .map(|c| {
                c.expressions
                    .iter()
                    .filter_map(|e| {
                        if let Expression::Query(e) = e {
                            Some(e.clone())
                        } else {
                            None
                        }
                    })
                    .collect()
            })
            .unwrap_or_default();
        for projected in projection.iter().chain(&ordering) {
            let Some(e) = projected.args.first() else {
                return Err(unsupported(
                    "projection requires an expression",
                    &projected.span,
                ));
            };
            checker.check(e)?;
        }
        for ordered in &ordering {
            let t = checker.check(&ordered.args[0])?;
            if !matches!(t.as_str(), "String" | "Int" | "Float" | "Bool" | "Entity")
                && !t.starts_with("enum:")
            {
                return Err(unsupported(
                    "order expression requires an ordered scalar or entity",
                    &ordered.span,
                ));
            }
        }
        let limit = selected
            .clauses
            .iter()
            .find(|c| c.kind == "limit")
            .map(|c| IntegerLiteral::from_digits(&c.name));
        let mut result = IndexedProgram {
            name: selected.name.clone(),
            scans: lowering.scans,
            filters: lowering.filters,
            projection,
            ordering,
            limit,
            fingerprint: String::new(),
            branches: vec![],
            actions: lowering.actions,
            predicates,
            optional: lowering.optional,
            enums,
            steps: lowering.steps,
            graph: vec![],
        };
        result.compute_fingerprint();
        Ok(result)
    }
}
pub(crate) fn query_expr(c: &Clause, i: usize) -> Result<&Expr> {
    match c.expressions.get(i) {
        Some(Expression::Query(e)) => Ok(e),
        _ => Err(unsupported("expected query expression", &c.span)),
    }
}
pub(crate) fn remap_expr(e: &Expr, map: &Roles) -> Expr {
    crate::rewrite::query(
        e,
        &|kind, v| {
            if kind == "role" {
                map.get(v).cloned().unwrap_or_else(|| v.into())
            } else {
                v.into()
            }
        },
        &|p| Parameter {
            role: map.get(&p.role).cloned().unwrap_or_else(|| p.role.clone()),
            ..p.clone()
        },
    )
}
pub(crate) fn free_roles(e: &Expr) -> BTreeSet<String> {
    crate::operands::free(crate::operands::Operand::Query(e))
}
fn mapped(map: &Roles, name: &str) -> String {
    map.get(name).cloned().unwrap_or_else(|| name.into())
}
fn nodes(kind: &str) -> bool {
    matches!(kind, "node" | "expression" | "statement")
}
pub(crate) fn clause_roles(clauses: &[Clause]) -> BTreeSet<String> {
    let mut result = BTreeSet::new();
    let mut pending: Vec<_> = clauses.iter().collect();
    while let Some(c) = pending.pop() {
        if !c.role.is_empty() {
            result.insert(c.role.clone());
        }
        if !c.alias.is_empty() {
            result.insert(c.alias.clone());
        }
        result.extend(c.parameters.iter().map(|p| p.role.clone()));
        pending.extend(c.blocks.iter().flatten());
        let mut exprs: Vec<_> = c
            .expressions
            .iter()
            .map(crate::operands::Operand::from)
            .collect();
        while let Some(e) = exprs.pop() {
            if e.kind() == "role" {
                result.insert(e.value().into());
            }
            exprs.extend(e.args());
        }
    }
    result
}
pub(crate) fn expr(
    kind: &str,
    span: &Span,
    value: impl Into<String>,
    args: Vec<Expr>,
) -> Result<Expr> {
    Expr::checked(kind.into(), span.clone(), value.into(), args, vec![])
}
struct Lowering<'a> {
    tree: &'a File,
    declarations: BTreeMap<&'a str, &'a Declaration>,
    domains: &'a Roles,
    roles: Roles,
    scans: Vec<Scan>,
    filters: Vec<Expr>,
    actions: Vec<(String, Expr)>,
    optional: Vec<Expr>,
    steps: Vec<Step>,
    counter: usize,
    budget: crate::compile_budget::WorkBudget,
}
impl Lowering<'_> {
    fn retaining(&self) -> bool {
        self.steps.len() <= 256
    }
    fn action(&mut self, role: String, e: Expr) {
        if !self.retaining() {
            return;
        }
        self.actions.push((role.clone(), e.clone()));
        self.steps.push(Step::Action(Action {
            role,
            expression: e,
        }));
    }
    fn scan(&mut self, scan: Scan) {
        if !self.retaining() {
            return;
        }
        self.scans.push(scan.clone());
        self.steps.push(Step::Scan(scan));
    }
    fn lower(
        &mut self,
        clauses: &[Clause],
        map: &Roles,
        owner: Option<&str>,
        stack: &[String],
        expected: Option<&Roles>,
    ) -> Result<()> {
        crate::with_stack(|| self.lower_inner(clauses, map, owner, stack, expected))
    }
    fn lower_inner(
        &mut self,
        clauses: &[Clause],
        map: &Roles,
        owner: Option<&str>,
        stack: &[String],
        expected: Option<&Roles>,
    ) -> Result<()> {
        if stack.len() > 512 {
            return Err(crate::ParseError::resource(
                "pattern expansion depth limit exceeded",
                self.tree.span.clone(),
            ));
        }
        for c in clauses {
            self.budget.header(c)?;
            let fail = |m| unsupported(m, &c.span);
            match c.kind.as_str() {
                "select" | "order" | "limit" => (),
                "selector" => {
                    let kind = c.name.as_str();
                    if !vocabulary().kinds.contains_key(kind) || !c.alias.is_empty() {
                        return Err(fail(format!(
                            "selector {kind} or selector evidence capture is not implemented"
                        )));
                    }
                    let role = mapped(map, &c.role);
                    if let Some(old) = self.roles.get(&role)
                        && (!overlap(old, kind) || distinct_parameter(old, kind))
                    {
                        return Err(fail(format!("incompatible selector types for ${role}")));
                    }
                    self.roles.insert(role.clone(), kind.into());
                    if let Some(owner) = owner
                        && nodes(kind)
                        && !nodes(&self.roles[owner])
                    {
                        return Err(fail(
                            "common AST selectors require a common AST parent".into(),
                        ));
                    }
                    if kind == "method" && owner.is_none() || kind == "function" {
                        return Err(fail(
                            "standalone method/function classification is not implemented".into(),
                        ));
                    }
                    if let Some(owner) = owner {
                        let parent = self.roles[owner].as_str();
                        if !(nodes(parent) && nodes(kind)
                            || matches!(parent, "type" | "class" | "interface" | "trait")
                                && matches!(kind, "field" | "method" | "constructor" | "callable")
                            || matches!(parent, "callable" | "method" | "function" | "constructor")
                                && matches!(
                                    kind,
                                    "param" | "receiver" | "var" | "operation" | "call"
                                )
                            || parent == "module_decl")
                        {
                            return Err(fail("unsupported ownership relation".into()));
                        }
                    }
                    let mut props = vec![];
                    let mut nested = vec![];
                    for child in c.blocks.first().map_or(&[][..], Vec::as_slice) {
                        if child.kind == "property" {
                            let Some(expected) = vocabulary().properties[kind].get(&child.name)
                            else {
                                return Err(unsupported(
                                    format!(
                                        "property {} is not supported for {kind}. {}",
                                        crate::parser::quote(&child.name),
                                        property_hint(&child.name)
                                    ),
                                    &child.span,
                                ));
                            };
                            self.budget
                                .expression(crate::operands::Operand::Query(query_expr(
                                    child, 0,
                                )?))?;
                            let mut value = query_expr(child, 0)?.clone();
                            if child.name.ends_with("type_status")
                                && value.kind == "name"
                                && matches!(value.value.as_str(), "known" | "unknown")
                            {
                                value = expr(
                                    "literal",
                                    &value.span,
                                    serde_json::to_string(&value.value).unwrap(),
                                    vec![],
                                )?;
                            }
                            if expected != "SourceType"
                                && !matches!(value.kind.as_str(), "literal" | "regex" | "wildcard")
                            {
                                return Err(unsupported(
                                    "property requires a scalar literal, regex or wildcard in this capability",
                                    &child.span,
                                ));
                            }
                            props.push((child.name.clone(), value));
                        } else {
                            nested.push(child.clone());
                        }
                    }
                    self.scan(Scan {
                        role: role.clone(),
                        selector: kind.into(),
                        owner: owner.map(str::to_owned),
                        properties: props,
                    });
                    self.lower(&nested, map, Some(&role), stack, expected)?;
                }
                "from" => {
                    for p in &c.parameters {
                        if !p.r#type.arguments.is_empty()
                            || !self.domains.contains_key(&p.r#type.name)
                        {
                            return Err(fail("unsupported finite domain".into()));
                        }
                        let role = mapped(map, &p.role);
                        let kind = &self.domains[&p.r#type.name];
                        if let Some(old) = self.roles.get(&role)
                            && (old != kind && !overlap(old, kind) || distinct_parameter(old, kind))
                        {
                            return Err(fail("incompatible role types".into()));
                        }
                        self.roles.insert(role.clone(), kind.clone());
                        self.scan(Scan {
                            role,
                            selector: kind.clone(),
                            owner: None,
                            properties: vec![],
                        });
                    }
                }
                "where" => {
                    self.budget
                        .expression(crate::operands::Operand::Query(query_expr(c, 0)?))?;
                    let transformed = remap_expr(query_expr(c, 0)?, map);
                    if free_roles(&transformed)
                        .iter()
                        .any(|r| !self.roles.contains_key(r))
                    {
                        return Err(fail("where inputs must already be bound".into()));
                    }
                    if self.retaining() {
                        self.filters.push(transformed.clone());
                    }
                    self.action(String::new(), transformed);
                }
                "not" => {
                    let condition = expr(
                        "unary",
                        &c.span,
                        "not",
                        vec![self.existential(&c.blocks[0], map, owner, &c.span)?],
                    )?;
                    if self.retaining() {
                        self.filters.push(condition.clone());
                    }
                    self.action(String::new(), condition);
                }
                "optional" => {
                    let e = self.existential(&c.blocks[0], map, owner, &c.span)?;
                    if self.retaining() {
                        self.optional.push(e);
                    }
                }
                "body" => {
                    if owner.is_none_or(|r| {
                        !matches!(
                            self.roles[r].as_str(),
                            "callable"
                                | "method"
                                | "function"
                                | "constructor"
                                | "module_decl"
                                | "module"
                        )
                    }) {
                        return Err(fail("BODY requires a callable owner".into()));
                    }
                    self.budget.clause(c)?;
                    let body = crate::body_check::compile_body(
                        c,
                        owner.unwrap(),
                        map,
                        &mut self.roles,
                        expected,
                    )
                    .map_err(|e| {
                        if e.code == "resource_limit" {
                            e
                        } else {
                            wrapped(e)
                        }
                    })?;
                    if self.retaining() {
                        self.steps.push(Step::Body(body));
                    }
                }
                "bind" => {
                    let role = mapped(map, &c.role);
                    if self.roles.contains_key(&role) {
                        return Err(fail("bind requires a fresh role".into()));
                    }
                    self.roles.insert(role.clone(), "#computed".into());
                    self.budget
                        .expression(crate::operands::Operand::Query(query_expr(c, 0)?))?;
                    let transformed = remap_expr(query_expr(c, 0)?, map);
                    if free_roles(&transformed)
                        .iter()
                        .any(|r| r == &role || !self.roles.contains_key(r))
                    {
                        return Err(fail("bind inputs must already be bound".into()));
                    }
                    self.action(role, transformed);
                }
                "use" => {
                    let Some(target) = self
                        .declarations
                        .get(c.name.as_str())
                        .copied()
                        .filter(|d| d.kind == "pattern")
                    else {
                        return Err(fail(
                            "unknown pattern or unsupported model/evidence argument".into(),
                        ));
                    };
                    if !c.flags.is_empty() || !c.alias.is_empty() {
                        return Err(fail(
                            "unknown pattern or unsupported model/evidence argument".into(),
                        ));
                    }
                    if stack.contains(&c.name) {
                        return Err(fail("recursive pattern expansion is not supported".into()));
                    }
                    let mut arguments = Roles::new();
                    for arg in &c.expressions {
                        let Expression::Query(arg) = arg else {
                            return Err(fail("expected query expression".into()));
                        };
                        let Some(actual) = arg.args.first() else {
                            return Err(fail(
                                "pattern arguments must be unique named roles".into(),
                            ));
                        };
                        if actual.kind != "role" || arguments.contains_key(&arg.value) {
                            return Err(fail(
                                "pattern arguments must be unique named roles".into(),
                            ));
                        }
                        arguments.insert(arg.value.clone(), mapped(map, &actual.value));
                    }
                    let names: BTreeSet<_> =
                        target.parameters.iter().map(|p| p.role.clone()).collect();
                    if names.len() != target.parameters.len() {
                        return Err(fail("duplicate pattern parameter".into()));
                    }
                    if arguments.keys().any(|n| !names.contains(n)) {
                        return Err(fail("unknown pattern argument".into()));
                    }
                    self.counter += 1;
                    let prefix = format!("@{}:", self.counter);
                    let local_names: BTreeSet<_> = clause_roles(&target.clauses)
                        .union(&names)
                        .cloned()
                        .collect();
                    let mut local: Roles = local_names
                        .into_iter()
                        .map(|n| (n.clone(), format!("{prefix}{n}")))
                        .collect();
                    for p in &target.parameters {
                        if !self.domains.contains_key(&p.r#type.name)
                            || !p.r#type.arguments.is_empty()
                        {
                            return Err(fail("unsupported pattern role type".into()));
                        }
                        if p.direction == "in"
                            && arguments
                                .get(&p.role)
                                .is_none_or(|r| !self.roles.contains_key(r))
                        {
                            return Err(fail("pattern input must already be bound".into()));
                        }
                        if let Some(arg) = arguments.get(&p.role) {
                            local.insert(p.role.clone(), arg.clone());
                        }
                    }
                    let mut next = stack.to_vec();
                    next.push(c.name.clone());
                    let expected: Roles = target
                        .parameters
                        .iter()
                        .map(|p| (p.role.clone(), self.domains[&p.r#type.name].clone()))
                        .collect();
                    self.lower(&target.clauses, &local, owner, &next, Some(&expected))?;
                    for p in &target.parameters {
                        let Some(kind) = self.roles.get(&local[&p.role]) else {
                            return Err(fail("pattern output has no finite binding".into()));
                        };
                        let expected = &self.domains[&p.r#type.name];
                        let compatible = if expected.starts_with("enum:") {
                            kind == expected
                        } else {
                            kind_is(kind, expected) && !distinct_parameter(kind, expected)
                        };
                        if !compatible {
                            return Err(fail(
                                "pattern parameter type does not match binding".into(),
                            ));
                        }
                    }
                }
                "fields" | "parameters" if c.flags.is_empty() => {
                    self.lower(&c.blocks[0], map, owner, stack, expected)?
                }
                "fields" | "parameters" if c.flags == ["exact"] => {
                    let Some(owner) = owner else {
                        return Err(fail("exact inventory requires an owner".into()));
                    };
                    let field = c.kind == "fields";
                    let valid = if field {
                        matches!(
                            self.roles[owner].as_str(),
                            "type" | "class" | "interface" | "trait"
                        )
                    } else {
                        matches!(
                            self.roles[owner].as_str(),
                            "callable" | "method" | "function" | "constructor"
                        )
                    };
                    if !valid {
                        return Err(fail("exact inventory has incompatible owner type".into()));
                    }
                    let selector = if field { "field" } else { "param" };
                    let children = &c.blocks[0];
                    if children
                        .iter()
                        .any(|c| c.kind != "selector" || c.name != selector)
                    {
                        return Err(fail(
                            "exact inventory requires direct field or parameter selectors".into(),
                        ));
                    }
                    self.lower(children, map, Some(owner), stack, expected)?;
                    self.counter += 1;
                    let role = format!("@inventory:{}", self.counter);
                    let item = expr("role", &c.span, &role, vec![])?;
                    let parent = expr("role", &c.span, owner, vec![])?;
                    let arguments = vec![parent, item.clone()]
                        .into_iter()
                        .map(|value| expr("argument", &c.span, "", vec![value]))
                        .collect::<Result<_>>()?;
                    let domain = expr("call", &c.span, "owns", arguments)?;
                    let mut allowed = expr("literal", &c.span, "false", vec![])?;
                    for child in children {
                        let equal = expr(
                            "binary",
                            &child.span,
                            "==",
                            vec![
                                item.clone(),
                                expr("role", &child.span, mapped(map, &child.role), vec![])?,
                            ],
                        )?;
                        allowed = expr("binary", &child.span, "or", vec![allowed, equal])?;
                    }
                    let condition = Expr::checked(
                        "quantifier".into(),
                        c.span.clone(),
                        "forall".into(),
                        vec![domain, allowed],
                        vec![Parameter {
                            r#type: TypeName {
                                name: if field { "Field" } else { "Parameter" }.into(),
                                arguments: vec![],
                            },
                            role,
                            direction: "relation".into(),
                        }],
                    )?;
                    if self.retaining() {
                        self.filters.push(condition.clone());
                    }
                    self.action(String::new(), condition);
                }
                _ => return Err(fail(format!("{} evaluation is not implemented", c.kind))),
            }
        }
        Ok(())
    }
    fn existential(
        &mut self,
        clauses: &[Clause],
        map: &Roles,
        owner: Option<&str>,
        span: &Span,
    ) -> Result<Expr> {
        for c in clauses {
            self.budget.clause(c)?;
        }
        crate::existential::compile(clauses, map, owner, span, &self.roles, &mut self.counter)
    }
}

/// Compile prepared indexed syntax and compose its bounded alternatives.
/// Library/model preparation and backend selection are owned by the caller.
pub fn compile_indexed_branches(tree: &File, query: Option<&str>) -> Result<IndexedProgram> {
    use sha2::{Digest, Sha256};
    let expanded = crate::expand_indexed_alternatives(tree, query)?;
    let mut plans = expanded
        .iter()
        .map(|tree| compile_indexed(tree, query))
        .collect::<Result<Vec<_>>>()?;
    if plans.len() == 1 {
        return Ok(plans.pop().unwrap());
    }
    let Some(first) = plans.first() else {
        return Err(unsupported("query has no alternatives", &tree.span));
    };
    let mut program = first.clone();
    let mut identity = Sha256::new();
    for plan in &plans {
        identity.update(plan.fingerprint.as_bytes());
    }
    program.fingerprint = format!("{:x}", identity.finalize());
    program.branches = plans
        .into_iter()
        .map(|mut plan| {
            plan.limit = None;
            plan
        })
        .collect();
    Ok(program)
}
