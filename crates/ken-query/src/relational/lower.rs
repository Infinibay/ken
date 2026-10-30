//! Reachable declaration compilation and correlated relational block scopes.
use super::{CompiledQuery, ir::*, scopes, selectors, source_checks, terms::*, vocabulary};
use crate::{
    Program, PythonRepr, Result,
    ast::*,
    compile_budget::WorkBudget,
    expression_check::{Roles, unsupported},
    operands::Operand,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
pub fn has_graph(tree: &File, query: Option<&str>) -> bool {
    let definitions: BTreeMap<_, _> = tree
        .declarations
        .iter()
        .map(|d| (d.name.as_str(), d))
        .collect();
    let mut seen = BTreeSet::new();
    let mut pending: Vec<_> = tree
        .declarations
        .iter()
        .filter(|d| d.kind == "query" && query.is_none_or(|q| q == d.name))
        .flat_map(|d| d.clauses.iter())
        .collect();
    while let Some(c) = pending.pop() {
        if matches!(
            c.kind.as_str(),
            "source_usages"
                | "source_require"
                | "declaration_initializer"
                | "edge"
                | "walk"
                | "tally"
                | "count"
        ) || c.kind == "initializer" && c.role.is_empty()
            || c.kind == "gap" && c.flags.iter().any(|f| f == "exit")
            || c.kind == "selector" && matches!(c.name.as_str(), "macro" | "type_parameter")
        {
            return true;
        }
        if c.kind == "property"
            && (c.name == "type"
                && c.expressions.first().is_some_and(|e| {
                    e.kind() == "call" && matches!(e.value(), "nominal" | "parameter")
                })
                || matches!(
                    c.name.as_str(),
                    "reassigned"
                        | "escapes"
                        | "initial"
                        | "writes"
                        | "effective"
                        | "exported"
                        | "target"
                        | "result_family"
                        | "captures"
                        | "discarded"
                        | "derive"
                        | "unreplaced"
                        | "completes"
                ))
        {
            return true;
        }
        pending.extend(c.blocks.iter().flatten());
        if c.kind == "use"
            && seen.insert(&c.name)
            && let Some(d) = definitions.get(c.name.as_str())
        {
            if d.parameters
                .iter()
                .any(|p| p.direction == "out" && p.r#type.name == "Call")
            {
                return true;
            }
            pending.extend(&d.clauses);
        }
    }
    false
}
pub fn compile_relational(tree: &File, query: Option<&str>) -> Result<CompiledQuery> {
    use sha2::{Digest, Sha256};
    crate::validation::tree(tree)?;
    crate::syntax_shape::tree(tree)?;
    let queries: Vec<_> = tree
        .declarations
        .iter()
        .filter(|d| d.kind == "query" && query.is_none_or(|q| q == d.name))
        .collect();
    if queries.len() != 1 {
        return Err(unsupported("choose exactly one query", &tree.span));
    }
    let selected = queries[0];
    let mut budget = WorkBudget::new(&tree.span);
    charge_metadata(tree, &mut budget)?;
    struct DigestWriter(Sha256);
    impl std::fmt::Write for DigestWriter {
        fn write_str(&mut self, text: &str) -> std::fmt::Result {
            self.0.update(text.as_bytes());
            Ok(())
        }
    }
    let mut digest = DigestWriter(Sha256::new());
    tree.write_python_repr(&mut digest)
        .expect("hash formatting");
    let fingerprint = format!("{:x}", digest.0.finalize());
    let mut compiler = Compiler {
        definitions: tree
            .declarations
            .iter()
            .map(|d| (d.name.as_str(), d))
            .collect(),
        plans: vec![],
        positions: BTreeMap::new(),
        visiting: BTreeSet::new(),
        namespace: &fingerprint,
        selected: &selected.name,
        budget,
    };
    if compiler.definitions.len() != tree.declarations.len() {
        return Err(unsupported(
            "duplicate declaration",
            tree.declarations.first().map_or(&tree.span, |d| &d.span),
        ));
    }
    let root = compiler.declaration(&selected.name)?;
    let mut result = (*root).clone();
    let mut inlined = false;
    if result.nodes.len() == 1
        && result.nodes[0].kind == "match"
        && let PlanValue::Tuple(values) = &result.nodes[0].value
        && let (Some(target), Some(PlanValue::Map(bindings)), Some(proof)) = (
            values.first().and_then(PlanValue::string),
            values.get(1),
            values.get(2).and_then(PlanValue::string),
        )
    {
        let reverse: BTreeMap<_, _> = bindings
            .items
            .iter()
            .filter_map(|(k, v)| v.string().map(|s| (s, k)))
            .collect();
        if proof.is_empty()
            && reverse.len() == bindings.items.len()
            && result
                .exports
                .items
                .iter()
                .all(|(_, v)| reverse.contains_key(v.as_str()))
        {
            let child = &compiler.plans[compiler.positions[target]].1;
            let mut exports = OrderedMap::default();
            for (k, v) in &result.exports.items {
                let parameter = reverse[v.as_str()];
                let value = child.exports.get(parameter).ok_or_else(|| {
                    unsupported("invalid forwarding pattern export", &selected.span)
                })?;
                exports.insert(k.clone(), value.clone());
            }
            result.nodes = child.nodes.clone();
            result.exports = exports;
            inlined = true;
        }
    }
    result.definitions = compiler
        .plans
        .into_iter()
        .filter(|(_, p)| inlined || !Arc::ptr_eq(p, &root))
        .collect();
    let mut projection = vec![];
    for c in &selected.clauses {
        if c.kind == "select" {
            for e in &c.expressions {
                if let Expression::Query(e) = e {
                    let mut e = e.clone();
                    if e.value.is_empty() {
                        e.value = e
                            .args
                            .first()
                            .ok_or_else(|| {
                                unsupported(
                                    "graph select requires roles (optionally as column)",
                                    &e.span,
                                )
                            })?
                            .value
                            .clone();
                    }
                    projection.push(e);
                }
            }
        }
    }
    let program = Program {
        name: selected.name.clone(),
        scans: vec![],
        filters: vec![],
        projection,
        ordering: vec![],
        limit: None,
        fingerprint,
        branches: vec![],
        actions: vec![],
        predicates: vec![],
        optional: vec![],
        enums: vec![],
        steps: vec![],
        graph: tree.declarations.clone(),
    };
    Ok(CompiledQuery {
        program,
        relational: Some(Arc::new(result)),
    })
}
struct Compiler<'a> {
    definitions: BTreeMap<&'a str, &'a Declaration>,
    plans: Vec<(String, Arc<RelationalQuery>)>,
    positions: BTreeMap<String, usize>,
    visiting: BTreeSet<String>,
    namespace: &'a str,
    selected: &'a str,
    budget: WorkBudget,
}
impl Compiler<'_> {
    fn declaration(&mut self, name: &str) -> Result<Arc<RelationalQuery>> {
        crate::with_stack(|| {
            let selected = self.definitions.get(self.selected).unwrap();
            if self.visiting.contains(name) {
                return Err(unsupported(
                    format!("recursive graph pattern dependency: {name}"),
                    &self.definitions[name].span,
                ));
            }
            let identifier = format!("{}:{name}", self.namespace);
            if let Some(i) = self.positions.get(&identifier) {
                return Ok(self.plans[*i].1.clone());
            }
            let Some(source) = self
                .definitions
                .get(name)
                .copied()
                .filter(|d| matches!(d.kind.as_str(), "pattern" | "query"))
            else {
                return Err(unsupported(
                    format!("unknown graph pattern: {name}"),
                    &selected.span,
                ));
            };
            if self.visiting.len() >= 512 {
                return Err(crate::ParseError::resource(
                    "relational pattern depth limit exceeded",
                    source.span.clone(),
                ));
            }
            if !source.generics.is_empty() {
                return Err(unsupported(
                    "graph pattern generics require specialization",
                    &source.span,
                ));
            }
            let roles: BTreeSet<_> = source.parameters.iter().map(|p| &p.role).collect();
            if roles.len() != source.parameters.len()
                || source.parameters.iter().any(|p| {
                    !vocabulary().domains.contains_key(&p.r#type.name)
                        || !p.r#type.arguments.is_empty()
                        || !matches!(p.direction.as_str(), "in" | "out")
                })
            {
                return Err(unsupported(
                    "relational parameters require unique in/out source-domain roles",
                    &source.span,
                ));
            }
            self.visiting.insert(name.into());
            let types = source
                .parameters
                .iter()
                .map(|p| (p.role.clone(), vocabulary().domains[&p.r#type.name].clone()))
                .collect();
            let bound = source
                .parameters
                .iter()
                .filter(|p| p.direction == "in")
                .map(|p| p.role.clone())
                .collect();
            let mut context = Context {
                compiler: self,
                types,
                aliases: BTreeMap::new(),
            };
            let (mut nodes, bound) = context.block(&source.clauses, bound, None, true)?;
            let mut exports = OrderedMap::default();
            for p in &source.parameters {
                exports.insert(p.role.clone(), format!("${}", p.role));
            }
            let selects: Vec<_> = source
                .clauses
                .iter()
                .filter(|c| c.kind == "select")
                .collect();
            if source.kind == "query" {
                if selects.len() != 1 {
                    return Err(unsupported("graph query requires one select", &source.span));
                }
                exports = OrderedMap::default();
                for e in &selects[0].expressions {
                    let Expression::Query(e) = e else {
                        return Err(unsupported(
                            "graph select requires roles (optionally as column)",
                            e.span(),
                        ));
                    };
                    if e.kind != "projection" || e.args.first().is_none_or(|a| a.kind != "role") {
                        return Err(unsupported(
                            "graph select requires roles (optionally as column)",
                            &e.span,
                        ));
                    }
                    let role = &e.args[0].value;
                    let public = if e.value.is_empty() { role } else { &e.value };
                    if exports.get(public).is_some() {
                        return Err(unsupported("duplicate projection name", &e.span));
                    }
                    exports.insert(public.clone(), format!("${role}"));
                }
            } else if !selects.is_empty() {
                return Err(unsupported("pattern cannot contain select", &source.span));
            }
            if exports.items.iter().any(|(_, v)| !bound.contains(&v[1..])) {
                return Err(unsupported(
                    "graph output is not bound in every alternative",
                    &source.span,
                ));
            }
            if !context.aliases.is_empty() {
                for node in &mut nodes {
                    node.rewrite(&context.aliases);
                }
                for (_, v) in &mut exports.items {
                    *v = rewrite_text(v, &context.aliases);
                }
            }
            let plan = Arc::new(RelationalQuery {
                name: source.name.clone(),
                nodes: Arc::new(nodes),
                exports,
                definitions: OrderedMap::default(),
            });
            self.positions.insert(identifier.clone(), self.plans.len());
            self.plans.push((identifier, plan.clone()));
            self.visiting.remove(name);
            Ok(plan)
        })
    }
}
pub(super) struct Context<'a, 'b> {
    compiler: &'a mut Compiler<'b>,
    types: Roles,
    aliases: BTreeMap<String, String>,
}
impl Context<'_, '_> {
    pub(super) fn charge_expression(&mut self, e: &Expr) -> Result<()> {
        self.compiler.budget.expression(Operand::Query(e))
    }
    pub(super) fn charge_work(&mut self, units: usize) -> Result<()> {
        self.compiler.budget.charge(units)
    }
    fn block(
        &mut self,
        clauses: &[Clause],
        mut bound: BTreeSet<String>,
        owner: Option<(&str, &str)>,
        top: bool,
    ) -> Result<(Vec<Node>, BTreeSet<String>)> {
        crate::with_stack(|| {
            let mut nodes = vec![];
            let mut forthcoming = vec![];
            let mut witnesses = super::comparisons::WitnessNames::default();
            for c in clauses {
                charge_clause_fields(&mut self.compiler.budget, c)?;
                let fail = |m| unsupported(m, &c.span);
                match c.kind.as_str() {
                    "selector" => {
                        let previous = self.types.get(&c.role).map(String::as_str);
                        let kind = c.name.as_str();
                        let compatible = previous.is_none_or(|p| {
                            p.is_empty()
                                || p == kind
                                || matches!(
                                    (p, kind),
                                    ("operation", "macro")
                                        | ("macro", "operation")
                                        | ("type", "class" | "interface" | "trait")
                                        | ("class" | "interface" | "trait", "type")
                                        | ("callable", "method" | "constructor")
                                        | ("method" | "constructor", "callable")
                                )
                        });
                        if !compatible {
                            return Err(fail(format!(
                                "incompatible source selectors for ${}",
                                c.role
                            )));
                        }
                        self.types.insert(c.role.clone(), c.name.clone());
                        let lowered = selectors::selector(c, owner, &mut self.compiler.budget)?;
                        let (out, b) = self.block(&lowered, bound, None, false)?;
                        nodes.extend(out);
                        bound = b;
                    }
                    "source_owned" => {
                        let (out, b) =
                            self.block(first_block(c)?, bound, Some((&c.role, &c.name)), false)?;
                        nodes.extend(out);
                        bound = b;
                    }
                    "source_type" => {
                        let v = first_expression(c)?;
                        if c.name == "writes" {
                            let r =
                                v.args.first().and_then(|a| a.args.first()).ok_or_else(|| {
                                    fail(
                                        "writes requires exactly($binding, nonnegative_integer)"
                                            .into(),
                                    )
                                })?;
                            if !bound.contains(&r.value) {
                                forthcoming.push((r.value.clone(), c));
                            }
                        }
                        let mut spec = vec![
                            PlanValue::text(format!("${}", c.role)),
                            PlanValue::text(&c.name),
                            PlanValue::Expression(Expression::Query(v.clone())),
                        ];
                        if let Some(parent) = c.name.strip_prefix("escapes:") {
                            spec[1] = PlanValue::text("escapes");
                            spec.push(PlanValue::text(format!("${parent}")));
                        }
                        nodes.push(Node::new("source_type", PlanValue::tuple(spec)));
                    }
                    "source_effective_field" => {
                        let mut attrs = vec![];
                        let mut type_matcher = PlanValue::None;
                        let mut nominal = PlanValue::None;
                        let mut declaration = PlanValue::None;
                        for p in first_block(c)? {
                            let mut v = first_expression(p)?.clone();
                            match p.name.as_str() {
                                "declaration" => {
                                    if v.kind != "role"
                                        || self.types.get(&v.value).is_some_and(|t| t != "field")
                                    {
                                        return Err(unsupported(
                                            "field declaration requires a Field role",
                                            &p.span,
                                        ));
                                    }
                                    declaration = PlanValue::text(format!("${}", v.value));
                                    bound.insert(v.value.clone());
                                    self.types.insert(v.value, "field".into());
                                }
                                "type" => {
                                    if v.kind == "call"
                                        && v.value == "nominal"
                                        && v.args.len() == 1
                                        && v.args[0].args.len() == 1
                                        && v.args[0].args[0].kind == "role"
                                    {
                                        let role = &v.args[0].args[0].value;
                                        if self.types.get(role).is_some_and(|t| {
                                            !t.is_empty()
                                                && !matches!(
                                                    t.as_str(),
                                                    "type" | "class" | "interface" | "trait"
                                                )
                                        }) {
                                            return Err(unsupported(
                                                "nominal field type requires a TypeDecl role",
                                                &p.span,
                                            ));
                                        }
                                        nominal = PlanValue::text(format!("${role}"));
                                        bound.insert(role.clone());
                                        self.types.insert(role.clone(), "type".into());
                                    } else {
                                        crate::source_matcher::validate_matcher(&v)?;
                                        type_matcher = PlanValue::Expression(Expression::Query(v));
                                    }
                                }
                                _ => {
                                    if p.name == "visibility" && v.kind == "name" {
                                        v = selectors::expr(
                                            "literal",
                                            &v.span,
                                            json_string(&v.value),
                                            vec![],
                                        )?;
                                    }
                                    let (op, text) = matcher(Operand::Query(&v))?;
                                    attrs.push((p.name.clone(), op, text));
                                }
                            }
                        }
                        nodes.push(Node::new(
                            "source_effective_field",
                            PlanValue::tuple(vec![
                                PlanValue::text(format!("${}", c.name)),
                                PlanValue::text(format!("${}", c.role)),
                                attrs_value(attrs),
                                type_matcher,
                                nominal,
                                declaration,
                            ]),
                        ));
                        bound.insert(c.role.clone());
                    }
                    "source_capture" => {
                        self.types.insert(c.role.clone(), "value".into());
                        bound.insert(c.role.clone());
                    }
                    "source_receiver" => {
                        nodes.push(Node::new(
                            "source_receiver",
                            PlanValue::tuple(vec![
                                PlanValue::text(format!("${}", c.name)),
                                PlanValue::text(format!("${}", c.role)),
                            ]),
                        ));
                        bound.insert(c.role.clone());
                    }
                    "source_require" => {
                        let dispatch = c.name == "dispatch";
                        if !bound.contains(&c.role)
                            || !self.types.get(&c.role).is_some_and(|t| {
                                if dispatch {
                                    matches!(
                                        t.as_str(),
                                        "callable" | "method" | "function" | "constructor"
                                    )
                                } else {
                                    matches!(t.as_str(), "type" | "class" | "interface" | "trait")
                                }
                            })
                        {
                            return Err(fail(
                                if dispatch {
                                    "quantified dispatch owner requires a selected callable"
                                } else {
                                    "quantified constructor owner requires a selected TypeDecl"
                                }
                                .into(),
                            ));
                        }
                        if c.flags
                            .get(1)
                            .is_some_and(|w| !w.is_empty() && !bound.contains(w))
                        {
                            return Err(fail(
                                "named dispatch witness requires an already selected callable"
                                    .into(),
                            ));
                        }
                        nodes.push(Node::new(
                            "source_quantifier",
                            source_checks::requirement(c)?,
                        ));
                    }
                    "source_usages" => {
                        if !bound.contains(&c.name)
                            || self.types.get(&c.name).is_none_or(|t| t != "value")
                        {
                            return Err(fail("usages requires an already captured Value".into()));
                        }
                        if c.role == c.name
                            || self
                                .types
                                .get(&c.role)
                                .is_some_and(|t| !matches!(t.as_str(), "usage" | ""))
                        {
                            return Err(fail("usage capture requires a Usage role".into()));
                        }
                        nodes.push(Node::new("source_usages", source_checks::usage(c, &bound)?));
                        bound.insert(c.role.clone());
                        self.types.insert(c.role.clone(), "usage".into());
                    }
                    "declaration_initializer" => {
                        let Some((parent, kind)) =
                            owner.filter(|(_, k)| matches!(*k, "field" | "var"))
                        else {
                            return Err(fail(
                                "declaration initializer requires a field or variable owner".into(),
                            ));
                        };
                        let _ = kind;
                        let e = first_block(c)?
                            .first()
                            .ok_or_else(|| fail("missing initializer expression".into()))?;
                        if !bound.contains(&e.role) {
                            return Err(unsupported(
                                "initializer target must be selected before its expression",
                                &e.span,
                            ));
                        }
                        let valid = self.types.get(&e.role).is_some_and(|t| {
                            if e.kind == "construct" {
                                matches!(t.as_str(), "type" | "class" | "interface" | "trait")
                            } else {
                                t == "call"
                            }
                        });
                        if !valid {
                            return Err(unsupported(
                                "initializer target has an incompatible source domain",
                                &e.span,
                            ));
                        }
                        if e.blocks.iter().any(|b| !b.is_empty()) {
                            return Err(unsupported(
                                "initializer expression constraints are not yet supported",
                                &e.span,
                            ));
                        }
                        if !e.alias.is_empty() {
                            if self
                                .types
                                .get(&e.alias)
                                .is_some_and(|t| !t.is_empty() && t != "call")
                            {
                                return Err(unsupported(
                                    "initializer evidence has Call domain",
                                    &e.span,
                                ));
                            }
                            self.types.insert(e.alias.clone(), "call".into());
                            bound.insert(e.alias.clone());
                        }
                        nodes.push(Node::new(
                            "source_initializer",
                            PlanValue::tuple(vec![
                                PlanValue::text(format!("${parent}")),
                                PlanValue::text(&e.kind),
                                PlanValue::text(format!("${}", e.role)),
                                PlanValue::text(if e.alias.is_empty() {
                                    String::new()
                                } else {
                                    format!("${}", e.alias)
                                }),
                            ]),
                        ));
                    }
                    "body" => {
                        let Some((parent, _)) = owner.filter(|(_, k)| {
                            matches!(*k, "callable" | "method" | "constructor" | "module_decl")
                        }) else {
                            return Err(fail("BODY requires a callable owner".into()));
                        };
                        self.compiler.budget.clause(c)?;
                        charge_scope(&mut self.compiler.budget, &bound, &self.types)?;
                        for (a, b) in &self.aliases {
                            self.compiler.budget.charge(1 + (a.len() + b.len()) / 64)?;
                        }
                        let mut roles = self
                            .types
                            .iter()
                            .filter(|(r, _)| bound.contains(*r))
                            .map(|(a, b)| (a.clone(), b.clone()))
                            .collect();
                        let aliases = self
                            .aliases
                            .iter()
                            .map(|(a, b)| (a[1..].into(), b[1..].into()))
                            .collect();
                        let parent = self
                            .aliases
                            .get(&format!("${parent}"))
                            .map(|s| &s[1..])
                            .unwrap_or(parent);
                        let body =
                            crate::compile_body(c, parent, &aliases, &mut roles, Some(&self.types))
                                .map_err(|e| {
                                    if e.code == "resource_limit" {
                                        e
                                    } else {
                                        unsupported(e.to_string(), &c.span)
                                    }
                                })?;
                        self.types.extend(roles);
                        bound.extend(body.outputs.iter().cloned());
                        nodes.push(Node::new("source_body", PlanValue::Body(body)));
                    }
                    "edge" | "walk" => {
                        if !vocabulary().relations.contains(&c.name) {
                            return Err(fail(format!("unknown graph relation {}", c.name)));
                        }
                        let endpoints = c
                            .expressions
                            .iter()
                            .map(|e| term(e.into()))
                            .collect::<Result<Vec<_>>>()?;
                        if endpoints.len() != 2 {
                            return Err(fail("graph relation requires two endpoints".into()));
                        }
                        let mut properties = vec![];
                        let mut names = BTreeSet::new();
                        for p in first_block(c)? {
                            if p.kind != "property" || !names.insert(p.name.as_str()) {
                                return Err(unsupported(
                                    "expected unique graph context property",
                                    &p.span,
                                ));
                            }
                            properties.push((p.name.as_str(), first_expression(p)?));
                        }
                        if c.kind == "edge" {
                            if !c.alias.is_empty() {
                                return Err(fail("edge evidence aliases are not supported".into()));
                            }
                            let attrs = properties
                                .into_iter()
                                .map(|(k, v)| {
                                    matcher(Operand::Query(v))
                                        .map(|(op, text)| (k.into(), op, text))
                                })
                                .collect::<Result<_>>()?;
                            nodes.push(fact(
                                endpoints[0].clone(),
                                &c.name,
                                endpoints[1].clone(),
                                attrs,
                            ));
                        } else {
                            if names != BTreeSet::from(["min", "max"]) || c.alias.is_empty() {
                                return Err(fail(
                                    "walk requires min/max and a witness alias".into(),
                                ));
                            }
                            let mut values = vec![];
                            for name in ["min", "max"] {
                                let v = properties.iter().find(|(k, _)| *k == name).unwrap().1;
                                if v.kind != "literal"
                                    || v.value.is_empty()
                                    || !v.value.bytes().all(|b| b.is_ascii_digit())
                                {
                                    return Err(fail(
                                        "walk bounds require integer literals".into(),
                                    ));
                                }
                                values.push(v.value.parse::<usize>().ok());
                            }
                            let (lo, hi) = match (values[0], values[1]) {
                                (Some(a), Some(b)) if a <= b && b <= 32 => (a, b),
                                _ => {
                                    return Err(fail(
                                        "walk bounds must satisfy 0 <= min <= max <= 32".into(),
                                    ));
                                }
                            };
                            if bound.contains(&c.alias) {
                                return Err(fail("walk witness requires a fresh role".into()));
                            }
                            nodes.push(Node::new(
                                "path",
                                PlanValue::tuple(vec![
                                    PlanValue::Term(endpoints[0].clone()),
                                    PlanValue::text(&c.name),
                                    PlanValue::Term(endpoints[1].clone()),
                                    PlanValue::number(lo),
                                    PlanValue::number(hi),
                                    PlanValue::text(format!("${}", c.alias)),
                                ]),
                            ));
                            bound.insert(c.alias.clone());
                        }
                        bound.extend(
                            c.expressions
                                .iter()
                                .filter(|e| e.kind() == "role")
                                .map(|e| e.value().to_owned()),
                        );
                    }
                    "use" => {
                        let child = self.compiler.declaration(&c.name)?;
                        let params = &self.compiler.definitions[c.name.as_str()].parameters;
                        if self.compiler.definitions[c.name.as_str()].kind != "pattern"
                            || !c.flags.is_empty()
                        {
                            return Err(fail("use requires a graph pattern".into()));
                        }
                        let mut bindings = OrderedMap::default();
                        for argument in &c.expressions {
                            let Expression::Query(a) = argument else {
                                return Err(fail(
                                    "use requires unique named role arguments".into(),
                                ));
                            };
                            if a.kind != "argument"
                                || a.value.is_empty()
                                || a.args.len() != 1
                                || a.args[0].kind != "role"
                                || bindings.get(&a.value).is_some()
                            {
                                return Err(fail(
                                    "use requires unique named role arguments".into(),
                                ));
                            }
                            bindings.insert(a.value.clone(), format!("${}", a.args[0].value));
                        }
                        if bindings
                            .items
                            .iter()
                            .any(|(k, _)| child.exports.get(k).is_none())
                        {
                            return Err(fail("unknown pattern parameter".into()));
                        }
                        if params.iter().any(|p| {
                            p.direction == "in"
                                && bindings
                                    .get(&p.role)
                                    .is_none_or(|r| !bound.contains(&r[1..]))
                        }) {
                            return Err(fail("pattern input must already be bound".into()));
                        }
                        for p in params {
                            if let Some(r) = bindings.get(&p.role) {
                                let r = &r[1..];
                                if self.types.get(r).is_none_or(|t| t.is_empty()) {
                                    self.types.insert(
                                        r.into(),
                                        vocabulary().domains[&p.r#type.name].clone(),
                                    );
                                }
                            }
                        }
                        let spec = PlanValue::tuple(vec![
                            PlanValue::text(format!("{}:{}", self.compiler.namespace, c.name)),
                            PlanValue::Map(
                                bindings
                                    .items
                                    .iter()
                                    .map(|(k, v)| (k.clone(), PlanValue::text(v)))
                                    .collect(),
                            ),
                            PlanValue::text(if c.alias.is_empty() {
                                String::new()
                            } else {
                                format!("${}", c.alias)
                            }),
                        ]);
                        nodes.push(Node::new("match", spec));
                        bound.extend(bindings.items.into_iter().map(|(_, v)| v[1..].into()));
                        if !c.alias.is_empty() && !bound.insert(c.alias.clone()) {
                            return Err(fail(
                                "pattern evidence alias requires a fresh role".into(),
                            ));
                        }
                    }
                    "either" => {
                        charge_scope(&mut self.compiler.budget, &bound, &self.types)?;
                        let outer = self.types.clone();
                        let mut branches = vec![];
                        let mut types = vec![];
                        for alternative in &c.blocks {
                            charge_scope(&mut self.compiler.budget, &bound, &outer)?;
                            self.types = outer.clone();
                            let (out, b) = self.block(alternative, bound.clone(), owner, false)?;
                            branches.push(out);
                            charge_scope(&mut self.compiler.budget, &b, &self.types)?;
                            types.push((b, self.types.clone()));
                        }
                        self.types = outer;
                        if branches.len() < 2 {
                            return Err(fail("either requires at least two alternatives".into()));
                        }
                        for (bindings, types) in &types {
                            charge_scope(&mut self.compiler.budget, bindings, types)?;
                        }
                        scopes::common_types(&mut self.types, &types, &mut bound);
                        nodes.push(Node::branches("any", PlanValue::None, branches));
                    }
                    "not" | "optional" => {
                        if c.kind == "not" && owner.is_none() {
                            return Err(fail("Place not exists inside a source selector (for example, callable $owner { not exists { call $site {} } }) to define its absence scope".into()));
                        }
                        charge_scope(&mut self.compiler.budget, &bound, &self.types)?;
                        let outer = self.types.clone();
                        self.compiler.budget.clause(c)?;
                        let private =
                            scopes::private_witnesses(first_block(c)?, &bound, c.span.start);
                        let (out, _) = self.block(&private, bound.clone(), owner, false)?;
                        self.types = outer;
                        let scope = owner.map_or(PlanValue::None, |(r, k)| {
                            PlanValue::tuple(vec![
                                PlanValue::text(k),
                                PlanValue::text(format!("${r}")),
                            ])
                        });
                        nodes.push(Node::branches(&c.kind, scope, vec![out]));
                    }
                    "tally" | "count" => {
                        charge_scope(&mut self.compiler.budget, &bound, &self.types)?;
                        let outer = self.types.clone();
                        let (out, local) =
                            self.block(first_block(c)?, bound.clone(), owner, false)?;
                        self.types = outer;
                        if !local.contains(&c.role) {
                            return Err(fail("tally requires a positively bound witness".into()));
                        }
                        let count = c
                            .flags
                            .first()
                            .filter(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()))
                            .ok_or_else(|| fail("invalid tally count".into()))?;
                        nodes.push(Node::branches(
                            "count",
                            PlanValue::tuple(vec![
                                PlanValue::text(format!("${}", c.role)),
                                PlanValue::text(if c.name == "==" { "=" } else { &c.name }),
                                PlanValue::Integer(crate::IntegerLiteral::from_digits(count)),
                            ]),
                            vec![out],
                        ));
                    }
                    "bind" => {
                        let value = first_expression(c)?;
                        if !top
                            || value.kind != "role"
                            || !bound.contains(&value.value)
                            || bound.contains(&c.role)
                        {
                            return Err(fail(
                                "graph bind requires a fresh top-level alias of a bound role"
                                    .into(),
                            ));
                        }
                        let source = format!("${}", value.value);
                        self.aliases.insert(
                            format!("${}", c.role),
                            self.aliases.get(&source).cloned().unwrap_or(source),
                        );
                        if let Some(t) = self.types.get(&value.value) {
                            self.types.insert(c.role.clone(), t.clone());
                        }
                        bound.insert(c.role.clone());
                    }
                    "where" => {
                        let e = match c.expressions.first() {
                            Some(Expression::Query(e)) => e,
                            Some(e) => {
                                return Err(unsupported(
                                    "graph where requires a query expression",
                                    e.span(),
                                ));
                            }
                            None => return Err(fail("missing where expression".into())),
                        };
                        self.comparison(e, &mut bound, &mut nodes, &mut witnesses)?;
                    }
                    "select" => (),
                    "order" | "limit" => {
                        return Err(fail(format!(
                            "{} is unavailable with resolved/graph relationships; use max_rows to bound returned rows (without ordering)",
                            c.kind
                        )));
                    }
                    _ => {
                        return Err(fail(format!(
                            "{} cannot yet be combined with resolved/graph relationships; isolate that clause in a source-only query and validate both queries against the same fixture",
                            c.kind
                        )));
                    }
                }
            }
            for (role, c) in forthcoming {
                if !bound.contains(&role) {
                    return Err(unsupported(
                        "writes matcher requires an already bound source binding",
                        &c.span,
                    ));
                }
            }
            Ok((nodes, bound))
        })
    }
}
fn first_block(c: &Clause) -> Result<&[Clause]> {
    c.blocks
        .first()
        .map(Vec::as_slice)
        .ok_or_else(|| unsupported("malformed clause block", &c.span))
}
fn first_expression(c: &Clause) -> Result<&Expr> {
    crate::indexed::query_expr(c, 0)
}

// The public program retains all declarations, including unreachable metadata.
// Charge that payload before any clone, rather than only counting used clauses.
fn charge_metadata(tree: &File, budget: &mut WorkBudget) -> Result<()> {
    let mut pending: Vec<_> = tree.declarations.iter().collect();
    while let Some(d) = pending.pop() {
        budget.charge(1 + (d.name.len() + d.kind.len()) / 64)?;
        charge_parameters(budget, &d.parameters)?;
        for value in &d.values {
            budget.charge(1 + value.len() / 64)?;
        }
        for (a, b) in &d.generics {
            budget.charge(1 + (a.len() + b.len()) / 64)?;
        }
        budget.charge(d.implements.len() / 64)?;
        if let Some(e) = &d.formula {
            budget.expression(Operand::Query(e))?;
        }
        let mut clauses: Vec<_> = d.clauses.iter().collect();
        while let Some(c) = clauses.pop() {
            charge_clause_fields(budget, c)?;
            clauses.extend(c.blocks.iter().flatten());
        }
        pending.extend(&d.members);
    }
    Ok(())
}
fn charge_parameters(budget: &mut WorkBudget, parameters: &[Parameter]) -> Result<()> {
    for p in parameters {
        budget.charge(1 + (p.role.len() + p.direction.len()) / 64)?;
        let mut pending = vec![&p.r#type];
        while let Some(t) = pending.pop() {
            budget.charge(1 + t.name.len() / 64)?;
            pending.extend(&t.arguments);
        }
    }
    Ok(())
}
fn charge_scope(budget: &mut WorkBudget, bound: &BTreeSet<String>, types: &Roles) -> Result<()> {
    for role in bound {
        budget.charge(1 + role.len() / 64)?;
    }
    for (role, kind) in types {
        budget.charge(1 + (role.len() + kind.len()) / 64)?;
    }
    Ok(())
}

fn charge_clause_fields(budget: &mut WorkBudget, c: &Clause) -> Result<()> {
    budget.header(c)?;
    charge_parameters(budget, &c.parameters)?;
    for flag in &c.flags {
        budget.charge(1 + flag.len() / 64)?;
    }
    for e in &c.expressions {
        budget.expression(e.into())?;
        let mut pending = vec![Operand::from(e)];
        while let Some(e) = pending.pop() {
            charge_parameters(budget, e.parameters())?;
            pending.extend(e.args());
        }
    }
    Ok(())
}
