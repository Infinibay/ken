//! Query scalar/domain rules and fresh quantified scopes.
use crate::{
    ParseError, Predicate, Result, ast::*, capabilities::*, source_matcher::validate_matcher,
};
use std::collections::BTreeMap;
pub(crate) type Roles = BTreeMap<String, String>;
pub(crate) fn unsupported(message: impl Into<String>, span: &Span) -> ParseError {
    ParseError {
        message: message.into(),
        span: span.clone(),
        code: "unsupported_capability".into(),
    }
}
pub(crate) fn wrapped(error: ParseError) -> ParseError {
    ParseError::new(error.to_string(), error.span)
}
pub(crate) struct ExpressionChecker<'a> {
    pub roles: &'a mut Roles,
    pub computed: &'a mut Roles,
    pub domains: &'a Roles,
    pub enums: &'a [(String, Vec<String>)],
    pub predicates: &'a [Predicate],
}
impl ExpressionChecker<'_> {
    pub fn check(&mut self, e: &Expr) -> Result<String> {
        crate::with_stack(|| self.inner(e))
    }
    fn fail<T>(&self, message: impl Into<String>, e: &Expr) -> Result<T> {
        Err(unsupported(message, &e.span))
    }
    fn actual<'a>(&self, arg: &'a Expr) -> Result<&'a Expr> {
        arg.args
            .first()
            .ok_or_else(|| unsupported("argument requires a value", &arg.span))
    }
    fn entity(&mut self, e: &Expr) -> Result<bool> {
        Ok(self.check(e)? == "Entity"
            && e.kind == "role"
            && vocabulary()
                .kinds
                .contains_key(self.roles.get(&e.value).map_or("", String::as_str)))
    }
    fn inner(&mut self, e: &Expr) -> Result<String> {
        match e.kind.as_str() {
            "type_test" => {
                if self.check(&e.args[0])? != "SourceType" {
                    return self.fail("type matcher requires a source type", e);
                }
                validate_matcher(&e.args[1]).map_err(wrapped)?;
                return Ok("Bool".into());
            }
            "literal" => {
                if e.value == "undefined" {
                    return self.fail("undefined scalar calculation is not supported", e);
                }
                let raw = serde_json::value::RawValue::from_string(e.value.clone())
                    .map_err(|_| unsupported("invalid scalar literal", &e.span))?;
                let v = ken_program::value::GraphValue::parse(&raw)
                    .map_err(|_| unsupported("invalid scalar literal", &e.span))?;
                use ken_program::value::GraphValue::*;
                return Ok(match v {
                    String(_) => "String",
                    Bool(_) => "Bool",
                    Int(_) => "Int",
                    Float(n) => {
                        if !n.is_finite() {
                            return self.fail("nonfinite numeric literal", e);
                        }
                        "Float"
                    }
                    Null => "Null",
                    _ => return self.fail("invalid scalar literal", e),
                }
                .into());
            }
            "role" => {
                let Some(kind) = self.roles.get(&e.value) else {
                    return self.fail(format!("unbound role ${}", e.value), e);
                };
                if kind == "#computed" {
                    return self.computed.get(&e.value).cloned().ok_or_else(|| {
                        unsupported("calculated role used before its definition", &e.span)
                    });
                }
                return Ok(if kind.starts_with("enum:") {
                    kind.clone()
                } else {
                    "Entity".into()
                });
            }
            "name" => {
                if let Some((name, member)) = e.value.rsplit_once('.')
                    && self
                        .enums
                        .iter()
                        .any(|(n, v)| n == name && v.iter().any(|x| x == member))
                {
                    return Ok(format!("enum:{name}"));
                }
                return self.fail("unknown enum member", e);
            }
            "regex" => return Ok("Regex".into()),
            "member" if e.args.len() == 1 && e.args[0].kind == "role" => {
                self.check(&e.args[0])?;
                return vocabulary()
                    .properties
                    .get(&self.roles[&e.args[0].value])
                    .and_then(|p| p.get(&e.value))
                    .cloned()
                    .ok_or_else(|| unsupported("unsupported property accessor", &e.span));
            }
            "list" => {
                let mut types = std::collections::BTreeSet::new();
                for a in &e.args {
                    types.insert(self.check(a)?);
                }
                if types.is_empty() {
                    return Ok("List<Empty>".into());
                }
                if types.len() == 1 {
                    return Ok(format!("List<{}>", types.first().unwrap()));
                }
                return self.fail("membership list requires homogeneous types", e);
            }
            "unary" => {
                let t = self.check(&e.args[0])?;
                if e.value == "not" && t == "Bool" {
                    return Ok("Bool".into());
                }
                if matches!(e.value.as_str(), "+" | "-") && numeric(&t) {
                    return Ok(t);
                }
            }
            "aggregate" | "quantifier" => {
                let before = self.roles.clone();
                let result = self.quantified(e);
                *self.roles = before;
                return result;
            }
            "call" => {
                if let Some(result) = self.call(e)? {
                    return Ok(result);
                }
            }
            "binary" => {
                let a = self.check(&e.args[0])?;
                let b = self.check(&e.args[1])?;
                let op = e.value.as_str();
                if matches!(op, "+" | "-" | "*" | "/" | "%") && numeric(&a) && numeric(&b) {
                    return Ok(if a == "Float" || b == "Float" || op == "/" {
                        "Float"
                    } else {
                        "Int"
                    }
                    .into());
                }
                if op == "in" && (b == "List<Empty>" || b == format!("List<{a}>"))
                    || matches!(op, "and" | "or") && a == "Bool" && b == "Bool"
                    || op == "matches" && a == "String" && b == "Regex"
                    || matches!(op, "==" | "!=") && a == b
                    || matches!(op, "<" | ">" | "<=" | ">=")
                        && (a == "String" && b == "String" || numeric(&a) && numeric(&b))
                {
                    return Ok("Bool".into());
                }
            }
            _ => (),
        }
        self.fail(
            format!("unsupported or ill-typed query expression {}", e.kind),
            e,
        )
    }
    fn quantified(&mut self, e: &Expr) -> Result<String> {
        for p in &e.parameters {
            if self.roles.contains_key(&p.role)
                || !self.domains.contains_key(&p.r#type.name)
                || !p.r#type.arguments.is_empty()
            {
                return self.fail("quantified role must be fresh with a finite domain", e);
            }
            self.roles
                .insert(p.role.clone(), self.domains[&p.r#type.name].clone());
        }
        if self.check(&e.args[0])? != "Bool" {
            return self.fail("quantifier condition must be Bool", e);
        }
        if e.value == "exists" {
            return Ok("Bool".into());
        }
        let t = self.check(&e.args[1])?;
        if e.value == "forall" {
            if t != "Bool" {
                return self.fail("forall property must be Bool", e);
            }
            return Ok("Bool".into());
        }
        if e.value == "count" {
            return Ok("Int".into());
        }
        if !numeric(&t) {
            return self.fail("numeric aggregate requires numeric projection", e);
        }
        Ok(if matches!(e.value.as_str(), "sum" | "sum_by") {
            t
        } else {
            format!("Option<{}>", if e.value == "avg" { "Float" } else { &t })
        })
    }
    fn call(&mut self, e: &Expr) -> Result<Option<String>> {
        let c = vocabulary();
        let name = e.value.as_str();
        let boolean = || Ok(Some("Bool".into()));
        if name == "stable_id"
            && e.args.len() == 1
            && self.check(self.actual(&e.args[0])?)? == "Entity"
        {
            return Ok(Some("String".into()));
        }
        if let Some(p) = self.predicates.iter().find(|p| p.name == name) {
            let parameters = p.parameters.clone();
            if e.args.len() != parameters.len() || e.args.iter().any(|a| !a.value.is_empty()) {
                return self.fail(
                    "predicate requires positional arguments matching its signature",
                    e,
                );
            }
            for (a, p) in e.args.iter().zip(&parameters) {
                let actual = self.actual(a)?;
                if self.enums.iter().any(|(n, _)| *n == p.r#type.name) {
                    if self.check(actual)? != format!("enum:{}", p.r#type.name) {
                        return self.fail("predicate enum argument type mismatch", actual);
                    }
                    continue;
                }
                if self.check(actual)? != "Entity" || actual.kind != "role" {
                    return self.fail("predicate argument must be a bound entity role", actual);
                }
                let kind = &self.roles[&actual.value];
                let expected = &c.types[&p.r#type.name];
                if !kind_is(kind, expected) {
                    return self.fail(
                        "predicate argument does not match its declared domain",
                        actual,
                    );
                }
                if distinct_parameter(kind, expected) {
                    return self.fail(
                        "receiver and ordinary parameter are distinct domains",
                        actual,
                    );
                }
            }
            return boolean();
        }
        if c.unary_relations.contains_key(name)
            || c.statement_unary.contains_key(name)
            || c.statement_relations.contains_key(name)
            || c.relations.contains_key(name)
            || matches!(name, "receives" | "preserves" | "instance_slot")
        {
            let unary = c.unary_relations.contains_key(name);
            let statement_one = c.statement_unary.contains_key(name);
            let statement_two = c.statement_relations.contains_key(name);
            let relation = c.relations.get(name);
            let count = if unary || statement_one { 1 } else { 2 };
            let message = if unary {
                "unary semantic relation expects one positional argument".into()
            } else if statement_one {
                "statement relation expects one positional argument".into()
            } else if statement_two {
                "statement relation expects two positional arguments".into()
            } else if relation.is_some() {
                "semantic relation expects two positional arguments".into()
            } else {
                format!("{name} expects two positional arguments")
            };
            if e.args.len() != count || e.args.iter().any(|a| !a.value.is_empty()) {
                return self.fail(message, e);
            }
            for (i, a) in e.args.iter().enumerate() {
                let actual = self.actual(a)?;
                let valid = self.entity(actual)?
                    && if unary {
                        kind_is(&self.roles[&actual.value], "callable")
                    } else if let Some((_, left, right)) = relation {
                        kind_is(
                            &self.roles[&actual.value],
                            &c.types[if i == 0 { left } else { right }],
                        )
                    } else {
                        true
                    };
                if !valid {
                    let message = if unary {
                        "unary semantic relation argument must be a Callable role".into()
                    } else if statement_one || statement_two {
                        "statement relation argument must be a bound entity role".into()
                    } else if relation.is_some() {
                        "semantic relation argument has wrong domain".into()
                    } else {
                        format!("{name} argument must be a bound entity role")
                    };
                    return self.fail(message, actual);
                }
            }
            return boolean();
        }
        if matches!(
            name,
            "contains" | "contains_direct" | "same_symbol" | "visible_at" | "initialized_at"
        ) {
            if e.args.len() != 2 || e.args.iter().any(|a| !a.value.is_empty()) {
                return self.fail("AST relation requires two positional nodes", e);
            }
            for a in &e.args {
                let a = self.actual(a)?;
                if a.kind != "role"
                    || !self
                        .roles
                        .get(&a.value)
                        .is_some_and(|v| matches!(v.as_str(), "node" | "expression" | "statement"))
                {
                    return self.fail("AST relation arguments must be common AST nodes", e);
                }
            }
            return boolean();
        }
        if matches!(name, "owns" | "kind_is") {
            if e.args.len() != 2 || e.args.iter().any(|a| !a.value.is_empty()) {
                return self.fail("structural relation expects two positional arguments", e);
            }
            let a = self.check(self.actual(&e.args[0])?)?;
            let b = self.check(self.actual(&e.args[1])?)?;
            if a == "Entity" && b == if name == "owns" { "Entity" } else { "String" } {
                return boolean();
            }
            return self.fail("structural relation argument type mismatch", e);
        }
        if name == "in_directory" && e.args.len() == 2 {
            if e.args.iter().any(|a| !a.value.is_empty()) {
                return self.fail("in_directory takes positional arguments", e);
            }
            if self.check(self.actual(&e.args[0])?)? == "Entity"
                && self.check(self.actual(&e.args[1])?)? == "String"
            {
                return boolean();
            }
        }
        Ok(None)
    }
}
fn numeric(t: &str) -> bool {
    matches!(t, "Int" | "Float")
}
