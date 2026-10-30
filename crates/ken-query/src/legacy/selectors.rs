//! Compact selectors retain legacy attribute placement and explicit triple clauses.
use super::*;
use crate::execution::{ExecutionError, Result};
use crate::legacy_blocks::{Grammar, Tokens};
fn invalid(message: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(message.into())
}
const SELECTORS: &[(&str, &str)] = &[
    ("class", "CLASS"),
    ("interface", "INTERFACE"),
    ("method", "CALLABLE"),
    ("function", "CALLABLE"),
    ("var_declaration", "STORAGE"),
    ("variable", "STORAGE"),
    ("parameter", "PARAMETER"),
    ("call", "CALL"),
    ("value", "VALUE"),
    ("collection", "COLLECTION"),
    ("entity", "_"),
];
const RELATIONS: &[(&str, &str, &str)] = &[
    ("has_method", "HAS_METHOD", "CALLABLE"),
    ("has_parameter", "HAS_PARAMETER", "PARAMETER"),
    ("has_argument", "ARGUMENT", "_"),
    ("has_call", "HAS_CALL", "CALL"),
    ("has_field", "HAS_FIELD", "STORAGE"),
    ("returns", "RETURNS", "_"),
    ("reads", "READS", "_"),
    ("writes", "WRITES", "_"),
    ("calls", "CALLS", "CALLABLE"),
    ("used_by", "CALLS", "CALLABLE"),
];
struct Parser {
    tokens: Tokens,
    pattern: Pattern,
    auto: usize,
    depth: usize,
}
fn clause(
    subject: String,
    relation: &str,
    object: String,
    attrs: Vec<(String, String, String)>,
) -> Clause {
    Clause {
        mode: "require".into(),
        subject,
        relation: relation.into(),
        object,
        attrs,
        minimum: 1,
        maximum: 1,
        count_op: ">=".into(),
        count: 1.into(),
        distinct: String::new(),
        r#where: vec![],
        capability: String::new(),
    }
}
impl Parser {
    fn literal(&mut self) -> Result<(String, String)> {
        crate::with_stack(|| {
            self.depth += 1;
            if self.depth > 128 {
                return Err(invalid("legacy query nesting limit exceeded"));
            }
            let result = self.literal_inner();
            self.depth -= 1;
            result
        })
    }
    fn literal_inner(&mut self) -> Result<(String, String)> {
        let token = self
            .tokens
            .tokens
            .get(self.tokens.at)
            .cloned()
            .ok_or_else(|| invalid("expected token, reached end of query"))?;
        self.tokens.at += 1;
        if token.text == "[" {
            let mut items = vec![];
            while !self.tokens.peek("]") {
                let (op, value) = self.literal()?;
                if op != "=" {
                    return Err(invalid("type alternatives accept literal values"));
                }
                items.push(value);
                if !self.tokens.peek("]") {
                    self.tokens.expect(",")?;
                }
            }
            self.tokens.expect("]")?;
            if items.is_empty() {
                return Err(invalid("empty alternatives"));
            }
            return Ok(("=".into(), items.join("|")));
        }
        if token.kind == "regex" {
            let (pattern, flags) = token.text[1..].rsplit_once('/').unwrap();
            if pattern.chars().count() > 512 {
                return Err(invalid("regular expressions are limited to 512 characters"));
            }
            crate::execution::regex_runtime::Pattern::compile(
                pattern,
                flags,
                crate::execution::regex_runtime::Dialect::Regex,
                &mut || Ok(()),
            )?;
            return Ok((
                "regex".into(),
                if flags.is_empty() {
                    pattern.into()
                } else {
                    format!("(?{flags}){pattern}")
                },
            ));
        }
        if token.kind == "string" {
            let text = crate::literal_strings::decode(&token.text)
                .and_then(|v| v.to_utf8())
                .ok_or_else(|| invalid("invalid selector string literal"))?;
            return Ok(("=".into(), text));
        }
        Ok(("=".into(), token.text))
    }
    fn selector(&mut self, parent: &str) -> Result<()> {
        crate::with_stack(|| {
            self.depth += 1;
            if self.depth > 128 {
                return Err(invalid("legacy query nesting limit exceeded"));
            }
            let result = self.selector_inner(parent);
            self.depth -= 1;
            result
        })
    }
    fn selector_inner(&mut self, parent: &str) -> Result<()> {
        let name = self.tokens.next()?;
        self.tokens.expect("(")?;
        let mut attrs = vec![];
        while !self.tokens.peek(")") {
            let key = self.tokens.next()?;
            self.tokens.expect(":")?;
            let (op, value) = self.literal()?;
            if value != "*" {
                attrs.push((key, op, value));
            }
            if !self.tokens.peek(")") {
                self.tokens.expect(",")?;
            }
        }
        self.tokens.expect(")")?;
        if self.tokens.peek("as") {
            self.tokens.next()?;
        }
        let alias = if let Some(t) = self.tokens.tokens.get(self.tokens.at).filter(|t| {
            t.kind == "word"
                && !SELECTORS.iter().any(|(n, _)| *n == t.text)
                && !RELATIONS.iter().any(|(n, _, _)| *n == t.text)
        }) {
            let text = t.text.clone();
            self.tokens.at += 1;
            if text.starts_with('$') {
                text
            } else {
                format!("${text}")
            }
        } else {
            self.auto += 1;
            format!("$_{}", self.auto)
        };
        if let Some((_, relation, kind)) = RELATIONS.iter().find(|(n, _, _)| *n == name) {
            if parent.is_empty() {
                return Err(invalid(format!("{name} needs an enclosing selector")));
            }
            if name == "has_parameter" && !attrs.iter().any(|(k, _, _)| k == "receiver") {
                attrs.push(("receiver".into(), "=".into(), "false".into()));
            }
            let (mut edge_attrs, mut entity_attrs) = (vec![], vec![]);
            for (key, op, value) in attrs {
                if name == "has_argument" && matches!(key.as_str(), "pos" | "name" | "kind") {
                    edge_attrs.push((
                        if key == "pos" { "position".into() } else { key },
                        op,
                        value,
                    ));
                } else {
                    entity_attrs.push((key, op, value));
                }
            }
            let (a, z) = if name == "used_by" {
                (alias.clone(), parent.into())
            } else {
                (parent.into(), alias.clone())
            };
            self.pattern
                .clauses
                .push(clause(a, relation, z, edge_attrs));
            self.pattern.clauses.push(clause(
                alias.clone(),
                "ENTITY",
                kind.to_string(),
                entity_attrs,
            ));
        } else if let Some((_, kind)) = SELECTORS.iter().find(|(n, _)| *n == name) {
            if !parent.is_empty() {
                return Err(invalid(
                    "nested selectors must name a relationship, e.g. has_method",
                ));
            }
            if name == "var_declaration" {
                attrs.push(("declared".into(), "=".into(), "true".into()));
            }
            self.pattern
                .clauses
                .push(clause(alias.clone(), "ENTITY", kind.to_string(), attrs));
        } else if name == "operation" {
            self.pattern
                .clauses
                .push(clause(alias.clone(), "OPERATION", "_".into(), attrs));
        } else {
            return Err(invalid(format!(
                "unknown selector {}; use entity(...) for generic entities",
                ken_program::value::GraphValue::String(name.as_str().into()).repr()
            )));
        }
        if self.tokens.peek("{") {
            self.tokens.next()?;
            while !self.tokens.peek("}") {
                self.selector(&alias)?;
            }
            self.tokens.expect("}")?;
        }
        if self.tokens.peek(";") {
            self.tokens.next()?;
        }
        Ok(())
    }
}
fn is_selector(source: &str) -> bool {
    SELECTORS
        .iter()
        .map(|(n, _)| *n)
        .chain(RELATIONS.iter().map(|(n, _, _)| *n))
        .chain(["operation"])
        .any(|name| {
            source.match_indices(name).any(|(at, _)| {
                source[..at]
                    .chars()
                    .next_back()
                    .is_none_or(|c| !ken_text::unicode::word(c))
                    && source[at + name.len()..]
                        .trim_start_matches(ken_text::unicode::whitespace)
                        .starts_with('(')
            })
        })
}
pub fn parse_query(source: &str) -> Result<Pattern> {
    if !is_selector(source) {
        return parse_pattern(source, true);
    }
    let (mut lines, mut triples) = (vec![], vec![]);
    for line in source.lines() {
        let stripped = line.trim_start_matches(ken_text::unicode::whitespace);
        let tag = stripped
            .split(ken_text::unicode::whitespace)
            .next()
            .unwrap_or("");
        if [
            "require",
            "optional",
            "forbid",
            "count",
            "different",
            "capability",
            "pattern",
            "scope",
        ]
        .contains(&tag)
            && stripped[tag.len()..]
                .chars()
                .next()
                .is_some_and(ken_text::unicode::whitespace)
        {
            triples.push(
                line.trim_end_matches(ken_text::unicode::whitespace)
                    .strip_suffix(';')
                    .unwrap_or(line.trim_end_matches(ken_text::unicode::whitespace)),
            );
        } else {
            lines.push(line);
        }
    }
    let mut p = Parser {
        tokens: Tokens::new(&lines.join("\n"), Grammar::Selectors)?,
        pattern: Pattern {
            name: "query".into(),
            clauses: vec![],
            different: vec![],
            capabilities: Default::default(),
            variants: Default::default(),
            variant_order: vec![],
        },
        auto: 0,
        depth: 0,
    };
    while p.tokens.at < p.tokens.tokens.len() {
        p.selector("")?;
    }
    if !triples.is_empty() {
        let extra = parse_pattern(
            &format!("require $_anchor ENTITY _\n{}", triples.join("\n")),
            false,
        )?;
        p.pattern.clauses.extend(extra.clauses.into_iter().skip(1));
        p.pattern.different = extra.different;
        p.pattern.capabilities = extra.capabilities;
        if extra.name != "query" {
            p.pattern.name = extra.name;
        }
    }
    if p.pattern.clauses.is_empty() {
        return Err(invalid("empty query"));
    }
    let bound: BTreeSet<_> = p
        .pattern
        .clauses
        .iter()
        .filter(|c| c.mode == "require")
        .flat_map(|c| [&c.subject, &c.object])
        .collect();
    if p.pattern
        .different
        .iter()
        .any(|(a, b)| !bound.contains(a) || !bound.contains(b))
    {
        return Err(invalid(
            "different requires roles bound by selectors or required clauses",
        ));
    }
    Ok(p.pattern)
}
