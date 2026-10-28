//! Public source views retain identity while trimming only complete physical lines.
pub use crate::result_selection::displayed_matches;
use crate::{
    Span,
    evidence::{MAX_EVIDENCE_LINES, entity_extent, source_bounds, source_text, verified_lines},
    intent::{QueryIntent, interpret},
    piece_cards::{CardEntity, PieceCard, validate_card},
    query::{CodeMatch, SearchRequest, Signals},
    rank_json,
    source_catalog::SourceCatalog,
    source_snapshot::{SourceAuthority, SourceError, SourceResult, invalid},
    vocabulary::code_terms_python,
};
use ken_text::PythonText;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Evidence {
    pub start_line: usize,
    pub end_line: usize,
    pub content: String,
}
#[derive(Clone, Debug, Serialize)]
pub struct DisplayedSource {
    pub path: String,
    pub entity: CardEntity,
    pub entity_span: Span,
    pub evidence: Vec<Evidence>,
    pub source_hash: String,
    pub stale: bool,
    pub truncated: bool,
}
#[derive(Clone, Debug, Serialize)]
pub struct OwnerResult {
    #[serde(flatten)]
    pub source: DisplayedSource,
    pub language: String,
    pub ranking_score: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signals: Option<Signals>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub matches: Option<Vec<CardEntity>>,
}
#[derive(Clone, Debug, Serialize)]
pub struct PieceResult {
    #[serde(flatten)]
    pub source: DisplayedSource,
    pub piece_kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub module_name: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signals: Option<Value>,
}
#[derive(Clone, Debug, Serialize)]
#[serde(untagged)]
pub enum SearchResult {
    Owner(OwnerResult),
    Piece(PieceResult),
}
impl SearchResult {
    pub fn source(&self) -> &DisplayedSource {
        match self {
            Self::Owner(r) => &r.source,
            Self::Piece(r) => &r.source,
        }
    }
    fn source_mut(&mut self) -> &mut DisplayedSource {
        match self {
            Self::Owner(r) => &mut r.source,
            Self::Piece(r) => &mut r.source,
        }
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct SearchResponse {
    pub query: PythonText,
    pub results: Vec<SearchResult>,
    pub profile_version: String,
    pub warnings: Vec<String>,
    pub truncated: bool,
    pub omitted_count: usize,
}
impl SearchResponse {
    pub fn new(request: &SearchRequest, profile_version: &str) -> Self {
        Self {
            query: request.query().clone(),
            results: Vec::new(),
            profile_version: profile_version.into(),
            warnings: Vec::new(),
            truncated: false,
            omitted_count: 0,
        }
    }
    /// Python's ensure_ascii=False semantic length, including lone surrogates.
    pub fn python_characters(&self) -> usize {
        let body = json!({"results":self.results,"profile_version":self.profile_version,"warnings":self.warnings,"truncated":self.truncated,"omitted_count":self.omitted_count});
        json_characters(&body) + "\"query\":".len() + 1 + string_characters(&self.query)
    }
}
fn string_characters(text: &PythonText) -> usize {
    rank_json::quote(text).chars().count()
        - 5 * text
            .codepoints()
            .iter()
            .filter(|p| (0xd800..=0xdfff).contains(*p))
            .count()
}
fn json_characters(value: &Value) -> usize {
    match value {
        Value::Null => 4,
        Value::Bool(true) => 4,
        Value::Bool(false) => 5,
        Value::Number(n) => {
            if n.is_f64() {
                rank_json::float(n.as_f64().expect("finite response number")).len()
            } else {
                n.to_string().len()
            }
        }
        Value::String(s) => string_characters(&s.as_str().into()),
        Value::Array(a) => {
            2 + a.len().saturating_sub(1) + a.iter().map(json_characters).sum::<usize>()
        }
        Value::Object(o) => {
            2 + o.len().saturating_sub(1)
                + o.iter()
                    .map(|(key, value)| {
                        string_characters(&key.as_str().into()) + 1 + json_characters(value)
                    })
                    .sum::<usize>()
        }
    }
}
fn terms(text: &PythonText) -> BTreeSet<String> {
    code_terms_python(text, None).into_iter().collect()
}
fn overlap(query: &BTreeSet<String>, text: &PythonText) -> usize {
    query.intersection(&terms(text)).count()
}
fn fragment(lines: &[String], span: Span) -> SourceResult<Evidence> {
    Ok(Evidence {
        start_line: span.start_line,
        end_line: span.end_line,
        content: source_text(lines, span).map_err(|e| invalid(e.to_string()))?,
    })
}
fn rounded_score(score: f64) -> f64 {
    format!("{score:.8}")
        .parse()
        .expect("decimal-rounded finite score")
}
fn path_repr(path: &str) -> String {
    let quote = if path.contains('\'') && !path.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut result = quote.to_string();
    for c in path.chars() {
        match c {
            '\\' => result.push_str("\\\\"),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            c if c == quote => {
                result.push('\\');
                result.push(c);
            }
            c if c.is_control() && u32::from(c) <= 255 => {
                result.push_str(&format!("\\x{:02x}", u32::from(c)))
            }
            _ => result.push(c),
        }
    }
    result.push(quote);
    result
}
fn source_message(source: &SourceAuthority, path: &str, error: &SourceError) -> String {
    if let SourceError::Io(io) = error
        && let Some(code) = io.raw_os_error()
    {
        let message = io.to_string();
        let suffix = format!(" (os error {code})");
        return format!(
            "[Errno {code}] {}: {}",
            message.strip_suffix(&suffix).unwrap_or(&message),
            path_repr(&source.location(path).to_string_lossy())
        );
    }
    error.to_string()
}
fn quote_owner(
    result: &mut DisplayedSource,
    owner: &CodeMatch,
    source: &SourceAuthority,
    request: &SearchRequest,
    query: &BTreeSet<String>,
    intent: &QueryIntent,
) -> SourceResult<()> {
    let lines = verified_lines(source, owner)?;
    let extent = entity_extent(owner).map_err(|e| invalid(e.to_string()))?;
    result.entity_span = extent;
    let executable = |p: &&crate::Passage| {
        p.implementation_start_line
            .is_none_or(|start| p.span.end_line >= start)
            || request.purpose() == "documentation"
    };
    let mut ordered: Vec<_> = owner.evidence.iter().collect();
    ordered.sort_by(|a, b| {
        executable(b)
            .cmp(&executable(a))
            .then_with(|| {
                b.signals
                    .get("joint_evidence")
                    .copied()
                    .unwrap_or(f64::NEG_INFINITY)
                    .total_cmp(
                        &a.signals
                            .get("joint_evidence")
                            .copied()
                            .unwrap_or(f64::NEG_INFINITY),
                    )
            })
            .then_with(|| {
                b.signals
                    .get("cosine_behavior")
                    .copied()
                    .unwrap_or(-1.)
                    .total_cmp(&a.signals.get("cosine_behavior").copied().unwrap_or(-1.))
            })
            .then_with(|| overlap(query, &b.fields.body).cmp(&overlap(query, &a.fields.body)))
            .then_with(|| a.span.start_line.cmp(&b.span.start_line))
    });
    if intent.identity {
        ordered.sort_by_key(|p| p.span.start_line);
    }
    let best = ordered[0];
    let bounds = source_bounds(
        owner,
        best,
        lines.len(),
        request.purpose() != "documentation" && !intent.identity,
    )
    .map_err(|e| invalid(e.to_string()))?;
    let mut center = (bounds.start_line.max(best.span.start_line) + best.span.end_line) / 2;
    if best.span.end_line - best.span.start_line + 1 > MAX_EVIDENCE_LINES {
        let first_line = bounds.start_line.max(best.span.start_line);
        let mut focus = first_line;
        let mut score = 0;
        for line in first_line..=best.span.end_line {
            let text = lines
                .get(line - 1)
                .ok_or_else(|| invalid("invalid source range"))?;
            let measured = overlap(query, &text.as_str().into());
            if measured > score {
                score = measured;
                focus = line;
            }
        }
        if score > 0 {
            center = focus;
        }
    }
    let mut start = (center as i128 - 19)
        .min(bounds.end_line as i128 - 39)
        .max(bounds.start_line as i128) as usize;
    let mut end = bounds.end_line.min(start + 39);
    if best
        .signals
        .get("selected_window")
        .is_some_and(|v| *v != 0.)
    {
        start = best.span.start_line;
        end = best.span.end_line;
    }
    result.evidence = vec![fragment(
        &lines,
        Span::new(start, end).map_err(|e| invalid(e.to_string()))?,
    )?];
    result.truncated = start > extent.start_line || end < extent.end_line;
    let mut selected: Vec<_> = owner
        .evidence
        .iter()
        .filter(|p| p.signals.get("selected_window").is_some_and(|v| *v != 0.))
        .collect();
    if !selected.is_empty() {
        selected.sort_by_key(|p| p.span.start_line);
        result.evidence = selected
            .iter()
            .map(|p| fragment(&lines, p.span))
            .collect::<SourceResult<_>>()?;
        let shown: usize = selected
            .iter()
            .map(|p| p.span.end_line - p.span.start_line + 1)
            .sum();
        if shown > MAX_EVIDENCE_LINES {
            return Err(invalid("selected evidence exceeds line budget"));
        }
        result.truncated = shown < extent.end_line - extent.start_line + 1;
    }
    if owner.signals.get("exact").is_some_and(|v| *v != 0.)
        && !intent.identity
        && selected.is_empty()
    {
        let declaration = extent.start_line;
        let body = &mut result.evidence[0];
        if declaration < body.start_line {
            let width = 8
                .min(
                    owner.evidence[0]
                        .fields
                        .signature
                        .codepoints()
                        .iter()
                        .filter(|p| **p == 10)
                        .count()
                        + 1,
                )
                .min(body.start_line - declaration);
            body.end_line = body.end_line.min(body.start_line + 39 - width);
            body.content = source_text(
                &lines,
                Span {
                    start_line: body.start_line,
                    end_line: body.end_line,
                },
            )
            .map_err(|e| invalid(e.to_string()))?;
            result.evidence.insert(
                0,
                fragment(
                    &lines,
                    Span {
                        start_line: declaration,
                        end_line: declaration + width - 1,
                    },
                )?,
            );
        }
    }
    Ok(())
}
pub fn present(
    matches: &[CodeMatch],
    source: &SourceAuthority,
    request: &SearchRequest,
    profile_version: &str,
) -> SourceResult<SearchResponse> {
    let mut response = SearchResponse::new(request, profile_version);
    let query = terms(request.query());
    let intent = interpret(request);
    for (_, owner) in displayed_matches(matches, request) {
        let first = owner
            .evidence
            .first()
            .ok_or_else(|| invalid("presentation requires source evidence"))?;
        let mut result = DisplayedSource {
            path: owner.entity.path.clone(),
            entity: CardEntity::from(&owner.entity),
            entity_span: first.entity_span,
            evidence: Vec::new(),
            source_hash: owner.source_hash.clone(),
            stale: false,
            truncated: false,
        };
        if let Err(error) = quote_owner(&mut result, owner, source, request, &query, &intent) {
            result.evidence.clear();
            result.stale = true;
            response.warnings.push(format!(
                "{}: {}; reindex source before quoting evidence",
                owner.entity.path,
                source_message(source, &owner.entity.path, &error)
            ));
        }
        response.results.push(SearchResult::Owner(OwnerResult {
            source: result,
            language: first.language.clone(),
            ranking_score: rounded_score(owner.score),
            signals: request.explain().then(|| owner.signals.clone()),
            matches: (request.target() == "file").then(|| {
                matches
                    .iter()
                    .filter(|m| m.entity.path == owner.entity.path)
                    .take(10)
                    .map(|m| CardEntity::from(&m.entity))
                    .collect()
            }),
        }));
    }
    response.omitted_count = matches.len().saturating_sub(response.results.len());
    response.truncated =
        response.omitted_count > 0 || response.results.iter().any(|r| r.source().truncated);
    while !response.results.is_empty() && response.python_characters() > request.max_chars() {
        let result = response
            .results
            .last_mut()
            .expect("nonempty response")
            .source_mut();
        let fragments = &mut result.evidence;
        if fragments.len() > 1 {
            fragments.pop();
            result.truncated = true;
        } else if let Some(fragment) = fragments.first_mut().filter(|e| e.start_line < e.end_line) {
            let mut lines: Vec<_> = fragment.content.split('\n').collect();
            if overlap(
                &query,
                &lines.last().expect("physical fragment").to_string().into(),
            ) > overlap(&query, &lines[0].into())
            {
                fragment.start_line += 1;
                lines.remove(0);
            } else {
                fragment.end_line -= 1;
                lines.pop();
            }
            fragment.content = lines.join("\n");
            result.truncated = true;
        } else {
            response.results.pop();
            response.omitted_count += 1;
        }
        response.truncated = true;
    }
    Ok(response)
}
pub fn present_cards(
    cards: &[PieceCard],
    request: &SearchRequest,
    catalog: &SourceCatalog,
    profile_version: &str,
) -> SourceResult<SearchResponse> {
    let mut response = SearchResponse::new(request, profile_version);
    for card in cards.iter().take(request.limit()) {
        let unit = &card.unit;
        let kind = unit.target_kind.as_str();
        let entity = unit.entity.clone().unwrap_or_else(|| CardEntity {
            kind: kind.into(),
            qualname: unit.module_name.clone(),
            owner: None,
            definition_ordinal: 0,
        });
        let [start, end] = if let Some(key) = &unit.entity {
            catalog.extent(&key.at(&unit.path))?
        } else {
            [
                1,
                catalog
                    .snapshots()
                    .get(&unit.path)
                    .ok_or_else(|| invalid("unknown/stale card source"))?
                    .lines()
                    .len()
                    .max(1),
            ]
        };
        let mut result = DisplayedSource {
            path: unit.path.clone(),
            entity,
            entity_span: Span::new(start, end).map_err(|e| invalid(e.to_string()))?,
            evidence: Vec::new(),
            source_hash: card.source_hash.clone(),
            stale: false,
            truncated: card.truncated,
        };
        if let Err(error) = validate_card(card, catalog, true) {
            result.stale = true;
            response.warnings.push(format!(
                "{}: {}; reindex before quoting source",
                unit.path,
                source_message(catalog.source(), &unit.path, &error)
            ));
        } else {
            let mut remaining = if request.explain() { 64 } else { 16 };
            for excerpt in &card.excerpts {
                if remaining == 0 {
                    result.truncated = true;
                    break;
                }
                let count = remaining.min(excerpt.end_line - excerpt.start_line + 1);
                result.evidence.push(Evidence {
                    start_line: excerpt.start_line,
                    end_line: excerpt.start_line + count - 1,
                    content: excerpt
                        .content
                        .split('\n')
                        .take(count)
                        .collect::<Vec<_>>()
                        .join("\n"),
                });
                result.truncated |= count < excerpt.end_line - excerpt.start_line + 1;
                remaining -= count;
            }
        }
        let mut contiguous: Vec<Evidence> = Vec::new();
        for fragment in result.evidence {
            if let Some(last) = contiguous
                .last_mut()
                .filter(|last| last.end_line + 1 == fragment.start_line)
            {
                last.end_line = fragment.end_line;
                last.content.push('\n');
                last.content.push_str(&fragment.content);
            } else {
                contiguous.push(fragment);
            }
        }
        result.evidence = contiguous;
        response.results.push(SearchResult::Piece(PieceResult {
            source: result,
            piece_kind: kind.into(),
            module_name: (kind == "module").then(|| unit.module_name.clone()),
            signals: None,
        }));
    }
    response.omitted_count = cards.len().saturating_sub(response.results.len());
    while !response.results.is_empty() && response.python_characters() > request.max_chars() {
        if let Some(result) = response
            .results
            .iter_mut()
            .rev()
            .find(|r| !r.source().evidence.is_empty())
        {
            let result = result.source_mut();
            let fragment = result.evidence.last_mut().expect("reducible source");
            if fragment.start_line == fragment.end_line {
                result.evidence.pop();
            } else {
                fragment.end_line -= 1;
                let mut lines: Vec<_> = fragment.content.split('\n').collect();
                lines.pop();
                fragment.content = lines.join("\n");
            }
            result.truncated = true;
        } else {
            response.results.pop();
            response.omitted_count += 1;
        }
        response.truncated = true;
    }
    response.truncated |=
        response.omitted_count > 0 || response.results.iter().any(|r| r.source().truncated);
    Ok(response)
}
