use super::*;
use context::*;
pub fn validate(pattern: &BodyPattern, check: &mut dyn FnMut() -> Result<()>) -> Result<()> {
    let mut patterns = vec![(pattern, 0usize)];
    let mut work = 0usize;
    while let Some((pattern, depth)) = patterns.pop() {
        check()?;
        work += 1;
        if depth > 96 || work > 200_000 {
            return Err(invalid("BODY pattern validation limit exceeded"));
        }
        if pattern.owner.is_empty() {
            return Err(invalid("BODY owner role is empty"));
        }
        for clause in &pattern.clauses {
            check()?;
            work += 1;
            let n = clause.expressions.len();
            match clause.kind.as_str() {
                "call" | "construct" => {
                    if clause.role.is_empty() || clause.blocks.len() != 1 {
                        return Err(invalid("BODY call requires a role and constraint block"));
                    }
                    validate_call(clause)?;
                }
                "let" => {
                    if clause.role.is_empty() {
                        return Err(invalid("BODY let requires an output role"));
                    }
                    if n == 1 && op(clause, 0)?.kind() == "index" {
                    } else if block(clause).len() == 1
                        && matches!(block(clause)[0].kind.as_str(), "call" | "construct")
                    {
                        validate_call(&block(clause)[0])?;
                    } else {
                        return Err(invalid("malformed BODY let"));
                    }
                }
                "return" => {
                    if n > 1 {
                        return Err(invalid("BODY return accepts one operand"));
                    }
                }
                "yield" | "where" | "if" | "iterate" => {
                    if n != 1 {
                        return Err(invalid("BODY step requires one operand"));
                    }
                }
                "assign" => {
                    if n != 2 {
                        return Err(invalid("BODY assignment requires two operands"));
                    }
                }
                "insert" => {
                    if !(1..=2).contains(&n) || clause.role.is_empty() {
                        return Err(invalid("BODY insertion requires collection and value"));
                    }
                }
                "clear" | "macro" | "break" => {
                    if clause.role.is_empty() {
                        return Err(invalid("BODY step requires a role"));
                    }
                }
                "resume" => {
                    if !matches!(clause.name.as_str(), "next" | "throw" | "close") {
                        return Err(invalid("invalid BODY resumption"));
                    }
                }
                "gap" => {
                    restrictions(clause, flag(clause, "exit"))?;
                }
                "initializer" => {
                    if block(clause).is_empty() {
                        return Err(invalid("initializer requires an assignment"));
                    }
                    for assignment in block(clause) {
                        if assignment.kind != "assign"
                            || assignment.expressions.len() != 2
                            || assignment.expressions.iter().any(|e| e.kind() != "role")
                        {
                            return Err(invalid("initializer requires role assignments"));
                        }
                    }
                }
                "selector" => {
                    if clause.role.is_empty() {
                        return Err(invalid("BODY selector requires a role"));
                    }
                    for c in block(clause) {
                        if c.kind != "property"
                            || !matches!(c.name.as_str(), "name" | "type" | "type_status")
                            || c.expressions.len() != 1
                        {
                            return Err(invalid("unsupported BODY selector property"));
                        }
                    }
                }
                "adjacent" => (),
                _ => return Err(invalid(format!("unknown BODY step {}", clause.kind))),
            }
            if matches!(
                clause.kind.as_str(),
                "return" | "yield" | "assign" | "insert" | "if" | "iterate"
            ) || (clause.kind == "let" && !clause.expressions.is_empty())
            {
                for e in &clause.expressions {
                    source_operand(O::from(e))?;
                }
            }
            if clause.kind == "iterate" && !pattern.nested.iter().any(|(c, _)| c == clause) {
                return Err(invalid("iteration requires a prepared BODY"));
            }
            if clause.kind == "if" {
                let arms = pattern
                    .controls
                    .iter()
                    .find(|(c, _)| c == clause)
                    .ok_or_else(|| invalid("conditional requires prepared BODY arms"))?;
                if arms.1.len() != clause.blocks.len() {
                    return Err(invalid("conditional BODY arm inventory disagrees"));
                }
            }
            let mut clauses = vec![(clause, 0usize)];
            while let Some((c, d)) = clauses.pop() {
                check()?;
                work += 1;
                if d > 96 || work > 200_000 {
                    return Err(invalid("BODY clause validation limit exceeded"));
                }
                let mut expressions = c
                    .expressions
                    .iter()
                    .map(|e| (O::from(e), 0usize))
                    .collect::<Vec<_>>();
                while let Some((e, ed)) = expressions.pop() {
                    check()?;
                    work += 1;
                    if ed > 96 || work > 200_000 {
                        return Err(invalid("BODY expression validation limit exceeded"));
                    }
                    if matches!(e.kind(), "member" | "index")
                        && (e.len() == 0 || (e.kind() == "index" && e.len() != 2))
                    {
                        return Err(invalid("malformed source access"));
                    }
                    if e.kind() == "binary" && e.len() != 2 {
                        return Err(invalid("binary source expression requires two operands"));
                    }
                    if e.kind() == "unary" && e.len() != 1 {
                        return Err(invalid("unary source expression requires one operand"));
                    }
                    expressions.extend(e.args().map(|e| (e, ed + 1)));
                }
                clauses.extend(c.blocks.iter().flatten().map(|c| (c, d + 1)));
            }
        }
        patterns.extend(pattern.nested.iter().map(|(_, p)| (p, depth + 1)));
        for (_, arms) in &pattern.controls {
            patterns.extend(arms.iter().map(|p| (p, depth + 1)));
        }
    }
    Ok(())
}
fn validate_call(clause: &Clause) -> Result<()> {
    if clause.role.is_empty() || clause.blocks.len() != 1 {
        return Err(invalid("BODY call requires a role and constraint block"));
    }
    for c in block(clause) {
        match c.kind.as_str() {
            "argument" => {
                if c.expressions.is_empty() {
                    return Err(invalid("BODY argument requires an operand"));
                }
                if c.role.is_empty() && c.name != "any" {
                    if c.name.starts_with('"') {
                        if serde_json::from_str::<String>(&c.name).is_err() {
                            return Err(invalid("malformed BODY argument keyword"));
                        }
                    } else if c.name.is_empty() || !c.name.chars().all(|c| c.is_ascii_digit()) {
                        return Err(invalid("BODY argument requires a position or parameter"));
                    }
                }
                for e in &c.expressions {
                    if e.kind() != "from" {
                        source_operand(O::from(e))?;
                    }
                }
            }
            "property" => {
                if c.expressions.len() != 1 {
                    return Err(invalid("BODY property requires one operand"));
                }
                if !matches!(
                    c.name.as_str(),
                    "entry"
                        | "receiver"
                        | "receiver_input"
                        | "receiver_version"
                        | "name"
                        | "resolution"
                        | "dispatch"
                        | "discarded"
                        | "returned"
                        | "unreplaced"
                        | "rebound"
                        | "wraps"
                        | "empty"
                        | "present"
                        | "fallback"
                        | "retained"
                ) {
                    return Err(invalid(format!("unknown BODY call property {}", c.name)));
                }
            }
            "initializer" => (),
            _ => return Err(invalid(format!("unknown BODY call constraint {}", c.kind))),
        }
    }
    Ok(())
}

fn source_operand(root: O<'_>) -> Result<()> {
    let mut pending = vec![(root, 0usize)];
    let mut work = 0;
    while let Some((e, depth)) = pending.pop() {
        work += 1;
        if depth > 96 || work > 200_000 {
            return Err(invalid("BODY source operand limit exceeded"));
        }
        match e.kind() {
            "role" | "literal" | "wildcard" => {
                if e.len() != 0 || (e.kind() == "role" && e.value().is_empty()) {
                    return Err(invalid("malformed BODY source operand"));
                }
            }
            "member" => {
                if !(1..=2).contains(&e.len()) || e.args().any(|a| a.kind() != "role") {
                    return Err(invalid("source member requires roles"));
                }
            }
            "index" => {
                if e.len() != 2
                    || arg(e, 0)?.kind() != "role"
                    || !matches!(
                        arg(e, 1)?.kind(),
                        "role" | "literal" | "wildcard" | "member"
                    )
                {
                    return Err(invalid("malformed BODY source index"));
                }
                pending.push((arg(e, 1)?, depth + 1));
            }
            "binary" | "unary" => {
                let arity = if e.kind() == "binary" { 2 } else { 1 };
                if e.len() != arity || e.value().is_empty() {
                    return Err(invalid("malformed BODY source operator"));
                }
                pending.extend(e.args().map(|e| (e, depth + 1)));
            }
            "call" if e.value() == "read" => {
                if e.len() != 1 {
                    return Err(invalid("read requires one binding"));
                }
                let a = arg(e, 0)?;
                if !a.value().is_empty() || a.len() != 1 || arg(a, 0)?.kind() != "role" {
                    return Err(invalid("read requires one binding"));
                }
                pending.push((arg(a, 0)?, depth + 1));
            }
            "call" if e.value() == "binary" => {
                let (left, _, right) =
                    crate::body_check::binary_parts(e).map_err(|e| invalid(e.message))?;
                pending.push((left, depth + 1));
                pending.push((right, depth + 1));
            }
            _ => {
                return Err(invalid(format!(
                    "unsupported BODY source operand {}",
                    e.kind()
                )));
            }
        }
    }
    Ok(())
}
