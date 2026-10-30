//! Source-pattern checking: each body owns anchors, captures and nested plans.
use crate::compile_budget::WorkBudget;
use crate::operands::Operand as O;
use crate::{
    ParseError, Result,
    ast::*,
    capabilities::vocabulary,
    checked::BodyPattern,
    expression_check::Roles,
    operands::{Operand, free},
};
use std::collections::{BTreeMap, BTreeSet};
fn error(message: impl Into<String>, span: &Span) -> ParseError {
    ParseError::new(message, span.clone())
}
fn in_kinds(kind: Option<&String>, kinds: &[&str]) -> bool {
    kind.is_some_and(|k| kinds.contains(&k.as_str()))
}
const PLACES: &[&str] = &["field", "var", "param", "receiver", "value"];
const STORAGE: &[&str] = &["field", "var", "param", "receiver"];
const VALUES: &[&str] = &[
    "var", "param", "receiver", "field", "value", "callable", "call",
];
const TARGETS: &[&str] = &[
    "callable",
    "method",
    "function",
    "constructor",
    "call",
    "field",
    "var",
    "param",
    "receiver",
    "value",
];
fn operand(c: &Clause, i: usize) -> Result<Operand<'_>> {
    c.expressions
        .get(i)
        .map(Operand::from)
        .ok_or_else(|| error("missing source operand", &c.span))
}
fn arg(e: Operand<'_>, i: usize) -> Result<Operand<'_>> {
    e.arg(i)
        .ok_or_else(|| error("missing expression operand", e.span()))
}
fn block(c: &Clause) -> &[Clause] {
    c.blocks.first().map_or(&[], Vec::as_slice)
}
fn mapped(map: &Roles, name: &str) -> String {
    map.get(name).cloned().unwrap_or_else(|| name.into())
}
fn remap(c: &Clause, map: &Roles) -> Clause {
    crate::with_stack(|| {
        let mut result = crate::rewrite::clause_shell(c);
        result.role = mapped(map, &c.role);
        result.alias = mapped(map, &c.alias);
        result.expressions = c
            .expressions
            .iter()
            .map(|e| {
                crate::rewrite::expression(
                    e,
                    &|kind, v| {
                        if kind == "role" {
                            mapped(map, v)
                        } else {
                            v.into()
                        }
                    },
                    &|p| Parameter {
                        role: mapped(map, &p.role),
                        ..p.clone()
                    },
                )
            })
            .collect();
        result.blocks = c
            .blocks
            .iter()
            .map(|b| b.iter().map(|c| remap(c, map)).collect())
            .collect();
        result
    })
}
/// Check a BODY against selected roles. Successful captures extend `roles`.
/// Like the original, an error may leave bindings introduced before that error.
pub fn compile_body(
    c: &Clause,
    owner: &str,
    mapping: &Roles,
    roles: &mut Roles,
    expected: Option<&Roles>,
) -> Result<BodyPattern> {
    crate::validation::clause(c)?;
    crate::syntax_shape::clause(c)?;
    let mut budget = WorkBudget::new(&c.span);
    compile_with_budget(c, owner, mapping, roles, expected, &mut budget)
}
fn compile_with_budget(
    c: &Clause,
    owner: &str,
    mapping: &Roles,
    roles: &mut Roles,
    expected: Option<&Roles>,
    budget: &mut WorkBudget,
) -> Result<BodyPattern> {
    budget.clause(c)?;
    budget.charge(roles.len() + expected.map_or(0, |m| m.len()) + mapping.len())?;
    crate::with_stack(|| {
        let expected: Roles = expected
            .into_iter()
            .flat_map(|m| m.iter())
            .map(|(k, v)| (mapped(mapping, k), v.clone()))
            .collect();
        let clauses: Vec<_> = block(c).iter().map(|c| remap(c, mapping)).collect();
        let mut checker = BodyChecker {
            roles,
            budget,
            expected: &expected,
            outputs: vec![],
            output_names: BTreeSet::new(),
            call_aliases: vec![],
        };
        checker.body(c, owner, clauses)
    })
}
struct BodyChecker<'a> {
    budget: &'a mut WorkBudget,
    roles: &'a mut Roles,
    expected: &'a Roles,
    outputs: Vec<String>,
    output_names: BTreeSet<String>,
    call_aliases: Vec<String>,
}
impl BodyChecker<'_> {
    fn output(&mut self, name: &str) {
        if self.output_names.insert(name.into()) {
            self.outputs.push(name.into());
        }
    }
    fn capture(&mut self, name: &str, kind: &str) {
        self.roles.insert(name.into(), kind.into());
        self.output(name);
    }
    fn alias(&mut self, item: &Clause, allow_call: bool) -> Result<()> {
        if item.alias.is_empty() {
            return Ok(());
        }
        if self.roles.contains_key(&item.alias) {
            return Err(error(
                "operation evidence capture must be fresh",
                &item.span,
            ));
        }
        self.capture(&item.alias, "operation");
        if self.expected.get(&item.alias).is_some_and(|t| t == "call") {
            if !allow_call {
                return Err(error(
                    "Call evidence requires a call or construction",
                    &item.span,
                ));
            }
            self.roles.insert(item.alias.clone(), "call".into());
            self.call_aliases.push(item.alias.clone());
        }
        Ok(())
    }
    fn nested(
        &mut self,
        body: &Clause,
        owner: &str,
        local: &mut Roles,
        linear: bool,
    ) -> Result<BodyPattern> {
        if block(body).is_empty() {
            return Ok(BodyPattern::empty(owner));
        }
        let mut body = body.clone();
        if linear {
            body.flags.push("linear".into());
        }
        compile_with_budget(
            &body,
            owner,
            &Roles::new(),
            local,
            Some(self.expected),
            self.budget,
        )
    }
    fn retain_outputs(&mut self, inner: &BodyPattern, local: &Roles) {
        for name in &inner.outputs {
            if self.expected.contains_key(name) && !self.output_names.contains(name) {
                self.roles.insert(name.clone(), local[name].clone());
                self.output(name);
            }
        }
    }
    fn body(&mut self, body: &Clause, owner: &str, clauses: Vec<Clause>) -> Result<BodyPattern> {
        let mut anchored = false;
        let mut pending_adjacent = false;
        let mut pending_gap = false;
        let mut nested = vec![];
        let mut controls = vec![];
        let mut current_flags = body.flags.clone();
        // Dataclass equality includes the span. Index candidate occurrences by
        // span so resume keeps Python's first-equal-clause rule without rescanning
        // every earlier instruction in an ordinary wide body.
        let mut occurrences = BTreeMap::<_, Vec<usize>>::new();
        for (i, c) in clauses.iter().enumerate() {
            occurrences
                .entry((c.span.source.clone(), c.span.start, c.span.end))
                .or_default()
                .push(i);
        }
        for (index, item) in clauses.iter().enumerate() {
            let fail = |m| error(m, &item.span);
            match item.kind.as_str() {
                "macro" => {
                    if !in_kinds(self.roles.get(&item.role), &["macro", "operation"]) {
                        return Err(fail("macro requires a selected macro occurrence"));
                    }
                    anchored = true;
                    pending_adjacent = false;
                    pending_gap = false;
                    continue;
                }
                "resume" => {
                    let first = *occurrences
                        [&(item.span.source.clone(), item.span.start, item.span.end)]
                        .iter()
                        .find(|&&i| clauses[i] == *item)
                        .unwrap();
                    if !anchored
                        || clauses[if first == 0 {
                            clauses.len() - 1
                        } else {
                            first - 1
                        }]
                        .kind
                            != "yield"
                    {
                        return Err(fail("resume requires an immediately preceding yield"));
                    }
                    continue;
                }
                "where" => {
                    if free(operand(item, 0)?)
                        .iter()
                        .any(|n| !self.roles.contains_key(n))
                    {
                        return Err(fail("BODY where inputs must already be bound"));
                    }
                    continue;
                }
                "initializer" => {
                    if anchored || index != 0 || !item.alias.is_empty() {
                        return Err(fail("initializer must be the first BODY step"));
                    }
                    for assignment in block(item) {
                        if assignment.kind != "assign"
                            || assignment.name != "="
                            || !assignment.alias.is_empty()
                            || assignment.expressions.iter().any(|e| e.kind() != "role")
                            || !in_kinds(
                                self.roles.get(operand(assignment, 0)?.value()),
                                &["field"],
                            )
                            || !in_kinds(
                                self.roles.get(operand(assignment, 1)?.value()),
                                &["param"],
                            )
                        {
                            return Err(error(
                                "initializer requires assignments from parameters to fields",
                                &assignment.span,
                            ));
                        }
                    }
                    if block(item).is_empty() {
                        return Err(fail("initializer requires an assignment"));
                    }
                    anchored = true;
                    continue;
                }
                "gap" => {
                    if item.flags.iter().any(|f| f == "exit") {
                        if !anchored || index + 1 != clauses.len() {
                            return Err(fail("terminal gap must follow an anchor and end BODY"));
                        }
                        for r in terminal_bindings(item)? {
                            if !in_kinds(self.roles.get(&r), STORAGE) {
                                return Err(fail("terminal gap requires a bound source binding"));
                            }
                        }
                        continue;
                    }
                    if !anchored || pending_gap {
                        return Err(fail("gap requires two distinct anchors"));
                    }
                    let restrictions = interval_restrictions(item)?;
                    for r in restrictions.protected {
                        if !in_kinds(self.roles.get(&r), STORAGE) {
                            return Err(fail("gap requires a bound storage"));
                        }
                    }
                    for r in restrictions.forbidden {
                        if !in_kinds(
                            self.roles.get(&r),
                            &["callable", "method", "function", "constructor"],
                        ) {
                            return Err(fail("gap call requires a bound Callable"));
                        }
                    }
                    pending_gap = true;
                    continue;
                }
                "adjacent" => {
                    if !anchored || pending_adjacent {
                        return Err(fail("adjacent requires two distinct anchors"));
                    }
                    pending_adjacent = true;
                    continue;
                }
                "if" => {
                    self.condition(operand(item, 0)?, true)?;
                    let mut arms = vec![];
                    for arm in &item.blocks {
                        let mut local = self.roles.clone();
                        let mut c = Clause::new("body", item.span.clone());
                        c.blocks = vec![arm.clone()];
                        let linear = current_flags.iter().any(|f| f == "linear");
                        let plan = self.nested(&c, owner, &mut local, linear)?;
                        self.retain_outputs(&plan, &local);
                        arms.push(plan);
                    }
                    if !item.alias.is_empty() {
                        if self.roles.contains_key(&item.alias) {
                            return Err(fail("branch capture must be fresh"));
                        }
                        self.capture(&item.alias, "operation");
                    }
                    controls.push((item.clone(), arms));
                    anchored = true;
                    pending_adjacent = false;
                    pending_gap = false;
                    continue;
                }
                "iterate" => {
                    let source = operand(item, 0)?;
                    if source.kind() == "index" {
                        let container = arg(source, 0)?;
                        let key = arg(source, 1)?;
                        if container.kind() != "role"
                            || !in_kinds(self.roles.get(container.value()), PLACES)
                        {
                            return Err(fail("iterate requires a bound collection place"));
                        }
                        if key.kind() == "role" && !in_kinds(self.roles.get(key.value()), PLACES)
                            || !matches!(key.kind(), "role" | "literal" | "member")
                        {
                            return Err(fail("iterate key requires a bound operand"));
                        }
                    } else if source.kind() != "role"
                        || !in_kinds(
                            self.roles.get(source.value()),
                            &["var", "field", "param", "receiver", "value", "call"],
                        )
                    {
                        if source.kind() == "role" && !self.roles.contains_key(source.value()) {
                            self.capture(source.value(), "value");
                        } else {
                            return Err(fail("iterate requires a bound collection"));
                        }
                    }
                    if !item.name.is_empty() || self.roles.contains_key(&item.role) {
                        return Err(fail(
                            "iterate requires a fresh element role; collection output is not implemented",
                        ));
                    }
                    let bodies: Vec<_> = block(item).iter().filter(|c| c.kind == "body").collect();
                    let props: Vec<_> = block(item)
                        .iter()
                        .filter(|c| c.kind == "property")
                        .collect();
                    if bodies.len() != 1 || bodies.len() + props.len() != block(item).len() {
                        return Err(fail(
                            "iterate requires exactly one BODY and supported properties",
                        ));
                    }
                    let select = |name: &str| {
                        props
                            .iter()
                            .copied()
                            .filter(|p| p.name == name)
                            .collect::<Vec<_>>()
                    };
                    let asyncs = select("async");
                    let body_props = select("body");
                    let origins = select("origin");
                    if asyncs.len() > 1
                        || body_props.len() > 1
                        || origins.len() > 1
                        || asyncs.len() + body_props.len() + origins.len() != props.len()
                    {
                        return Err(fail(
                            "iterate supports async: true or false, one body role and one origin role",
                        ));
                    }
                    if origins
                        .iter()
                        .any(|p| p.expressions.first().is_none_or(|e| e.kind() != "role"))
                    {
                        return Err(fail("iterate origin names a call occurrence"));
                    }
                    if asyncs.iter().any(|p| {
                        p.expressions.first().is_none_or(|e| {
                            e.kind() != "literal" || !matches!(e.value(), "true" | "false")
                        })
                    }) {
                        return Err(fail("iterate supports async: true or false"));
                    }
                    if let Some(prop) = body_props.first() {
                        let value = operand(prop, 0)?;
                        if value.kind() != "role" {
                            return Err(fail("iterate body names a role"));
                        }
                        if self.roles.contains_key(value.value()) {
                            return Err(fail("iteration body capture must be fresh"));
                        }
                        self.capture(value.value(), "operation");
                    }
                    if !item.alias.is_empty() {
                        if self.roles.contains_key(&item.alias) {
                            return Err(fail("iteration capture must be fresh"));
                        }
                        self.capture(&item.alias, "operation");
                    }
                    let mut local = self.roles.clone();
                    local.insert(item.role.clone(), "value".into());
                    let inner = self.nested(
                        bodies[0],
                        owner,
                        &mut local,
                        current_flags.iter().any(|f| f == "linear"),
                    )?;
                    self.retain_outputs(&inner, &local);
                    nested.push((item.clone(), inner));
                    if let Some(expected) = self.expected.get(&item.role) {
                        if !matches!(expected.as_str(), "var" | "") {
                            return Err(fail("iteration element output requires Binding"));
                        }
                        let kind = if expected.is_empty() { "var" } else { expected };
                        self.roles.insert(item.role.clone(), kind.into());
                        self.output_names.insert(item.role.clone());
                        self.outputs.push(item.role.clone());
                    }
                    anchored = true;
                    pending_adjacent = false;
                    pending_gap = false;
                    continue;
                }
                _ => (),
            }
            if !matches!(
                item.kind.as_str(),
                "assign"
                    | "return"
                    | "yield"
                    | "break"
                    | "selector"
                    | "call"
                    | "let"
                    | "insert"
                    | "clear"
            ) || item.kind == "selector" && item.name != "var"
            {
                return Err(fail(&format!(
                    "BODY instruction is not implemented: {}",
                    item.kind
                )));
            }
            if item.kind == "selector" {
                self.variable(item)?;
            }
            for (pos, e) in item.expressions.iter().enumerate() {
                self.source(
                    e.into(),
                    true,
                    item.kind == "assign" && pos + 1 == item.expressions.len(),
                )?;
            }
            for c in item.blocks.iter().flatten() {
                current_flags = c.flags.clone();
                if c.kind == "from"
                    && !in_kinds(
                        self.roles.get(&c.role),
                        &[
                            "var",
                            "param",
                            "receiver",
                            "field",
                            "value",
                            "callable",
                            "call",
                            "operation",
                        ],
                    )
                {
                    return Err(error("derivation requires a bound place", &c.span));
                }
            }
            match item.kind.as_str() {
                "insert" => {
                    if !in_kinds(self.roles.get(&item.role), PLACES) {
                        if self.roles.contains_key(&item.role) {
                            return Err(fail("insert requires a bound collection place"));
                        }
                        let kind = self
                            .expected
                            .get(&item.role)
                            .filter(|s| !s.is_empty())
                            .map_or("value", String::as_str);
                        self.roles.insert(item.role.clone(), kind.into());
                        self.output(&item.role);
                    }
                    anchored = true;
                    pending_adjacent = false;
                    pending_gap = false;
                    continue;
                }
                "clear" => {
                    if !in_kinds(self.roles.get(&item.role), PLACES) {
                        return Err(fail("clear requires a bound collection place"));
                    }
                    if !item.name.is_empty()
                        && !in_kinds(self.roles.get(&item.name), &["operation"])
                    {
                        return Err(fail("clear requires a bound iteration operation"));
                    }
                    if !item.alias.is_empty() {
                        if self.roles.contains_key(&item.alias) {
                            return Err(fail("clear evidence capture must be fresh"));
                        }
                        self.capture(&item.alias, "operation");
                    }
                    anchored = true;
                    pending_adjacent = false;
                    pending_gap = false;
                    continue;
                }
                "let" => {
                    let inner = if item.blocks.first().is_some_and(|b| b.len() == 1) {
                        item.blocks[0].first()
                    } else {
                        None
                    };
                    if inner.is_none()
                        && item.expressions.len() == 1
                        && operand(item, 0)?.kind() == "index"
                    {
                        self.let_value(item)?;
                        if !item.alias.is_empty() {
                            if self.roles.contains_key(&item.alias) {
                                return Err(fail("operation evidence capture must be fresh"));
                            }
                            self.capture(&item.alias, "operation");
                        }
                        anchored = true;
                        pending_adjacent = false;
                        pending_gap = false;
                        continue;
                    }
                    let Some(inner) =
                        inner.filter(|c| matches!(c.kind.as_str(), "call" | "construct"))
                    else {
                        return Err(fail("let requires a call or a construction"));
                    };
                    if inner.kind == "construct" {
                        self.construct(inner, &item.span)?;
                        self.let_value(item)?;
                        self.alias(item, true)?;
                        anchored = true;
                        pending_adjacent = false;
                        pending_gap = false;
                        continue;
                    }
                    self.target(inner, false, &item.span)?;
                    self.call_constraints(inner, true)?;
                    self.let_value(item)?;
                }
                "call" => {
                    self.target(item, item.flags.iter().any(|f| f == "qualify"), &item.span)?;
                    self.call_constraints(item, false)?;
                }
                "break" if !in_kinds(self.roles.get(&item.role), &["operation"]) => {
                    return Err(fail("break requires a bound iteration capture"));
                }
                "assign" => {
                    let place = operand(item, 0)?;
                    if !(place.kind() == "role" && in_kinds(self.roles.get(place.value()), STORAGE)
                        || matches!(place.kind(), "member" | "index"))
                    {
                        return Err(fail("assignment place requires a bound storage role"));
                    }
                }
                _ => (),
            }
            self.alias(item, matches!(item.kind.as_str(), "call" | "let"))?;
            anchored = true;
            pending_adjacent = false;
            pending_gap = false;
        }
        if pending_adjacent || pending_gap || !anchored {
            return Err(error(
                "BODY requires anchors and cannot end with adjacent",
                &body.span,
            ));
        }
        Ok(BodyPattern {
            owner: owner.into(),
            clauses,
            adjacent: body.flags.iter().any(|f| f == "adjacent"),
            outputs: std::mem::take(&mut self.outputs),
            nested,
            controls,
            linear: body.flags.iter().any(|f| f == "linear"),
            call_aliases: std::mem::take(&mut self.call_aliases),
        })
    }

    fn let_value(&mut self, item: &Clause) -> Result<()> {
        if self.roles.get(&item.role).is_some_and(|r| r != "value") {
            return Err(error("let capture requires a Value role", &item.span));
        }
        self.roles
            .entry(item.role.clone())
            .or_insert_with(|| "value".into());
        self.output(&item.role);
        Ok(())
    }
}

mod call_constraints;
mod intervals;
mod source_operands;
use intervals::{interval_restrictions, terminal_bindings};
