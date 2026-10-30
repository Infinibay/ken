//! The same ordered production stages feed ranking and explanation.
use crate::{
    model::{sort_findings, sort_items},
    text, *,
};
use rusqlite::Connection;
use std::collections::BTreeMap;
#[derive(Default)]
struct Trace {
    channels: BTreeMap<String, Vec<RankedItem>>,
    findings: Vec<FindingItem>,
    stages: Vec<(&'static str, RankResult)>,
    gate: f64,
    suppressed: bool,
}
fn capture(
    trace: &mut Option<Trace>,
    name: &'static str,
    files: &[RankedItem],
    symbols: &[RankedItem],
) {
    if let Some(trace) = trace {
        trace.stages.push((
            name,
            RankResult {
                files: files.to_vec(),
                symbols: symbols.to_vec(),
                findings: Vec::new(),
            },
        ));
    }
}
fn run(
    conn: &Connection,
    request: &RankRequest,
    policy: &Policy,
    numerics: &mut dyn ContextNumerics,
    explain: bool,
) -> Result<(RankResult, Option<Trace>)> {
    let mut trace = explain.then(Trace::default);
    let prompt = text::matching(&request.prompt);
    let root = request.project_root.as_deref();
    let similar = channels::similar_past_sessions(
        conn,
        &request.prompt_embedding,
        &request.agent_id,
        &request.clock,
        numerics,
    )?;
    let (explicit_files, explicit_symbols) = channels::explicit_mentions(conn, &request.prompt)?;
    let reactive = if request.include_reactive {
        channels::reactive_scores(conn, &request.agent_id, request.current_iteration)?
    } else {
        Vec::new()
    };
    let predictive = channels::predictive_scores(conn, &similar, policy)?;
    let (fuzzy_files, fuzzy_symbols) = channels::fuzzy_scores(
        conn,
        &request.prompt_embedding,
        root,
        &request.clock,
        policy,
        numerics,
    )?;
    let (doc_files, doc_symbols) =
        channels::doc_intent_scores(conn, &request.prompt_embedding, root, policy, numerics)?;
    let literal = channels::literal_content_scores(conn, &request.prompt, root)?;
    let (lexical_files, lexical_symbols) =
        channels::lexical_scores(conn, &request.prompt, Some(&request.agent_id), root)?;
    let mut findings = channels::finding_scores(conn, &request.prompt_embedding, numerics)?;
    if let Some(trace) = &mut trace {
        for (name, items) in [
            ("explicit_files", &explicit_files),
            ("explicit_symbols", &explicit_symbols),
            ("reactive", &reactive),
            ("predictive", &predictive),
            ("fuzzy_files", &fuzzy_files),
            ("fuzzy_symbols", &fuzzy_symbols),
            ("doc_intent_files", &doc_files),
            ("doc_intent_symbols", &doc_symbols),
            ("literal_files", &literal),
            ("lexical_files", &lexical_files),
            ("lexical_symbols", &lexical_symbols),
        ] {
            trace.channels.insert(name.into(), items.clone());
        }
        trace.findings = findings.clone();
    }
    let mut symbols = merge::symbols(
        explicit_symbols
            .into_iter()
            .chain(fuzzy_symbols)
            .chain(doc_symbols)
            .chain(lexical_symbols),
    );
    let mut files = merge::files(
        &[
            explicit_files,
            reactive,
            predictive,
            fuzzy_files,
            doc_files,
            literal,
            lexical_files,
        ],
        policy,
    );
    capture(&mut trace, "merge", &files, &symbols);
    boosts::symbol_file_affinity(conn, &mut files, &symbols)?;
    capture(&mut trace, "symbol_file_affinity", &files, &symbols);
    boosts::freshness(conn, &mut files, &request.clock)?;
    capture(&mut trace, "freshness", &files, &symbols);
    if policy.ppr != PprMode::Replace {
        boosts::cooc(conn, &mut files, &request.clock, policy)?;
    }
    capture(&mut trace, "cooc", &files, &symbols);
    if policy.ppr != PprMode::Replace {
        boosts::test_affinity(conn, &mut files)?;
    }
    capture(&mut trace, "test_affinity", &files, &symbols);
    if policy.ppr != PprMode::Replace {
        boosts::import_affinity(conn, &mut files)?;
    }
    capture(&mut trace, "import_affinity", &files, &symbols);
    if policy.ppr != PprMode::Off {
        ppr::apply(conn, &mut files, policy)?;
    }
    capture(&mut trace, "ppr", &files, &symbols);
    boosts::dismissal(conn, &mut files, &similar)?;
    capture(&mut trace, "dismissal", &files, &symbols);
    boosts::implementation(&mut files, &prompt);
    capture(&mut trace, "implementation_intent", &files, &symbols);
    boosts::documentation(&mut files, &prompt);
    capture(&mut trace, "documentation_intent", &files, &symbols);
    boosts::language(&mut files, &mut symbols, &prompt);
    capture(&mut trace, "language_intent", &files, &symbols);
    if let Some(root) = root {
        files.retain(|it| it.target.to_utf8().is_some_and(|p| root.join(p).exists()));
        symbols.retain(|it| {
            it.target.to_utf8().is_some_and(|target| {
                boosts::symbol_path(&target).is_some_and(|p| root.join(p).exists())
            })
        });
    }
    sort_items(&mut files);
    sort_items(&mut symbols);
    sort_findings(&mut findings);
    let result = RankResult {
        files: files[..prefix(files.len(), request.top_files)].to_vec(),
        symbols: symbols[..prefix(symbols.len(), request.top_symbols)].to_vec(),
        findings: findings[..prefix(findings.len(), request.top_findings)].to_vec(),
    };
    let gate = if policy.fusion == FusionMode::LogOdds {
        policy.fusion_gate
    } else {
        1.5
    };
    let suppressed = result.top_score() < gate;
    if let Some(trace) = &mut trace {
        trace.gate = gate;
        trace.suppressed = suppressed;
    }
    capture(&mut trace, "before_gate", &files, &symbols);
    Ok((
        if suppressed {
            RankResult::default()
        } else {
            result
        },
        trace,
    ))
}
pub fn rank(
    conn: &Connection,
    request: &RankRequest,
    policy: &Policy,
    numerics: &mut dyn ContextNumerics,
) -> Result<RankResult> {
    Ok(run(conn, request, policy, numerics, false)?.0)
}
fn items(items: &[RankedItem], top: i64) -> Vec<ExplanationItem> {
    let mut items = items.to_vec();
    sort_items(&mut items);
    items.truncate(prefix(items.len(), top));
    items
        .into_iter()
        .map(|i| ExplanationItem {
            target: Some(i.target),
            topic: None,
            score: rounded(i.score, 3),
            reason: i.reason,
            tags: None,
        })
        .collect()
}
fn findings(items: &[FindingItem], top: i64) -> Vec<ExplanationItem> {
    let mut items = items.to_vec();
    sort_findings(&mut items);
    items.truncate(prefix(items.len(), top));
    items
        .into_iter()
        .map(|i| ExplanationItem {
            target: None,
            topic: Some(i.topic),
            score: rounded(i.score, 3),
            reason: i.reason,
            tags: Some(i.tags),
        })
        .collect()
}
fn diff(before: &[RankedItem], after: &[RankedItem]) -> Vec<Change> {
    let a = before
        .iter()
        .map(|i| (i.target.codepoints().to_vec(), i))
        .collect::<BTreeMap<_, _>>();
    let b = after
        .iter()
        .map(|i| (i.target.codepoints().to_vec(), i))
        .collect::<BTreeMap<_, _>>();
    let keys = a
        .keys()
        .chain(b.keys())
        .collect::<std::collections::BTreeSet<_>>();
    let mut changes = Vec::new();
    for key in keys {
        let before = a.get(key).map(|i| i.score);
        let after = b.get(key).map(|i| i.score);
        if before == after {
            continue;
        }
        let target = b.get(key).or_else(|| a.get(key)).unwrap().target.clone();
        changes.push(Change {
            target,
            before: before.map(|v| rounded(v, 3)),
            after: after.map(|v| rounded(v, 3)),
            delta: before.zip(after).map(|(b, a)| rounded(a - b, 3)),
        });
    }
    changes.sort_by(|a, b| {
        b.delta
            .unwrap_or(0.)
            .abs()
            .partial_cmp(&a.delta.unwrap_or(0.).abs())
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    changes
}
pub fn explain(
    conn: &Connection,
    request: &RankRequest,
    policy: &Policy,
    numerics: &mut dyn ContextNumerics,
    top: i64,
) -> Result<Explanation> {
    let mut request = request.clone();
    request.top_files = top;
    request.top_symbols = top;
    request.top_findings = top;
    let (result, trace) = run(conn, &request, policy, numerics, true)?;
    let trace = trace.expect("requested production trace");
    let mut channels = trace
        .channels
        .into_iter()
        .map(|(name, value)| (name, items(&value, top)))
        .collect::<BTreeMap<_, _>>();
    channels.insert("findings".into(), findings(&trace.findings, top));
    let merge = &trace.stages[0].1;
    let mut boosts = BTreeMap::new();
    let mut before = merge;
    for (name, stage) in &trace.stages[1..] {
        if *name == "before_gate" {
            continue;
        }
        boosts.insert((*name).into(), diff(&before.files, &stage.files));
        if *name == "language_intent" {
            boosts.insert(
                "language_symbol_intent".into(),
                diff(&before.symbols, &stage.symbols),
            );
        }
        before = stage;
    }
    let mut scores = merge
        .files
        .iter()
        .map(|it| Score {
            target: it.target.clone(),
            score: it.score,
        })
        .collect::<Vec<_>>();
    scores.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    scores.truncate(prefix(scores.len(), top));
    for score in &mut scores {
        score.score = rounded(score.score, 3);
    }
    Ok(Explanation {
        prompt: request.prompt,
        channels,
        merge_before_boosts: scores,
        boosts,
        confidence_gate: ConfidenceGate {
            threshold: trace.gate,
            suppressed: trace.suppressed,
        },
        candidates_before_gate: items(&trace.stages.last().unwrap().1.files, top),
        final_files: items(&result.files, top),
        final_symbols: items(&result.symbols, top),
        final_findings: findings(&result.findings, top),
    })
}
