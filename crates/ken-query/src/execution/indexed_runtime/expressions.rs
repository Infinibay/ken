//! Typed calculations and finite quantification; evaluation never invokes source code.
use super::super::source::Knowledge;
use super::super::values::{arithmetic, compare, unary};
use super::*;
use std::cmp::Ordering;
impl Runtime<'_, '_> {
    pub(super) fn evaluate(&mut self, e: &Expr, bindings: &Bindings) -> Result<Value> {
        crate::with_stack(|| {
            self.check()?;
            self.depth += 1;
            let result = if self.depth > 512 {
                Err(ExecutionError::Exhausted("evaluation_depth"))
            } else {
                self.evaluate_inner(e, bindings)
            };
            self.depth -= 1;
            result
        })
    }
    fn evaluate_inner(&mut self, e: &Expr, b: &Bindings) -> Result<Value> {
        let arg = |i: usize| {
            e.args
                .get(i)
                .ok_or_else(|| invalid("missing expression operand"))
        };
        match e.kind.as_str() {
            "type_test" => {
                let value = self.evaluate(arg(0)?, b)?;
                let descriptor = match value {
                    Value::Type(v) => Knowledge::Known(v),
                    _ => Knowledge::Unknown("capability_missing"),
                };
                self.with_source(|s| s.matches(&descriptor, arg(1)?))
                    .map(source::truth)
            }
            "literal" => Value::literal(&e.value),
            "role" => b
                .get(&e.value)
                .cloned()
                .ok_or_else(|| invalid(format!("unbound role {}", e.value))),
            "name" => {
                for (name, values) in &self.program.enums {
                    for value in values {
                        if e.value == format!("{name}.{value}") {
                            return Ok(Value::Enum {
                                r#type: name.clone(),
                                name: value.clone(),
                            });
                        }
                    }
                }
                Err(invalid(format!("unknown enum member {}", e.value)))
            }
            "member" => {
                let owner = self.evaluate(arg(0)?, b)?;
                self.property(&owner, &e.value)
            }
            "list" => Ok(Value::tuple(
                e.args
                    .iter()
                    .map(|a| self.evaluate(a, b))
                    .collect::<Result<Vec<_>>>()?,
            )),
            "unary" => {
                let v = self.evaluate(arg(0)?, b)?;
                located(e, unary(&e.value, &v))
            }
            "binary" => {
                let left = self.evaluate(arg(0)?, b)?;
                if e.value == "and" && left.is_false() {
                    return Ok(left);
                }
                if e.value == "or" && left.is_true() {
                    return Ok(left);
                }
                if e.value == "matches" {
                    return match &left {
                        Value::Scalar(ken_program::value::GraphValue::String(text)) => {
                            self.regex_text(text, arg(1)?).map(Value::boolean)
                        }
                        _ => Ok(Value::unknown("capability_missing")),
                    };
                }
                let right = self.evaluate(arg(1)?, b)?;
                match e.value.as_str() {
                    "and" => return Ok(left.and(right)),
                    "or" => return Ok(left.or(right)),
                    "in" if matches!(&right,Value::Tuple(v)if v.is_empty()) => {
                        return Ok(Value::boolean(false));
                    }
                    _ => (),
                }
                if left.is_unknown() {
                    return Ok(left);
                }
                if right.is_unknown() {
                    return Ok(right);
                }
                match e.value.as_str() {
                    "==" | "!=" => Ok(Value::boolean(
                        (left.identity()? == right.identity()?) == (e.value == "=="),
                    )),
                    "in" => {
                        let Value::Tuple(values) = right else {
                            return Err(invalid("membership requires a tuple"));
                        };
                        let key = left.identity()?;
                        for v in values.iter() {
                            if v.identity()? == key {
                                return Ok(Value::boolean(true));
                            }
                        }
                        Ok(Value::boolean(false))
                    }
                    "+" | "-" | "*" | "/" | "%" => located(e, arithmetic(&e.value, &left, &right)),
                    "<" | ">" | "<=" | ">=" => {
                        let order = compare(&left, &right)?;
                        Ok(Value::boolean(match e.value.as_str() {
                            "<" => order == Ordering::Less,
                            ">" => order == Ordering::Greater,
                            "<=" => order != Ordering::Greater,
                            _ => order != Ordering::Less,
                        }))
                    }
                    _ => Err(invalid(format!("unsupported binary operation {}", e.value))),
                }
            }
            "call" => {
                let args = e
                    .args
                    .iter()
                    .map(|a| {
                        a.args
                            .first()
                            .ok_or_else(|| invalid("call argument missing"))
                            .and_then(|a| self.evaluate(a, b))
                    })
                    .collect::<Result<Vec<_>>>()?;
                match e.value.as_str() {
                    "stable_id" => Ok(args
                        .first()
                        .and_then(source::local_id)
                        .map_or_else(|| Value::unknown("capability_missing"), Value::string)),
                    "in_directory" => {
                        let value = args
                            .first()
                            .and_then(source::path)
                            .zip(args.get(1).and_then(Value::text))
                            .map(|(path, dir)| {
                                path.split('/').rev().skip(1).any(|part| part == dir)
                            });
                        Ok(value
                            .map_or_else(|| Value::unknown("capability_missing"), Value::boolean))
                    }
                    _ => self.relation(&e.value, &args),
                }
            }
            "aggregate" | "quantifier" => self.quantified(e, b),
            _ => Err(invalid(format!("unknown expression operation {}", e.kind))),
        }
    }
    fn quantified(&mut self, e: &Expr, b: &Bindings) -> Result<Value> {
        if e.args.is_empty() {
            return Err(invalid("quantifier requires a condition"));
        }
        let mut domains = vec![];
        let mut closed = true;
        for p in &e.parameters {
            let (values, complete) = self.domain(&p.r#type.name, Some((&p.role, &e.args[0], b)))?;
            domains.push((p.role.clone(), values));
            closed &= complete;
        }
        let mut accumulator = Aggregate {
            uncertain: !closed,
            projected: vec![],
            keys: BTreeSet::new(),
            contributions: vec![],
            decided: None,
        };
        self.quantified_tuples(e, &domains, 0, b.clone(), &mut accumulator)?;
        if let Some(value) = accumulator.decided {
            return Ok(value);
        }
        if matches!(e.value.as_str(), "exists" | "forall") {
            return Ok(if accumulator.uncertain {
                Value::unknown("open_world")
            } else {
                Value::boolean(e.value == "forall")
            });
        }
        if accumulator.uncertain {
            return Ok(Value::unknown("incomplete_aggregate_domain"));
        }
        let values = &accumulator.projected;
        match e.value.as_str() {
            "count" => Ok(Value::integer(values.len())),
            "sum" => located(e, sum(values)),
            "sum_by" => located(e, sum(&accumulator.contributions)),
            "avg" if !values.is_empty() => {
                let total = located(e, sum(values))?;
                Ok(Value::some(located(
                    e,
                    arithmetic("/", &total, &Value::integer(values.len())),
                )?))
            }
            "min" | "max" if !values.is_empty() => {
                let mut chosen = values[0].clone();
                for v in &values[1..] {
                    let order = compare(v, &chosen).map_err(|error| match error {
                        ExecutionError::Invalid(message) => {
                            invalid(format!("{}:{}: {message}", e.span.source, e.span.start))
                        }
                        other => other,
                    })?;
                    if e.value == "min" && order == Ordering::Less
                        || e.value == "max" && order == Ordering::Greater
                    {
                        chosen = v.clone();
                    }
                }
                Ok(Value::some(chosen))
            }
            "avg" | "min" | "max" => Ok(Value::none()),
            _ => Err(invalid("unsupported aggregate")),
        }
    }
    fn quantified_tuples(
        &mut self,
        e: &Expr,
        domains: &[(String, Vec<Value>)],
        index: usize,
        b: Bindings,
        a: &mut Aggregate,
    ) -> Result<()> {
        crate::with_stack(|| {
            self.check()?;
            if a.decided.is_some() {
                return Ok(());
            }
            if index < domains.len() {
                let (role, values) = &domains[index];
                for v in values {
                    let mut local = b.clone();
                    local.insert(role.clone(), v.clone());
                    self.quantified_tuples(e, domains, index + 1, local, a)?;
                    if a.decided.is_some() {
                        break;
                    }
                }
                return Ok(());
            }
            let predicate = self.evaluate(&e.args[0], &b)?;
            if predicate.is_false() {
                return Ok(());
            }
            if predicate.is_unknown() {
                a.uncertain = true;
                return Ok(());
            }
            if e.value == "exists" {
                a.decided = Some(Value::boolean(true));
                return Ok(());
            }
            let projection = e
                .args
                .get(1)
                .ok_or_else(|| invalid("quantifier projection missing"))?;
            let value = self.evaluate(projection, &b)?;
            if e.value == "forall" {
                if value.is_false() {
                    a.decided = Some(Value::boolean(false));
                } else {
                    a.uncertain |= value.is_unknown();
                }
                return Ok(());
            }
            if value.is_unknown() {
                a.uncertain = true;
            } else {
                if a.keys.insert(value.identity()?) {
                    a.projected.push(value.clone());
                }
                a.contributions.push(value);
            }
            Ok(())
        })
    }
    pub(super) fn regex(&mut self, text: &str, e: &Expr) -> Result<bool> {
        self.regex_text(&text.into(), e)
    }
    fn regex_text(&mut self, text: &ken_text::PythonText, e: &Expr) -> Result<bool> {
        self.check()?;
        let (pattern, flags) = e
            .value
            .strip_prefix('/')
            .and_then(|raw| raw.rsplit_once('/'))
            .ok_or_else(|| invalid("invalid regex literal"))?;
        let mut cache = std::mem::take(&mut self.regex_patterns);
        let result = cache.compile(
            &pattern.into(),
            flags,
            super::super::regex_runtime::Dialect::Regex,
            &mut || self.check(),
        );
        self.regex_patterns = cache;
        let pattern = result?;
        pattern.is_match_with_timeout(
            text,
            Some(std::time::Duration::from_millis(50)),
            &mut || self.check(),
        )
    }
}
struct Aggregate {
    uncertain: bool,
    projected: Vec<Value>,
    keys: BTreeSet<String>,
    contributions: Vec<Value>,
    decided: Option<Value>,
}
fn sum(values: &[Value]) -> Result<Value> {
    let mut total = Value::integer(0);
    for value in values {
        total = arithmetic("+", &total, value)?;
    }
    Ok(total)
}

fn located(e: &Expr, result: Result<Value>) -> Result<Value> {
    result.map_err(|error| match error {
        ExecutionError::Invalid(message) => {
            invalid(format!("{}:{}: {message}", e.span.source, e.span.start))
        }
        other => other,
    })
}
