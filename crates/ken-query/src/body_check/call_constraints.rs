//! Invocation/constructor constraints share capture state, not execution state.
use super::*;
impl BodyChecker<'_> {
    pub(super) fn target(&mut self, item: &Clause, qualified: bool, span: &Span) -> Result<()> {
        if !self.roles.contains_key(&item.role) {
            self.capture(
                &item.role,
                if qualified {
                    "type_parameter"
                } else {
                    "callable"
                },
            );
        }
        if !in_kinds(
            self.roles.get(&item.role),
            if qualified {
                &["type_parameter"]
            } else {
                TARGETS
            },
        ) {
            return Err(error(
                "call requires a bound Callable target or a retained callable",
                span,
            ));
        }
        Ok(())
    }

    pub(super) fn construct(&mut self, item: &Clause, instruction_span: &Span) -> Result<()> {
        if !self.roles.contains_key(&item.role) {
            self.capture(&item.role, "type");
        } else if !in_kinds(
            self.roles.get(&item.role),
            &["type", "class", "interface", "trait"],
        ) {
            return Err(error("construct requires a bound type", instruction_span));
        }
        for c in block(item) {
            match c.kind.as_str() {
                "initializer" => {
                    if !in_kinds(self.roles.get(&c.role), STORAGE) {
                        return Err(error("initializer requires a bound storage role", &c.span));
                    }
                    for e in &c.expressions {
                        self.source(e.into(), true, false)?;
                    }
                    let props = block(c);
                    if props.len() > 1 {
                        return Err(error("initializer accepts one transfer property", &c.span));
                    }
                    for p in props {
                        let v = p.expressions.first().map(Operand::from);
                        if p.kind != "property"
                            || p.name != "transfer"
                            || v.is_none_or(|v| {
                                v.kind() != "list"
                                    || v.len() == 0
                                    || v.args().any(|a| {
                                        a.kind() != "name"
                                            || !matches!(a.value(), "identity" | "shallow_copy")
                                    })
                            })
                        {
                            return Err(error(
                                "initializer transfer requires [identity, shallow_copy] or a subset",
                                &c.span,
                            ));
                        }
                    }
                }
                "argument" => {
                    if !c.role.is_empty() && !in_kinds(self.roles.get(&c.role), &["param"]) {
                        return Err(error("argument for requires a bound Parameter", &c.span));
                    }
                    if let Some(e) = c.expressions.iter().find(|e| e.kind() != "from") {
                        self.source(e.into(), true, false)?;
                    }
                }
                "where" => (),
                "property" if c.name == "retained" => self.source(operand(c, 0)?, true, false)?,
                _ => return Err(error("unsupported construct constraint", &c.span)),
            }
        }
        Ok(())
    }
    pub(super) fn call_constraints(&mut self, item: &Clause, let_form: bool) -> Result<()> {
        for c in block(item) {
            let fail = |m| error(m, &c.span);
            if c.kind == "argument" && c.alias.is_empty() {
                if !c.role.is_empty() && !in_kinds(self.roles.get(&c.role), &["param"]) {
                    return Err(fail("argument for requires a bound Parameter"));
                }
                if let Some(given) = c.expressions.iter().find(|e| e.kind() != "from") {
                    self.source(given.into(), true, false)?;
                }
                for derived in c.expressions.iter().filter(|e| e.kind() == "from") {
                    if !in_kinds(self.roles.get(derived.value()), VALUES) {
                        return Err(error("derivation requires a bound place", derived.span()));
                    }
                }
                continue;
            }
            if c.kind != "property" {
                return Err(fail("unsupported call constraint"));
            }
            let e = operand(c, 0)?;
            let value = e.value().trim_matches('"');
            match c.name.as_str() {
                "dispatch"
                    if matches!(
                        e.value(),
                        "exact"
                            | "possible"
                            | "contract"
                            | "\"exact\""
                            | "\"possible\""
                            | "\"contract\""
                    ) => {}
                "entry" | "receiver_input" => {
                    if e.kind() != "role" || !in_kinds(self.roles.get(e.value()), PLACES) {
                        return Err(error(
                            format!("{} requires a bound storage role", c.name),
                            &c.span,
                        ));
                    }
                }
                "receiver" => {
                    if !let_form && e.kind() == "member" {
                        let holder = arg(e, 0)?;
                        if holder.kind() != "role"
                            || !in_kinds(self.roles.get(holder.value()), PLACES)
                        {
                            return Err(fail("receiver member requires a bound storage role"));
                        }
                    } else if e.kind() != "role" || !in_kinds(self.roles.get(e.value()), PLACES) {
                        return Err(fail("receiver requires a bound storage role"));
                    }
                }
                "receiver_version" if !let_form => {
                    if e.kind() != "role" {
                        return Err(fail("receiver_version requires a role"));
                    }
                    self.roles
                        .entry(e.value().into())
                        .or_insert_with(|| "value".into());
                }
                "resolution"
                    if matches!(value, "resolved" | "unresolved" | "ambiguous" | "any") => {}
                "name" => {
                    let name = named_role(e);
                    if !name.is_empty() && self.expected.contains_key(name) {
                        self.capture(name, "value");
                    } else if !name_spellings(e) && !name_regex(e)? {
                        return Err(fail("unsupported call constraint"));
                    }
                }
                "discarded" | "returned" if value == "true" => (),
                "unreplaced" if value == "true" => {
                    if !block(item)
                        .iter()
                        .any(|c| c.kind == "property" && c.name == "receiver")
                    {
                        return Err(fail(
                            "unreplaced requires the receiver place of the same call",
                        ));
                    }
                }
                "rebound" if matches!(value, "true" | "false") => {
                    if !block(item)
                        .iter()
                        .any(|c| c.kind == "property" && c.name == "receiver")
                    {
                        return Err(fail("rebound requires the receiver place of the same call"));
                    }
                }
                name if vocabulary().optional_roles.contains_key(name) => {
                    if !matches!(e.kind(), "role" | "literal" | "name" | "wildcard") {
                        return Err(fail("optional row requires a role or literal"));
                    }
                    if e.kind() == "role" && !self.roles.contains_key(e.value()) {
                        self.capture(
                            e.value(),
                            if matches!(name, "empty" | "present") {
                                "callable"
                            } else {
                                "value"
                            },
                        );
                    }
                }
                _ => return Err(fail("unsupported call constraint")),
            }
        }
        Ok(())
    }
}
pub(super) fn named_role(e: Operand<'_>) -> &str {
    if e.kind() == "role" {
        e.value()
    } else if e.kind() == "binary"
        && e.value() == "in"
        && e.arg(0).is_some_and(|a| a.kind() == "role")
    {
        e.arg(0).unwrap().value()
    } else {
        ""
    }
}
pub(super) fn name_spellings(e: Operand<'_>) -> bool {
    e.kind() == "literal"
        || e.kind() == "list" && e.len() > 0 && e.args().all(|a| a.kind() == "literal")
}
pub(super) fn name_regex(e: Operand<'_>) -> Result<bool> {
    if e.kind() != "regex" {
        return Ok(false);
    }
    let Some((pattern, _flags)) = e.value().strip_prefix('/').and_then(|v| v.rsplit_once('/'))
    else {
        return Err(error("name regex is not a valid expression", e.span()));
    };
    if pattern.chars().count() > 512
        || pattern.contains("(?")
        || pattern
            .as_bytes()
            .windows(2)
            .any(|p| p[0] == b'\\' && matches!(p[1], b'1'..=b'9'))
    {
        return Err(error(
            "name regex must be regular (no backreferences or lookaround)",
            e.span(),
        ));
    }
    crate::regex_syntax::validate(pattern)
        .map_err(|_| error("name regex is not a valid expression", e.span()))?;
    Ok(true)
}
