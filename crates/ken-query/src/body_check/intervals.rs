//! Interval effects name protected bindings and forbidden targets.
use super::*;
fn binding(effect: Operand<'_>, name: &str, message: &str, span: &Span) -> Result<String> {
    if effect.kind() != "call"
        || effect.value() != name
        || effect.len() != 1
        || !arg(effect, 0)?.value().is_empty()
    {
        return Err(error(message, span));
    }
    let role = arg(arg(effect, 0)?, 0)?;
    if role.kind() != "role" {
        return Err(error(message, span));
    }
    Ok(role.value().into())
}
pub(super) fn terminal_bindings(c: &Clause) -> Result<Vec<String>> {
    let mut roles = vec![];
    for constraint in block(c) {
        let message = "terminal gap supports forbid assign(binding(...))";
        if constraint.kind != "forbid" {
            return Err(error(message, &constraint.span));
        }
        let e = operand(constraint, 0)?;
        if e.kind() != "call"
            || e.value() != "assign"
            || e.len() != 1
            || !arg(e, 0)?.value().is_empty()
        {
            return Err(error(message, &constraint.span));
        }
        roles.push(binding(
            arg(arg(e, 0)?, 0)?,
            "binding",
            "assign requires binding($role)",
            &constraint.span,
        )?);
    }
    if roles.is_empty() {
        return Err(error(
            "terminal gap requires an assignment restriction",
            &c.span,
        ));
    }
    Ok(roles)
}
pub(super) struct IntervalRestrictions {
    pub protected: Vec<String>,
    pub forbidden: Vec<String>,
}
pub(super) fn interval_restrictions(c: &Clause) -> Result<IntervalRestrictions> {
    let mut roles = vec![];
    let mut targets = None;
    for constraint in block(c) {
        if constraint.kind == "property" && constraint.name == "paths" {
            let e = operand(constraint, 0)?;
            if e.kind() == "name" && e.value() == "all"
                || e.kind() == "literal" && e.value() == "\"all\""
            {
                continue;
            }
            return Err(error("this gap requires paths: all", &constraint.span));
        }
        if constraint.kind != "forbid" {
            return Err(error("unsupported interval effect", &constraint.span));
        }
        let e = operand(constraint, 0)?;
        if e.kind() == "call" && e.value() == "call" {
            if targets.is_none() {
                targets = Some(forbidden_targets(c)?);
            }
            continue;
        }
        if e.kind() != "call"
            || e.value() != "write"
            || e.len() != 1
            || !arg(e, 0)?.value().is_empty()
        {
            return Err(error(
                "this interval supports forbid write(binding(...))",
                &constraint.span,
            ));
        }
        roles.push(binding(
            arg(arg(e, 0)?, 0)?,
            "binding",
            "write requires an explicit binding",
            &constraint.span,
        )?);
    }
    Ok(IntervalRestrictions {
        protected: roles,
        forbidden: targets.unwrap_or_default(),
    })
}
pub(super) fn forbidden_targets(c: &Clause) -> Result<Vec<String>> {
    let mut roles = vec![];
    for constraint in block(c) {
        if constraint.kind != "forbid" {
            continue;
        }
        let e = operand(constraint, 0)?;
        if e.kind() != "call" || e.value() != "call" {
            continue;
        }
        if e.len() == 0
            || e.len() > 2
            || !arg(e, 0)?.value().is_empty()
            || arg(arg(e, 0)?, 0)?.kind() != "role"
        {
            return Err(error(
                "forbid call requires a bound Callable",
                &constraint.span,
            ));
        }
        if e.len() == 2 {
            let a = arg(e, 1)?;
            if a.value() != "through" || !matches!(arg(a, 0)?.value(), "direct" | "\"direct\"") {
                return Err(error(
                    "forbid call currently requires through: direct",
                    &constraint.span,
                ));
            }
        }
        roles.push(arg(arg(e, 0)?, 0)?.value().into());
    }
    Ok(roles)
}
