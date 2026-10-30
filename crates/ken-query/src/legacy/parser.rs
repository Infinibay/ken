use super::{Clause, Count, Pattern, variable};
use crate::execution::{ExecutionError, Result};
use regex::Regex;
use std::sync::OnceLock;

fn invalid(message: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(message.into())
}

/// POSIX shlex tokenization, separately for each physical source line. Quotes
/// concatenate with adjacent unquoted text; comments start outside quotes.
fn words(line: &str) -> Result<Vec<String>> {
    let mut result = vec![];
    let mut word = String::new();
    let mut active = false;
    let mut quote = None;
    let mut chars = line.chars();
    while let Some(c) = chars.next() {
        if let Some(q) = quote {
            if c == q {
                quote = None;
            } else if c == '\\' && q == '"' {
                let next = chars
                    .next()
                    .ok_or_else(|| invalid("No escaped character"))?;
                if next != q && next != '\\' {
                    word.push('\\');
                }
                word.push(next);
            } else {
                word.push(c);
            }
        } else {
            match c {
                '#' => break,
                '\'' | '"' => {
                    quote = Some(c);
                    active = true;
                }
                '\\' => {
                    word.push(
                        chars
                            .next()
                            .ok_or_else(|| invalid("No escaped character"))?,
                    );
                    active = true;
                }
                ' ' | '\t' | '\r' | '\n' => {
                    if active {
                        result.push(std::mem::take(&mut word));
                        active = false;
                    }
                }
                _ => {
                    word.push(c);
                    active = true;
                }
            }
        }
    }
    if quote.is_some() {
        return Err(invalid("No closing quotation"));
    }
    if active {
        result.push(word);
    }
    Ok(result)
}
fn clause(words: &[String], mode: &str) -> Result<Clause> {
    if words.len() < 3 {
        return Err(invalid("a clause requires SUBJECT RELATION OBJECT"));
    }
    static RELATION: OnceLock<Regex> = OnceLock::new();
    let relation = RELATION
        .get_or_init(|| Regex::new(r"^([A-Z][A-Z_0-9]*)(?:\{(\d+),(\d+)\}|(\+|\*))?$").unwrap());
    let captures = relation
        .captures(&words[1])
        .ok_or_else(|| invalid(format!("invalid relation: {}", words[1])))?;
    let (minimum, maximum) = if let Some(low) = captures.get(2) {
        let low = decimal(low.as_str())
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(usize::MAX);
        let high = decimal(&captures[3])
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(usize::MAX);
        (low, high)
    } else if captures.get(4).is_some() {
        (1, 16)
    } else {
        (1, 1)
    };
    if minimum < 1 || minimum > maximum || maximum > 32 {
        return Err(invalid("path bounds must satisfy 1 <= min <= max <= 32"));
    }
    let mut c = Clause {
        mode: mode.into(),
        subject: words[0].clone(),
        relation: captures[1].into(),
        object: words[2].clone(),
        attrs: vec![],
        minimum,
        maximum,
        count_op: ">=".into(),
        count: 1.into(),
        distinct: String::new(),
        r#where: vec![],
        capability: String::new(),
    };
    static ATTRIBUTE: OnceLock<Regex> = OnceLock::new();
    let attribute =
        ATTRIBUTE.get_or_init(|| Regex::new(r"^([\w.]+)(!=|>=|<=|~=|=|>|<)(.+)$").unwrap());
    for word in &words[3..] {
        let a = attribute
            .captures(word)
            .ok_or_else(|| invalid(format!("invalid attribute: {word}")))?;
        if &a[1] == "when_capability" {
            c.capability = a[3].into();
        } else {
            c.attrs.push((a[1].into(), a[2].into(), a[3].into()));
        }
    }
    Ok(c)
}
fn directive(p: &mut Pattern, current: &mut Option<String>, words: &[String]) -> Result<()> {
    let (d, args) = words.split_first().unwrap();
    let c = match d.as_str() {
        "pattern" => {
            p.name = args.join(" ");
            return Ok(());
        }
        "scope" if args == ["project"] => return Ok(()),
        "capability" if !args.is_empty() => {
            p.capabilities.extend(args.iter().cloned());
            return Ok(());
        }
        "different" if args.len() == 2 => {
            p.different.push((args[0].clone(), args[1].clone()));
            return Ok(());
        }
        "variant" if args.len() == 1 => {
            if current.is_some() || p.variants.contains_key(&args[0]) {
                return Err(invalid("nested or duplicate variant"));
            }
            p.variant_order.push(args[0].clone());
            p.variants.insert(args[0].clone(), vec![]);
            *current = Some(args[0].clone());
            return Ok(());
        }
        "end" if args.is_empty() && current.is_some() => {
            *current = None;
            return Ok(());
        }
        "require" | "optional" | "forbid" => clause(args, d)?,
        "count" => {
            let (comparison, rest) = args
                .split_first()
                .ok_or_else(|| invalid("pop from empty list"))?;
            static COUNT: OnceLock<Regex> = OnceLock::new();
            let captures = COUNT
                .get_or_init(|| Regex::new(r"^(>=|<=|=|>|<)(\d+)$").unwrap())
                .captures(comparison)
                .ok_or_else(|| invalid("count requires a comparison such as >=2"))?;
            let at = rest.iter().position(|w| w == "where").unwrap_or(rest.len());
            let main = &rest[..at];
            let mut c = clause(
                &main
                    .iter()
                    .filter(|a| !a.starts_with("distinct="))
                    .cloned()
                    .collect::<Vec<_>>(),
                "count",
            )?;
            c.count_op = captures[1].into();
            c.count = Count::from_decimal(&captures[2])
                .ok_or_else(|| invalid("count comparison is out of range"))?;
            c.distinct = main
                .iter()
                .find_map(|a| a.strip_prefix("distinct=").map(str::to_owned))
                .unwrap_or_default();
            if at < rest.len() {
                for group in rest[at + 1..]
                    .split(|w| w == "and")
                    .filter(|g| !g.is_empty())
                {
                    c.r#where.push(clause(group, "require")?);
                }
            }
            c
        }
        _ => return Err(invalid(format!("unknown or malformed directive: {d}"))),
    };
    if let Some(name) = current {
        p.variants.get_mut(name).unwrap().push(c);
    } else {
        p.clauses.push(c);
    }
    Ok(())
}
pub fn parse_pattern(source: &str, validate_roles: bool) -> Result<Pattern> {
    let mut p = Pattern::default();
    let mut current = None;
    // Match Python str.splitlines(), treating CRLF as one separator.
    let mut lines = Vec::new();
    let mut begin = 0;
    let mut skip_lf = false;
    for (at, c) in source.char_indices() {
        if skip_lf && c == '\n' {
            begin = at + 1;
            skip_lf = false;
            continue;
        }
        skip_lf = false;
        if matches!(
            c,
            '\n' | '\r'
                | '\u{b}'
                | '\u{c}'
                | '\u{1c}'
                | '\u{1d}'
                | '\u{1e}'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        ) {
            lines.push(&source[begin..at]);
            begin = at + c.len_utf8();
            skip_lf = c == '\r';
        }
    }
    if begin < source.len() {
        lines.push(&source[begin..]);
    }
    for (number, line) in lines.into_iter().enumerate() {
        let tokens = words(line)?;
        if !tokens.is_empty() {
            directive(&mut p, &mut current, &tokens)
                .map_err(|e| invalid(format!("line {}: {e}", number + 1)))?;
        }
    }
    if current.is_some() {
        return Err(invalid("unterminated variant"));
    }
    if !p.clauses.iter().any(|c| c.mode == "require") && p.variants.is_empty() {
        return Err(invalid("a pattern needs at least one required clause"));
    }
    if validate_roles {
        let variants: Vec<_> = if p.variants.is_empty() {
            vec![&[][..]]
        } else {
            p.variants.values().map(Vec::as_slice).collect()
        };
        for variant in variants {
            let bound: std::collections::BTreeSet<_> = p
                .clauses
                .iter()
                .chain(variant)
                .filter(|c| c.mode == "require")
                .flat_map(|c| [&c.subject, &c.object])
                .filter(|t| variable(t))
                .collect();
            if p.different
                .iter()
                .any(|(a, b)| !bound.contains(a) || !bound.contains(b))
            {
                return Err(invalid(
                    "different requires two roles bound by required clauses",
                ));
            }
        }
    }
    Ok(p)
}

// Python int accepts every Unicode decimal digit matched by the grammar's \d.
pub(super) fn decimal(text: &str) -> Option<String> {
    static ZEROES: OnceLock<Vec<u32>> = OnceLock::new();
    let zeroes = ZEROES.get_or_init(|| {
        serde_json::from_str(include_str!("../../resources/float-decimal-zeroes.json"))
            .expect("frozen Unicode15 decimal digits")
    });
    let mut result = String::new();
    for c in text.chars() {
        let n = c as u32;
        let i = zeroes.partition_point(|z| *z <= n);
        if i == 0 || n - zeroes[i - 1] >= 10 {
            return None;
        }
        result.push((b'0' + (n - zeroes[i - 1]) as u8) as char);
    }
    if result.is_empty() {
        None
    } else {
        Some(result)
    }
}
