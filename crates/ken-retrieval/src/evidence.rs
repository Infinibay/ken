//! Faithful owner completion and judged source windows under a shared line budget.
use crate::{
    Passage, Result, RetrievalError, Span,
    intent::interpret,
    query::{Candidate, CodeMatch, SearchRequest, merge_spans},
    ranking::{RelevanceJudge, candidate_document},
    reductions::python_sum,
    result_selection::displayed_matches,
    source_snapshot::{SourceAuthority, SourceError, SourceResult, invalid},
};
use serde::Deserialize;

pub(crate) const MAX_EVIDENCE_LINES: usize = 40;

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct EvidenceOptions {
    pub limit: isize,
    pub max_windows: isize,
    pub max_fragments: isize,
}
impl Default for EvidenceOptions {
    fn default() -> Self {
        Self {
            limit: 1,
            max_windows: 6,
            max_fragments: 3,
        }
    }
}
fn invalid_evidence(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
pub fn verified_lines(source: &SourceAuthority, owner: &CodeMatch) -> SourceResult<Vec<String>> {
    let snapshot = source.read(&owner.entity.path).map_err(|e| match e {
        SourceError::Invalid(s) if s == "source outside root" => invalid("source escapes project"),
        other => other,
    })?;
    snapshot.verify(&owner.source_hash)?;
    if owner
        .evidence
        .iter()
        .any(|p| p.span.end_line > snapshot.lines().len())
    {
        return Err(invalid("invalid source range"));
    }
    Ok(snapshot.lines().to_vec())
}
pub fn entity_extent(owner: &CodeMatch) -> Result<Span> {
    if owner.evidence.is_empty()
        || owner
            .evidence
            .iter()
            .any(|p| p.entity != owner.entity || p.source_hash != owner.source_hash)
    {
        return Err(invalid_evidence(
            "entity extent requires one source owner and version",
        ));
    }
    let spans = owner
        .evidence
        .iter()
        .flat_map(|p| [p.span, p.entity_span])
        .chain(owner.owned_regions.iter().copied())
        .collect::<Vec<_>>();
    Span::new(
        spans.iter().map(|s| s.start_line).min().unwrap(),
        spans.iter().map(|s| s.end_line).max().unwrap(),
    )
}
pub fn source_bounds(
    owner: &CodeMatch,
    passage: &Passage,
    line_count: usize,
    implementation: bool,
) -> Result<Span> {
    let mut bounds = passage.entity_span;
    if owner.entity.qualname.is_none() {
        bounds = Span::new(1, line_count)?;
    }
    let regions = if owner.owned_regions.is_empty() {
        merge_spans(
            &owner
                .evidence
                .iter()
                .filter(|p| p.entity == owner.entity)
                .map(|p| p.span)
                .collect::<Vec<_>>(),
        )
    } else {
        owner.owned_regions.clone()
    };
    if !regions.is_empty() {
        bounds = regions
            .into_iter()
            .find(|r| {
                r.start_line <= passage.span.start_line && passage.span.start_line <= r.end_line
            })
            .unwrap_or(passage.span);
    }
    if implementation && bounds.end_line - bounds.start_line + 1 > MAX_EVIDENCE_LINES {
        bounds.start_line = bounds.end_line.min(
            bounds.start_line.max(
                passage
                    .implementation_start_line
                    .unwrap_or(bounds.start_line),
            ),
        );
    }
    Ok(bounds)
}
pub(crate) fn source_text(lines: &[String], span: Span) -> Result<String> {
    if span.start_line == 0 || span.start_line > span.end_line || span.end_line > lines.len() {
        return Err(invalid_evidence("invalid source range"));
    }
    Ok(lines[span.start_line - 1..span.end_line].join("\n"))
}
fn with_window(template: &Passage, lines: &[String], span: Span) -> Result<Passage> {
    let mut passage = template.clone();
    passage.span = span;
    passage.fields.body = source_text(lines, span)?.into();
    Ok(passage)
}
pub fn complete_owned_context(
    owner: &CodeMatch,
    source: &SourceAuthority,
) -> SourceResult<CodeMatch> {
    if owner.owned_regions.is_empty() {
        return Ok(owner.clone());
    }
    entity_extent(owner).map_err(|e| invalid(e.to_string()))?;
    let lines = verified_lines(source, owner)?;
    let template = &owner.evidence[0];
    let mut spans = Vec::new();
    for region in &owner.owned_regions {
        let mut p = template.clone();
        p.span = *region;
        spans
            .push(source_bounds(owner, &p, lines.len(), true).map_err(|e| invalid(e.to_string()))?);
    }
    let regions = merge_spans(&spans);
    if regions.is_empty()
        || regions.len() > 3
        || regions
            .iter()
            .map(|s| s.end_line - s.start_line + 1)
            .sum::<usize>()
            > MAX_EVIDENCE_LINES
    {
        return Ok(owner.clone());
    }
    if regions.iter().any(|r| r.end_line > lines.len()) {
        return Err(invalid("owned source region exceeds current source"));
    }
    let mut output = owner.clone();
    output.evidence = Vec::new();
    for region in regions {
        let mut p = with_window(template, &lines, region).map_err(|e| invalid(e.to_string()))?;
        p.signals.insert("selected_window".into(), 1.);
        output.evidence.push(p);
    }
    Ok(output)
}
pub fn complete_evidence(
    matches: &[CodeMatch],
    source: &SourceAuthority,
    request: &SearchRequest,
) -> Result<Vec<CodeMatch>> {
    let intent = interpret(request);
    let mut result = matches.to_vec();
    if intent.identity || intent.purpose == "documentation" {
        return Ok(result);
    }
    for (index, owner) in displayed_matches(matches, request) {
        if owner.signals.get("exact").is_some_and(|v| *v != 0.) {
            continue;
        }
        if let Ok(complete) = complete_owned_context(owner, source) {
            result[index] = complete;
        }
    }
    Ok(result)
}
fn distinct_passages(owner: &CodeMatch) -> Vec<&Passage> {
    let mut distinct: Vec<&Passage> = Vec::new();
    for passage in &owner.evidence {
        if let Some(previous) = distinct.iter_mut().find(|p| p.span == passage.span) {
            *previous = passage;
        } else {
            distinct.push(passage);
        }
    }
    distinct
}
fn utility(owner: &CodeMatch, fragments: &[Passage]) -> f64 {
    let peak = owner
        .evidence
        .iter()
        .map(|p| p.signals.get("joint_evidence").copied().unwrap_or(0.))
        .reduce(f64::max)
        .expect("window has source evidence");
    python_sum(distinct_passages(owner).into_iter().map(|p| {
        let overlap: usize = fragments
            .iter()
            .map(|w| {
                p.span
                    .end_line
                    .min(w.span.end_line)
                    .saturating_add(1)
                    .saturating_sub(p.span.start_line.max(w.span.start_line))
            })
            .sum();
        (-40_f64)
            .max(p.signals.get("joint_evidence").copied().unwrap_or(0.) - peak)
            .exp()
            * overlap as f64
            / (p.span.end_line - p.span.start_line + 1) as f64
    }))
}
fn windows(
    owner: &CodeMatch,
    lines: &[String],
    purpose: &str,
    limit: usize,
) -> Result<Vec<Passage>> {
    let mut proposals: Vec<Passage> = Vec::new();
    for p in &owner.evidence {
        let bounds = source_bounds(
            owner,
            p,
            lines.len(),
            !matches!(purpose, "identity" | "documentation"),
        )?;
        let width = MAX_EVIDENCE_LINES.min(bounds.end_line - bounds.start_line + 1);
        let starts = [
            p.span.start_line as i128,
            p.span.end_line as i128 - width as i128 + 1,
            (p.span.start_line as i128 + p.span.end_line as i128 - width as i128 + 1) / 2,
        ];
        for start in starts {
            let start = start
                .min((bounds.end_line - width + 1) as i128)
                .max(bounds.start_line as i128) as usize;
            let span = Span::new(start, start + width - 1)?;
            if proposals.iter().all(|p| p.span != span) {
                proposals.push(with_window(p, lines, span)?);
            }
        }
    }
    let mut measured: Vec<_> = proposals
        .into_iter()
        .map(|p| {
            let score = utility(owner, std::slice::from_ref(&p));
            (p, score)
        })
        .collect();
    measured.sort_by(|(a, x), (b, y)| {
        y.total_cmp(x)
            .then_with(|| a.span.start_line.cmp(&b.span.start_line))
    });
    Ok(measured.into_iter().take(limit).map(|(p, _)| p).collect())
}
pub(crate) fn combinations(n: usize, count: usize) -> Vec<Vec<usize>> {
    fn visit(
        n: usize,
        count: usize,
        start: usize,
        current: &mut Vec<usize>,
        output: &mut Vec<Vec<usize>>,
    ) {
        if current.len() == count {
            output.push(current.clone());
            return;
        }
        let remaining = count - current.len();
        if remaining > n.saturating_sub(start) {
            return;
        }
        for i in start..=n - remaining {
            current.push(i);
            visit(n, count, i + 1, current, output);
            current.pop();
        }
    }
    let mut output = Vec::new();
    visit(n, count, 0, &mut Vec::new(), &mut output);
    output
}
fn spans(bundle: &[Passage]) -> Vec<Span> {
    bundle.iter().map(|p| p.span).collect()
}
fn bundles(
    owner: &CodeMatch,
    lines: &[String],
    purpose: &str,
    limit: usize,
    max_fragments: usize,
) -> Result<Vec<Vec<Passage>>> {
    let singles = windows(owner, lines, purpose, limit)?;
    let mut proposals: Vec<_> = singles.iter().map(|p| vec![p.clone()]).collect();
    let mut strongest = distinct_passages(owner);
    strongest.sort_by(|a, b| {
        b.signals
            .get("joint_evidence")
            .copied()
            .unwrap_or(0.)
            .total_cmp(&a.signals.get("joint_evidence").copied().unwrap_or(0.))
            .then_with(|| a.span.start_line.cmp(&b.span.start_line))
    });
    strongest.truncate(4);
    for count in 2..=max_fragments.min(strongest.len()) {
        for indexes in combinations(strongest.len(), count) {
            let mut fragments = Vec::new();
            for (index, i) in indexes.into_iter().enumerate() {
                let p = strongest[i];
                let bounds = source_bounds(owner, p, lines.len(), purpose != "documentation")?;
                let width = (MAX_EVIDENCE_LINES / count
                    + usize::from(index < MAX_EVIDENCE_LINES % count))
                .min(bounds.end_line - bounds.start_line + 1);
                let center = (p.span.start_line + p.span.end_line) / 2;
                let start = (center as i128 - (width / 2) as i128)
                    .min((bounds.end_line - width + 1) as i128)
                    .max(bounds.start_line as i128) as usize;
                fragments.push(with_window(p, lines, Span::new(start, start + width - 1)?)?);
            }
            fragments.sort_by_key(|p| p.span.start_line);
            if fragments
                .windows(2)
                .any(|p| p[0].span.end_line >= p[1].span.start_line)
            {
                continue;
            }
            if proposals.iter().all(|p| spans(p) != spans(&fragments)) {
                proposals.push(fragments);
            }
        }
    }
    let mut ordered: Vec<_> = proposals
        .into_iter()
        .map(|p| {
            let score = utility(owner, &p);
            (p, score)
        })
        .collect();
    ordered.sort_by(|(a, x), (b, y)| {
        y.total_cmp(x)
            .then_with(|| a.len().cmp(&b.len()))
            .then_with(|| spans(a).cmp(&spans(b)))
    });
    let mut result: Vec<_> = singles
        .into_iter()
        .take(2.min(limit))
        .map(|p| vec![p])
        .collect();
    for (bundle, _) in ordered {
        if !result.contains(&bundle) {
            result.push(bundle);
        }
    }
    result.truncate(limit);
    Ok(result)
}
pub fn refine_evidence(
    matches: &[CodeMatch],
    source: &SourceAuthority,
    request: &SearchRequest,
    judge: &dyn RelevanceJudge,
    options: &EvidenceOptions,
) -> Result<Vec<CodeMatch>> {
    if options.limit <= 0 || options.max_windows <= 0 || !(1..=4).contains(&options.max_fragments) {
        return Err(invalid_evidence(
            "positive evidence selection budgets required",
        ));
    }
    let intent = interpret(request);
    let mut result = matches.to_vec();
    if intent.identity {
        return Ok(result);
    }
    for (index, owner) in matches.iter().take(options.limit as usize).enumerate() {
        if owner.signals.get("exact").is_some_and(|v| *v != 0.) {
            continue;
        }
        let Ok(lines) = verified_lines(source, owner) else {
            continue;
        };
        let bundles = bundles(
            owner,
            &lines,
            &intent.purpose,
            options.max_windows as usize,
            options.max_fragments as usize,
        )?;
        if bundles.is_empty() {
            continue;
        }
        let documents = bundles
            .iter()
            .map(|bundle| {
                candidate_document(
                    &Candidate {
                        entity: owner.entity.clone(),
                        passages: bundle.clone(),
                        signals: Default::default(),
                        owned_regions: Vec::new(),
                    },
                    &intent.purpose,
                )
            })
            .collect::<Result<Vec<_>>>()?;
        let scores = judge.score(request.query(), &documents, &intent.purpose)?;
        if scores.len() != bundles.len() || scores.iter().any(|s| !s.is_finite()) {
            return Err(invalid_evidence(
                "evidence selector must return one finite score per source window",
            ));
        }
        let mut best = 0;
        for i in 1..scores.len() {
            if scores[i] > scores[best]
                || (scores[i] == scores[best] && bundles[i].len() < bundles[best].len())
            {
                best = i;
            }
        }
        let mut evidence = bundles[best].clone();
        for p in &mut evidence {
            p.signals.insert("selected_window".into(), 1.);
            p.signals.insert("window_relevance".into(), scores[best]);
        }
        result[index].evidence = evidence;
        result[index]
            .signals
            .insert("window_relevance".into(), scores[best]);
    }
    Ok(result)
}
