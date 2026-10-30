use crate::{
    Candidate, Evidence, Inquiry, Reasoner, Result, SourceEvidence, Symbol, WhoReport, WhoRequest,
    invalid, reasoners, text,
};
use serde_json::{Value, json};
pub fn assess_symbol(
    symbol: &Symbol,
    formulations: &[String],
    similarities: &[f64],
    reasoners: &[Box<dyn Reasoner>],
) -> Result<Candidate> {
    if formulations.is_empty() || similarities.len() != formulations.len() {
        return Err(invalid("responsibility formulations and scores must align"));
    }
    let mut alternatives = Vec::new();
    for (wording, similarity) in formulations.iter().zip(similarities) {
        let inquiry = Inquiry {
            wording: wording.clone(),
            terms: reasoners::terms(wording),
            similarity: *similarity,
        };
        let mut evidence = Vec::new();
        for reasoner in reasoners {
            evidence.extend(reasoner.assess(&inquiry, symbol)?);
        }
        alternatives.push((reasoners::confidence(&evidence), wording, evidence));
    }
    let mut best = 0;
    for i in 1..alternatives.len() {
        if alternatives[i].0.score > alternatives[best].0.score {
            best = i;
        }
    }
    let wording = alternatives[best].1.clone();
    let mut evidence = alternatives[best].2.clone();
    for (_, _, items) in &alternatives {
        for item in items {
            if (item.direction == "against"
                || ["documentation_guard", "delegation"].contains(&item.reasoner.as_str()))
                && !evidence.contains(item)
            {
                evidence.push(item.clone());
            }
        }
    }
    // Deduplicate repeated contributions without giving call context a vote.
    let mut unique = Vec::new();
    for item in evidence {
        if !unique.contains(&item) {
            unique.push(item);
        }
    }
    let evidence: Vec<Evidence> = unique;
    let rating = reasoners::confidence(&evidence);
    let mut assumptions = Vec::new();
    for item in &evidence {
        if !item.assumption.is_empty() && !assumptions.contains(&item.assumption) {
            assumptions.push(item.assumption.clone());
        }
    }
    if wording != formulations[0] {
        assumptions.insert(
            0,
            format!("This supplied formulation preserves the question's meaning: {wording}").into(),
        );
    }
    let denied = evidence.iter().any(|e| e.direction == "against");
    let mut inspect = json!({"tool":"ken_read","path":symbol.path,"include":["source"]});
    if symbol.kind == "module" {
        inspect["start_line"] = json!(symbol.line);
        inspect["end_line"] = json!(symbol.end_line);
    } else {
        inspect["qualname"] = json!(symbol.qualname);
    }
    Ok(Candidate {
        symbol: symbol.qualname.clone(),
        path: symbol.path.clone(),
        line: symbol.line,
        kind: symbol.kind.clone(),
        status: if denied {
            "counterevidence"
        } else {
            "hypothesis"
        }
        .into(),
        confidence: rating,
        matched_formulation: wording,
        documentation: text::prefix(&symbol.documentation, 900),
        evidence,
        assumptions,
        source: SourceEvidence {
            sha256: symbol.sha256.clone(),
            index_changed: symbol.refreshed,
            documentation_scope: symbol.doc_scope.clone(),
            documentation_kind: format!("{}_docstring", symbol.kind),
            behavior_verified: false,
        },
        inspect,
        end_line: None,
        snippets: None,
        truncated: None,
        preview_unavailable: None,
        structure: None,
    })
}
pub(crate) fn present(
    request: &WhoRequest,
    mut candidates: Vec<Candidate>,
    scope: &str,
    indexed: usize,
    inspected: usize,
    issues: Vec<Value>,
    hypotheses: Vec<String>,
) -> WhoReport {
    candidates.sort_by(|a, b| {
        b.confidence
            .score
            .total_cmp(&a.confidence.score)
            .then_with(|| a.path.cmp(&b.path))
            .then_with(|| a.line.cmp(&b.line))
    });
    let plausible = candidates
        .iter()
        .filter(|c| c.confidence.score >= 0.4 && c.status == "hypothesis")
        .collect::<Vec<_>>();
    let close =
        plausible.len() > 1 && plausible[0].confidence.score - plausible[1].confidence.score < 0.08;
    let selected = plausible
        .into_iter()
        .take(request.limit as usize)
        .cloned()
        .collect::<Vec<_>>();
    let counterevidence = candidates
        .into_iter()
        .filter(|c| c.status == "counterevidence")
        .take(request.limit as usize)
        .collect();
    WhoReport {
        ok: true,
        question: request
            .question
            .trim_matches(ken_text::unicode::whitespace)
            .into(),
        hypotheses,
        status: if close {
            "ambiguous"
        } else if !selected.is_empty() {
            "candidates"
        } else {
            "unknown"
        }
        .into(),
        candidates: selected,
        counterevidence,
        assessment: json!({"kind":"heuristic","calibrated":false,"probability":null,"note":"Scores rank hypotheses; they are not probabilities of correctness. Documentation and call sites do not prove behavior."}),
        coverage: json!({"scope":scope,"indexed_symbols":indexed,"inspected_symbols":inspected,"candidate_limit":40,"exhaustive":false,"include_tests":request.include_tests,"sources":["module_docstrings","class_docstrings","method_docstrings","function_docstrings"],"findings_used":false,"issues":issues,"note":"Index retrieval can miss new symbols or concepts absent from the indexed docstring excerpt. Cross-language quality depends on the configured embedder."}),
        responsibility_map: None,
    }
}
