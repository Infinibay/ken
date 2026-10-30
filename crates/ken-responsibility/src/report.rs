//! Presentation is an extractive projection after ranking, never a second scorer.
use crate::{Candidate, Snippet, WhoReport, reasoners, text};
use ken_text::PythonText;
use serde::Serialize;
use serde_json::Value;
#[derive(Clone, Serialize)]
pub struct CompactCandidate {
    #[serde(skip_serializing_if = "Option::is_none")]
    symbol: Option<String>,
    kind: String,
    path: String,
    line: usize,
    score: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    end_line: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    snippets: Option<Vec<Snippet>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    truncated: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    preview_unavailable: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    evidence: Option<PythonText>,
    #[serde(skip_serializing_if = "Option::is_none")]
    assumed_formulation: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    caveats: Vec<PythonText>,
    #[serde(skip_serializing_if = "Option::is_none")]
    structure: Option<Value>,
}
#[derive(Clone, Serialize)]
pub struct CompactReport {
    status: String,
    score_kind: &'static str,
    candidates: Vec<CompactCandidate>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    counterevidence: Vec<CompactCandidate>,
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    uninspected_candidates: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    responsibility_map: Option<Value>,
}
#[derive(Clone, Serialize)]
#[serde(untagged)]
pub enum WhoOutput {
    Full(WhoReport),
    Compact(CompactReport),
}
impl WhoOutput {
    pub fn to_json_string(&self) -> crate::Result<String> {
        Ok(serde_json::to_string(self)?)
    }
    pub fn to_json(&self) -> crate::Result<Value> {
        Ok(serde_json::from_str(&self.to_json_string()?)?)
    }
}
fn candidate(candidate: &Candidate, question: &str) -> CompactCandidate {
    let mut evidence = None;
    if !candidate.documentation.is_empty() {
        let query = reasoners::terms(&candidate.matched_formulation);
        let fragments = text::fragments(&candidate.documentation);
        let mut best = None;
        let mut strength = f64::NEG_INFINITY;
        for fragment in fragments {
            let score = reasoners::overlap(&query, &text::scalar(&fragment));
            if score > strength {
                strength = score;
                best = Some(fragment);
            }
        }
        if let Some(quote) = best {
            evidence = Some(if quote.codepoints().len() <= 200 {
                quote
            } else {
                let mut p = text::prefix(&quote, 199).codepoints().to_vec();
                p.push(0x2026);
                PythonText::from_codepoints(p).expect("existing code points")
            });
        }
    } else if let Some(first) = candidate.evidence.first() {
        evidence = Some(first.explanation.clone());
    }
    let mut caveats = Vec::new();
    for item in &candidate.evidence {
        if item.direction != "supports" && !caveats.contains(&item.explanation) {
            caveats.push(item.explanation.clone());
        }
        if !item.assumption.is_empty()
            && (item.direction != "supports"
                || !["documentation", "name"].contains(&item.reasoner.as_str()))
            && !caveats.contains(&item.assumption)
        {
            caveats.push(item.assumption.clone());
        }
    }
    let structure = candidate
        .structure
        .as_ref()
        .filter(|v| v.as_object().is_some_and(|m| !m.is_empty()))
        .map(|v| {
            let mut out = v.clone();
            if let Some(object) = out.as_object_mut() {
                object.remove("observations");
            }
            out
        });
    CompactCandidate {
        symbol: (!(candidate.symbol == candidate.path && candidate.kind == "module"))
            .then(|| candidate.symbol.clone()),
        kind: candidate.kind.clone(),
        path: candidate.path.clone(),
        line: candidate.line,
        score: candidate.confidence.score,
        end_line: candidate.end_line,
        snippets: candidate.snippets.clone(),
        truncated: candidate.truncated,
        preview_unavailable: candidate.preview_unavailable.clone(),
        evidence,
        assumed_formulation: (candidate.matched_formulation != question)
            .then(|| candidate.matched_formulation.clone()),
        caveats,
        structure,
    }
}
pub fn render(result: &WhoReport, full: bool) -> WhoOutput {
    if full {
        return WhoOutput::Full(result.clone());
    }
    let issues = result.coverage["issues"].as_array().map_or(0, Vec::len);
    WhoOutput::Compact(CompactReport {
        status: result.status.clone(),
        score_kind: "heuristic_not_probability",
        candidates: result
            .candidates
            .iter()
            .map(|c| candidate(c, &result.question))
            .collect(),
        counterevidence: result
            .counterevidence
            .iter()
            .map(|c| candidate(c, &result.question))
            .collect(),
        reason: (result.status == "unknown").then_some(
            "Insufficient evidence in the inspected indexed code; not proof of absence.",
        ),
        uninspected_candidates: (issues > 0).then_some(issues),
        responsibility_map: result.responsibility_map.clone(),
    })
}
