//! Stable explicit evidence preferences, independently of neural score production.
use crate::{
    EntityKey, Result, RetrievalError,
    source_catalog::SourceCatalog,
    source_snapshot::SourceResult,
    symbol_requirements::{SymbolRequirements, WORDS},
    text_patterns as p,
};
use ken_text::PythonText;
use std::collections::BTreeSet;
pub fn is_test_case(key: &EntityKey, catalog: &SourceCatalog) -> SourceResult<bool> {
    if !matches!(key.kind.as_str(), "function" | "method") {
        return Ok(false);
    }
    let Some((_, passages)) = catalog.owners().iter().find(|(owner, _)| owner == key) else {
        return Ok(false);
    };
    if passages[0].role != "test" || catalog.enclosing_callable(key)?.is_some() {
        return Ok(false);
    }
    let name = key
        .qualname
        .as_deref()
        .unwrap_or("")
        .rsplit('.')
        .next()
        .unwrap_or("");
    if key.path.ends_with(".py") || key.path.ends_with(".pyi") {
        return Ok(name.starts_with("test"));
    }
    if key.path.ends_with(".java") {
        let [start, end] = catalog.extent(key)?;
        let lines = catalog.snapshots()[&key.path].lines();
        let prefix = lines[start - 1..end.min(start + 11)].join("\n");
        let declaration = prefix.split('{').next().unwrap_or("");
        return Ok(p::has(
            r"(?m)^\s*@(?:[\w]+\.)*(?:Test|RepeatedTest|ParameterizedTest|TestFactory|TestTemplate)\b",
            false,
            &declaration.into(),
        ));
    }
    Ok(false)
}
pub fn apply_symbol_preferences(
    required: &SymbolRequirements,
    witnesses: &[BTreeSet<String>],
    test_cases: &[bool],
    implementations: &[PythonText],
    order: &[usize],
) -> Result<Vec<usize>> {
    let count = implementations.len();
    let mut membership = order.to_vec();
    membership.sort_unstable();
    if witnesses.len() != count
        || test_cases.len() != count
        || membership != (0..count).collect::<Vec<_>>()
    {
        return Err(RetrievalError::Invalid(
            "one observation per candidate and complete permutation required".into(),
        ));
    }
    let mut result = order.to_vec();
    if !required.operations.is_empty() {
        result.sort_by_key(|&i| {
            !required.operations.iter().all(|item| {
                if item == "cause:*" {
                    witnesses[i].iter().any(|value| value.starts_with("cause:"))
                } else {
                    witnesses[i].contains(item)
                }
            })
        });
    }
    if required.test_case {
        result.sort_by_key(|&i| !test_cases[i]);
    }
    if !required.operators.is_empty() {
        let present = implementations
            .iter()
            .map(|text| {
                let mut words = p::captures(WORDS, false, text)
                    .into_iter()
                    .map(|c| c.whole.to_utf8().expect("ASCII token").to_ascii_lowercase())
                    .collect::<BTreeSet<_>>();
                if p::has("&&", false, text) {
                    words.insert("and".into());
                }
                if p::has(r"\|\|", false, text) {
                    words.insert("or".into());
                }
                words
            })
            .collect::<Vec<_>>();
        result.sort_by_key(|&i| !required.operators.is_subset(&present[i]));
    }
    Ok(result)
}
