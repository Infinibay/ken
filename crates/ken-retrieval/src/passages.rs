use crate::{EntityKey, Passage, PassageFields, Result, RetrievalError, Span, classify_role};
use ken_syntax::{ParsedFile, ParsedScope};
use ken_text::unicode::{splitlines, whitespace, word};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
pub const EXTRACTOR_VERSION: usize = 8;
pub trait TokenCounter {
    fn count(&self, text: &str) -> Result<usize>;
}
pub struct LexicalCounter;
impl TokenCounter for LexicalCounter {
    fn count(&self, text: &str) -> Result<usize> {
        let mut n = 0;
        let mut previous = false;
        for c in text.chars() {
            let current = word(c);
            if current {
                if !previous {
                    n += 1
                }
            } else if !whitespace(c) {
                n += 1
            }
            previous = current;
        }
        Ok(n)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PassagePolicy {
    pub max_tokens: usize,
    pub tokenizer_version: String,
}
impl Default for PassagePolicy {
    fn default() -> Self {
        Self {
            max_tokens: 256,
            tokenizer_version: "code-lexical-v1".into(),
        }
    }
}
impl PassagePolicy {
    pub fn new(max_tokens: usize, tokenizer_version: impl Into<String>) -> Result<Self> {
        if max_tokens == 0 {
            return Err(RetrievalError::Invalid(
                "max_tokens must be positive".into(),
            ));
        }
        Ok(Self {
            max_tokens,
            tokenizer_version: tokenizer_version.into(),
        })
    }
}
pub fn extract_passages(
    source: &[u8],
    parsed: &ParsedFile,
    path: &str,
    language: &str,
    policy: &PassagePolicy,
    counter: &dyn TokenCounter,
) -> Result<Vec<Passage>> {
    if policy.max_tokens == 0 {
        return Err(RetrievalError::Invalid(
            "max_tokens must be positive".into(),
        ));
    }
    if source.contains(&0) {
        return Ok(vec![]);
    }
    let Ok(text) = std::str::from_utf8(source) else {
        return Ok(vec![]);
    };
    let lines = splitlines(text);
    if lines.is_empty() {
        return Ok(vec![]);
    }
    let hash = format!("{:x}", Sha256::digest(source));
    let mut scopes = parsed.scopes.clone();
    if scopes.is_empty() {
        for symbol in &parsed.symbols {
            let signature = lines
                .get(symbol.line_start.wrapping_sub(1))
                .ok_or_else(|| RetrievalError::Invalid("symbol starts outside source".into()))?
                .to_string();
            scopes.push(ParsedScope {
                symbol: symbol.clone(),
                owner: symbol.qualname.rsplit_once('.').map(|(s, _)| s.into()),
                signature,
                documentation: symbol.docstring.clone().map(Into::into),
                statements: vec![],
                implementation_start_line: None,
                annotations: vec![],
            });
        }
    }
    scopes.sort_by(|a, b| {
        a.symbol
            .line_start
            .cmp(&b.symbol.line_start)
            .then_with(|| b.symbol.line_end.cmp(&a.symbol.line_end))
    });
    let mut assigned = vec![None; lines.len() + 1];
    let mut sorted: Vec<_> = (0..scopes.len()).collect();
    sorted.sort_by_key(|&i| {
        scopes[i]
            .symbol
            .line_end
            .saturating_sub(scopes[i].symbol.line_start)
    });
    for i in sorted {
        let s = &scopes[i].symbol;
        if s.line_start > 0 && s.line_start <= s.line_end.min(lines.len()) {
            for slot in &mut assigned[s.line_start..=s.line_end.min(lines.len())] {
                slot.get_or_insert(i);
            }
        }
    }
    let mut groups = HashMap::new();
    let mut identities = Vec::new();
    for scope in &scopes {
        let s = &scope.symbol;
        let ordinal = groups
            .entry((&s.kind, &s.qualname, &scope.owner))
            .or_insert(0);
        identities.push(EntityKey {
            path: path.into(),
            kind: s.kind.clone(),
            qualname: Some(s.qualname.clone()),
            owner: scope.owner.clone(),
            definition_ordinal: *ordinal,
        });
        *ordinal += 1;
    }
    let module = EntityKey {
        path: path.into(),
        kind: "module".into(),
        qualname: None,
        owner: None,
        definition_ordinal: 0,
    };
    let mut out = Vec::new();
    let mut start = 1;
    while start <= lines.len() {
        let owner = assigned[start];
        let scope = owner.map(|i| &scopes[i]);
        let implementation = scope.and_then(|s| s.implementation_start_line);
        let mut end = start;
        while end < lines.len() && assigned[end + 1] == owner {
            if implementation == Some(end + 1) {
                break;
            }
            let candidate = lines[start - 1..end + 1].join("\n");
            if counter.count(&candidate)? > policy.max_tokens {
                break;
            }
            end += 1;
        }
        if end < lines.len() && assigned[end + 1] == owner && implementation != Some(end + 1) {
            end = scope
                .and_then(|s| {
                    s.statements
                        .iter()
                        .map(|(_, e)| *e)
                        .filter(|e| start <= *e && *e <= end)
                        .max()
                })
                .unwrap_or(end)
        }
        let body = lines[start - 1..end].join("\n");
        if !body.trim_matches(whitespace).is_empty() {
            let entity = owner.map_or(&module, |i| &identities[i]);
            let identity = [
                Some(entity.kind.as_str()),
                entity.qualname.as_deref(),
                entity.owner.as_deref(),
            ]
            .into_iter()
            .flatten()
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
            let fields = PassageFields {
                identity: identity.into(),
                signature: scope.map_or("", |s| s.signature.as_str()).into(),
                documentation: scope.map_or_else(
                    || parsed.docstring.as_deref().unwrap_or("").into(),
                    |s| s.documentation.clone().unwrap_or_else(|| "".into()),
                ),
                body: body.clone().into(),
                path: path.into(),
            };
            out.push(Passage {
                entity: entity.clone(),
                span: Span::new(start, end)?,
                fields,
                source_hash: hash.clone(),
                entity_span: scope.map_or_else(
                    || Span::new(1, lines.len()),
                    |s| Span::new(s.symbol.line_start, s.symbol.line_end),
                )?,
                language: language.into(),
                role: classify_role(
                    path,
                    entity.qualname.as_deref(),
                    scope.map_or(&[], |s| s.annotations.as_slice()),
                )
                .into(),
                split_reason: (counter.count(&body)? > policy.max_tokens)
                    .then(|| "oversized_line".into()),
                signals: BTreeMap::new(),
                implementation_start_line: implementation,
            });
        }
        start = end + 1;
    }
    Ok(out)
}
