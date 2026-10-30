//! Independent evidence kinds share one explicit, uncalibrated confidence rule.
use crate::{Confidence, Evidence, Inquiry, Reasoner, Result, Symbol, rounded, text};
use std::collections::BTreeSet;
use unicode_normalization::{UnicodeNormalization, char::canonical_combining_class};
pub fn terms(value: &str) -> BTreeSet<String> {
    let mut separated = String::new();
    let mut previous = None;
    for c in value.chars() {
        if previous.is_some_and(|p: char| p.is_ascii_lowercase()) && c.is_ascii_uppercase() {
            separated.push(' ');
        }
        separated.push(c);
        previous = Some(c);
    }
    let normalized = separated
        .to_lowercase()
        .nfkd()
        .filter(|c| canonical_combining_class(*c) == 0)
        .collect::<String>();
    const STOP: &str = "who what which where how does do is are the a an of to for and in that this method function class code responsible handles responsible for quien quienes que cual cuales donde como el la los las un una de del para por y en se encarga metodo funcion clase codigo hace tal cosa hace";
    normalized
        .split(|c: char| !c.is_ascii_lowercase() && !c.is_ascii_digit())
        .filter(|w| w.len() > 1 && !STOP.split_whitespace().any(|s| s == *w))
        .map(|w| {
            if w.len() > 3 && w.ends_with('s') && !w.ends_with("ss") {
                w[..w.len() - 1].to_owned()
            } else {
                w.to_owned()
            }
        })
        .collect()
}
pub fn overlap(query: &BTreeSet<String>, value: &str) -> f64 {
    if query.is_empty() {
        0.
    } else {
        query.intersection(&terms(value)).count() as f64 / query.len() as f64
    }
}
fn evidence(
    reasoner: &str,
    direction: &str,
    strength: f64,
    explanation: impl Into<ken_text::PythonText>,
    assumption: &str,
) -> Evidence {
    Evidence {
        reasoner: reasoner.into(),
        direction: direction.into(),
        strength,
        explanation: explanation.into(),
        assumption: assumption.into(),
    }
}
fn guard(pattern: &str, clause: &ken_text::PythonText) -> Result<bool> {
    use ken_query::execution::regex_runtime::{Dialect, Pattern};
    let mut check = || Ok(());
    let p = Pattern::compile(pattern, "i", Dialect::Stdlib, &mut check)
        .map_err(|e| crate::invalid(e.to_string()))?;
    p.is_match(clause, &mut check)
        .map_err(|e| crate::invalid(e.to_string()))
}
pub struct DocumentationReasoner;
impl Reasoner for DocumentationReasoner {
    fn assess(&self, inquiry: &Inquiry, symbol: &Symbol) -> Result<Vec<Evidence>> {
        if symbol.documentation.is_empty() {
            return Ok(vec![]);
        }
        let lexical = overlap(&inquiry.terms, &text::scalar(&symbol.documentation));
        let score = inquiry.similarity.clamp(0., 1.);
        let mut out = vec![evidence(
            "documentation",
            "supports",
            score.max(0.85 * lexical),
            format!(
                "Documentation similarity {score:.3}; term coverage {lexical:.3} (correlated signals, combined by max)."
            ),
            "The documentation accurately describes this symbol's current behavior.",
        )];
        for clause in text::clauses(&symbol.documentation) {
            if let Some(tail) = text::denial_tail(&clause)
                && overlap(&inquiry.terms, &text::scalar(&tail)) >= 0.5
            {
                out.push(evidence(
                    "documentation_guard",
                    "against",
                    0.9,
                    text::prepend(
                        "Possible explicit denial: ",
                        &text::prefix(&clause.clone().trimmed(), 240),
                    ),
                    "",
                ));
            }
            if guard(r"\b(?:may|might|could|would|if|podría|puede|si)\b", &clause)?
                && overlap(&inquiry.terms, &text::scalar(&clause)) >= 0.5
            {
                out.push(evidence(
                    "documentation_guard",
                    "context",
                    0.5,
                    text::prepend(
                        "Conditional documentation: ",
                        &text::prefix(&clause.clone().trimmed(), 240),
                    ),
                    "The documented condition must hold; it has not been established.",
                ));
            }
            if guard(r"\b(?:delegat\w*|forward\w*|delega\w*)\b", &clause)?
                && overlap(&inquiry.terms, &text::scalar(&clause)) >= 0.5
            {
                out.push(evidence(
                    "delegation",
                    "context",
                    0.5,
                    text::prepend(
                        "Documentation describes delegation: ",
                        &text::prefix(&clause.trimmed(), 240),
                    ),
                    "Coordinating or delegating an operation does not establish who implements it.",
                ));
            }
        }
        Ok(out)
    }
}
pub struct NameReasoner;
impl Reasoner for NameReasoner {
    fn assess(&self, inquiry: &Inquiry, symbol: &Symbol) -> Result<Vec<Evidence>> {
        let strength = overlap(&inquiry.terms, &symbol.qualname);
        Ok(if strength > 0. {
            vec![evidence(
                "name",
                "supports",
                strength,
                "The symbol name shares responsibility terms.",
                "The name reflects behavior; a name alone does not prove it.",
            )]
        } else {
            vec![]
        })
    }
}
pub struct CallsReasoner;
impl Reasoner for CallsReasoner {
    fn assess(&self, inquiry: &Inquiry, symbol: &Symbol) -> Result<Vec<Evidence>> {
        let sites = symbol
            .calls
            .iter()
            .filter(|(name, _)| overlap(&inquiry.terms, name) >= 0.5)
            .take(4)
            .map(|(name, line)| format!("{name}:{line}"))
            .collect::<Vec<_>>();
        Ok(if sites.is_empty() {
            vec![]
        } else {
            vec![evidence(
                "calls",
                "context",
                0.4,
                format!(
                    "Contains call expressions related by name: {}",
                    sites.join(", ")
                ),
                "Call targets and runtime execution are unresolved; this may be an orchestrator.",
            )]
        })
    }
}
pub fn default_reasoners() -> Vec<Box<dyn Reasoner>> {
    vec![
        Box::new(DocumentationReasoner),
        Box::new(NameReasoner),
        Box::new(CallsReasoner),
    ]
}
pub fn confidence(evidence: &[Evidence]) -> Confidence {
    let strongest = |name: &str| {
        evidence
            .iter()
            .filter(|e| e.reasoner == name && e.direction == "supports")
            .map(|e| e.strength)
            .reduce(f64::max)
            .unwrap_or(0.)
    };
    let doc = strongest("documentation");
    let name = strongest("name");
    let additional = evidence
        .iter()
        .filter(|e| {
            e.direction == "supports" && !["documentation", "name"].contains(&e.reasoner.as_str())
        })
        .map(|e| e.strength)
        .reduce(f64::max)
        .unwrap_or(0.);
    let mut score = doc.max(0.65 * name).max(0.5 * additional) + 0.05 * doc.min(name);
    if evidence.iter().any(|e| e.direction == "against") {
        score = score.min(0.2);
    } else if evidence
        .iter()
        .any(|e| ["documentation_guard", "delegation"].contains(&e.reasoner.as_str()))
    {
        score = score.min(0.55);
    }
    let score = rounded(score.min(0.95), 3);
    Confidence {
        score,
        band: if score >= 0.7 {
            "strong"
        } else if score >= 0.5 {
            "moderate"
        } else {
            "weak"
        }
        .into(),
        calibrated: false,
        probability: None,
        policy: "responsibility-evidence/1".into(),
    }
}
