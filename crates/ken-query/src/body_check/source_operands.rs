//! Binding and operand rules for source expressions and branch conditions.
use super::*;
impl BodyChecker<'_> {
    pub(super) fn variable(&mut self, item: &Clause) -> Result<()> {
        if self.roles.get(&item.role).is_some_and(|r| r != "var") {
            return Err(error("var capture requires a Binding role", &item.span));
        }
        if !self.roles.contains_key(&item.role) {
            self.capture(&item.role, "var");
        }
        for p in block(item) {
            if p.kind != "property" || !matches!(p.name.as_str(), "name" | "type" | "type_status") {
                return Err(error("unsupported variable property", &p.span));
            }
            let v = operand(p, 0)?;
            match p.name.as_str() {
                "type" => {
                    let O::Query(v) = v else {
                        return Err(error("unknown source type matcher", v.span()));
                    };
                    crate::source_matcher::validate_matcher(v)?;
                }
                "name"
                    if !matches!(v, O::Query(_))
                        || !matches!(v.kind(), "literal" | "regex" | "wildcard")
                        || v.kind() == "literal" && !json_string(v) =>
                {
                    return Err(error("variable name requires string or regex", &p.span));
                }
                "type_status" => {
                    let decoded = if v.kind() == "name" {
                        Some(v.value().to_owned())
                    } else if v.kind() == "literal" {
                        serde_json::from_str::<String>(v.value()).ok()
                    } else {
                        None
                    };
                    if !matches!(v, O::Query(_))
                        || !decoded.is_some_and(|s| matches!(s.as_str(), "known" | "unknown"))
                    {
                        return Err(error("type_status requires known or unknown", &p.span));
                    }
                }
                _ => (),
            }
        }
        Ok(())
    }
    pub(super) fn condition(&mut self, e: Operand<'_>, capture: bool) -> Result<()> {
        crate::with_stack(|| {
            if e.kind() == "call" && e.value() == "binary" {
                let (left, _, right) = binary_parts(e)?;
                self.condition(left, capture)?;
                return self.condition(right, capture);
            }
            if !matches!(
                e.kind(),
                "role" | "literal" | "binary" | "unary" | "wildcard" | "index"
            ) {
                return Err(error("unsupported condition expression", e.span()));
            }
            if e.kind() == "index" {
                let container = arg(e, 0)?;
                let key = arg(e, 1)?;
                if container.kind() != "role"
                    || !in_kinds(self.roles.get(container.value()), PLACES)
                {
                    return Err(error(
                        "condition requires a bound collection place",
                        e.span(),
                    ));
                }
                if key.kind() == "role" && !self.roles.contains_key(key.value()) {
                    if !capture || !in_kinds(self.expected.get(key.value()), &["value", "call"]) {
                        return Err(error("condition key requires a bound operand", e.span()));
                    }
                    self.capture(key.value(), "value");
                } else if key.kind() == "role" && !in_kinds(self.roles.get(key.value()), PLACES)
                    || !matches!(key.kind(), "role" | "literal" | "wildcard" | "member")
                {
                    return Err(error("condition key requires a bound operand", e.span()));
                }
                return Ok(());
            }
            if e.kind() == "role" && !self.roles.contains_key(e.value()) {
                if !capture || !in_kinds(self.expected.get(e.value()), &["value", "call"]) {
                    return Err(error(
                        "condition requires a bound source binding or captured value",
                        e.span(),
                    ));
                }
                self.capture(e.value(), "value");
            } else if e.kind() == "role" && !in_kinds(self.roles.get(e.value()), PLACES) {
                return Err(error(
                    "condition requires a bound source binding or captured value",
                    e.span(),
                ));
            }
            for a in e.args() {
                self.condition(a, capture)?;
            }
            Ok(())
        })
    }
    pub(super) fn source(
        &mut self,
        e: Operand<'_>,
        allow_value: bool,
        capture: bool,
    ) -> Result<()> {
        crate::with_stack(|| {
            if e.kind() == "call" && e.value() == "binary" {
                let (left, _, right) = binary_parts(e)?;
                self.source(left, allow_value, capture)?;
                return self.source(right, allow_value, capture);
            }
            if e.kind() == "call" && e.value() == "read" && e.len() == 1 {
                let a = arg(e, 0)?;
                if a.value().is_empty() && arg(a, 0)?.kind() == "role" {
                    return self.source(arg(a, 0)?, allow_value, capture);
                }
            }
            if e.kind() == "member" {
                let place = e.arg(0);
                if place.is_none_or(|p| {
                    p.kind() != "role" || !in_kinds(self.roles.get(p.value()), PLACES)
                }) || e.len() > 2
                    || e.len() == 2
                        && e.arg(1).is_none_or(|p| {
                            p.kind() != "role"
                                || !in_kinds(self.roles.get(p.value()), &["field", "var"])
                        })
                {
                    return Err(error("member requires a bound place", e.span()));
                }
                return Ok(());
            }
            if e.kind() == "index" {
                let container = arg(e, 0)?;
                let key = arg(e, 1)?;
                if container.kind() != "role"
                    || !in_kinds(
                        self.roles.get(container.value()),
                        &["var", "param", "receiver", "field", "value", "callable"],
                    )
                {
                    return Err(error("index requires a bound container place", e.span()));
                }
                if key.kind() == "role" {
                    if !self.roles.contains_key(key.value()) {
                        if !(capture || allow_value) {
                            return Err(error("index key requires a bound operand", e.span()));
                        }
                        self.capture(key.value(), "value");
                    } else if !in_kinds(self.roles.get(key.value()), PLACES) {
                        return Err(error("index key requires a bound operand", e.span()));
                    }
                } else if !matches!(key.kind(), "literal" | "wildcard" | "member") {
                    return Err(error("index key requires a bound operand", e.span()));
                }
                return Ok(());
            }
            if !matches!(
                e.kind(),
                "role" | "literal" | "binary" | "unary" | "wildcard"
            ) {
                return Err(error("unsupported source expression", e.span()));
            }
            let message = if allow_value {
                "source operand requires a bound storage, parameter or captured value"
            } else {
                "source operand requires a bound storage or parameter"
            };
            if e.kind() == "role" && !self.roles.contains_key(e.value()) {
                if !capture || !in_kinds(self.expected.get(e.value()), &["value", "call"]) {
                    return Err(error(message, e.span()));
                }
                self.capture(e.value(), "value");
            } else if e.kind() == "role"
                && !in_kinds(
                    self.roles.get(e.value()),
                    if allow_value { VALUES } else { STORAGE },
                )
            {
                return Err(error(message, e.span()));
            }
            for a in e.args() {
                self.source(a, allow_value, capture)?;
            }
            Ok(())
        })
    }
}
fn json_string(e: Operand<'_>) -> bool {
    e.kind() == "literal" && serde_json::from_str::<String>(e.value()).is_ok()
}
fn binary_parts(e: Operand<'_>) -> Result<(Operand<'_>, Operand<'_>, Operand<'_>)> {
    let mut arguments = BTreeMap::new();
    for a in e.args() {
        arguments.insert(a.value(), arg(a, 0)?);
    }
    if arguments.len() != e.len()
        || arguments.keys().copied().collect::<Vec<_>>() != ["left", "operator", "right"]
    {
        return Err(error(
            "binary requires left:, operator:, and right: exactly once",
            e.span(),
        ));
    }
    let operator = arguments["operator"];
    if operator.kind() != "wildcard" {
        let valid = if operator.kind() == "list" {
            operator.len() > 0 && operator.args().all(json_string)
        } else {
            json_string(operator)
        };
        if !valid {
            return Err(error(
                "binary operator requires _, a string, or a nonempty list of strings",
                operator.span(),
            ));
        }
    }
    Ok((arguments["left"], operator, arguments["right"]))
}
