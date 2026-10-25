//! Interpret explicit symbol evidence requests without observing source bodies.
use crate::{intent, query::SearchRequest, text_patterns as p};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolRequirements {
    pub operations: BTreeSet<String>,
    pub operators: BTreeSet<String>,
    pub test_case: bool,
}
pub fn requested_operations(query: &PythonText) -> BTreeSet<String> {
    let lower = p::fold(query);
    let mut required = BTreeSet::new();
    for action in p::captures(
        r"\b(?:invokes?|invoking)\s+(?!no\b|nothing\b)\S",
        false,
        &lower,
    ) {
        if !p::has(
            r"\b(?:not|never|without|cannot|can't|doesn't|don't|avoid\w*|prevent\w*)\b[^.;!?]*$",
            false,
            &p::slice(&lower, 0, action.start),
        ) {
            required.insert("invocation".into());
        }
    }
    if p::has(r"\b(?:retain\w*|preserv\w*|keep\w*)\b", false, &lower)
        && p::has(r"\bexception\b", false, &lower)
        && p::has(r"\bcause\b", false, &lower)
        && !p::has(
            r"\b(?:not|without|suppress\w*)\b[^.;]{0,60}\bcause\b",
            false,
            &lower,
        )
    {
        required.insert(
            if p::has(r"\battribute[\s-]+error\b", false, &lower) {
                "cause:AttributeError"
            } else {
                "cause:*"
            }
            .into(),
        );
    }
    if p::has(r"\b(?:mapping|dictionary)\b", false, &lower)
        && p::has(r"\bkey\b", false, &lower)
        && p::has(r"\b(?:assign\w*|writ\w*|set\w*)\b", false, &lower)
        && p::has(
            r"\b(?:remember\w*|previous|old|undo|absent)\b",
            false,
            &lower,
        )
        && !p::has(
            r"\b(?:without|never|not)\s+(?:assign\w*|writ\w*|set\w*)\b",
            false,
            &lower,
        )
    {
        required.insert("snapshot_keyed_write".into());
    }
    if p::has(r"\breturn\w*\b", false, &lower)
        && p::has(r"\b(?:flag|boolean|state)\b", false, &lower)
        && p::has(r"\bor\b", false, &lower)
        && p::has(r"\b(?:updat\w*|refresh\w*|assign\w*)\b", false, &lower)
        && !p::has(
            r"\b(?:without|never|not)\s+(?:updat\w*|refresh\w*|assign\w*)\b",
            false,
            &lower,
        )
    {
        required.insert("returned_flag_refresh".into());
    }
    required
}
pub(crate) const WORDS: &str = r"[A-Za-z_][A-Za-z_0-9]*";
pub fn explicit_code_terms(query: &PythonText) -> BTreeSet<String> {
    let mut words = BTreeSet::new();
    for token in p::captures(WORDS, false, query) {
        let token = token.whole.to_utf8().expect("ASCII token");
        if token.bytes().any(|c| c.is_ascii_uppercase())
            && !token.bytes().any(|c| c.is_ascii_lowercase())
        {
            words.insert(token.to_ascii_lowercase());
        }
    }
    for token in p::captures(r"`([A-Za-z]+)`", false, query) {
        words.insert(
            token.groups[1]
                .as_ref()
                .expect("operator capture")
                .to_utf8()
                .expect("ASCII token")
                .to_ascii_lowercase(),
        );
    }
    let bitwise = p::has(r"\bbit[\s-]?wise\b", true, query);
    words.retain(|word| {
        matches!(word.as_str(), "and" | "or" | "not" | "in" | "is")
            && !(bitwise && matches!(word.as_str(), "and" | "or" | "not"))
    });
    words
}
pub fn requests_test_case(request: &SearchRequest) -> bool {
    if intent::interpret(request).purpose != "tests" {
        return false;
    }
    let lower = p::fold(request.query()).trimmed();
    let subject = if let Some(m) = p::find(r"^where\s+(?:does|do|is|are)\s+", false, &lower) {
        let mut points = "find ".chars().map(u32::from).collect::<Vec<_>>();
        points.extend_from_slice(p::tail(&lower, m.end).codepoints());
        p::text(&points)
    } else {
        lower.clone()
    };
    if p::has(
        r"\b[\w]+-double\s+(?:factory|helper|fixture|builder)\b",
        false,
        &subject,
    ) {
        return false;
    }
    if let Some(m) = p::find(intent::TEST_OBJECT, false, &subject) {
        return !p::has(
            r"^\s+(?:helpers?|fixtures?|factor(?:y|ies)|builders?|utilit(?:y|ies))\b",
            false,
            &p::tail(&subject, m.end),
        );
    }
    p::has(r"^where\s+(?:is|are)\b", false, &lower) && p::has(r"\btested\b", false, &lower)
}
pub fn requirements(request: &SearchRequest) -> SymbolRequirements {
    SymbolRequirements {
        operations: requested_operations(request.query()),
        operators: explicit_code_terms(request.query()),
        test_case: requests_test_case(request),
    }
}
