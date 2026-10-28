//! Display verified evidence without reading source or changing search results.
use crate::{
    presentation::{SearchResponse, SearchResult},
    rank_json,
};
use serde_json::Value;

fn diagnostic_json(value: &Value) -> String {
    match value {
        Value::String(text) => rank_json::quote(&text.as_str().into()),
        Value::Number(number) if number.is_f64() => {
            rank_json::float(number.as_f64().expect("JSON float"))
        }
        Value::Array(items) => format!(
            "[{}]",
            items
                .iter()
                .map(diagnostic_json)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(items) => {
            let mut entries: Vec<_> = items.iter().collect();
            entries.sort_by(|(a, _), (b, _)| a.cmp(b));
            format!(
                "{{{}}}",
                entries
                    .into_iter()
                    .map(|(key, value)| {
                        format!(
                            "{}: {}",
                            rank_json::quote(&key.as_str().into()),
                            diagnostic_json(value)
                        )
                    })
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
        _ => value.to_string(),
    }
}

fn has_signals(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|v| v != 0.),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

pub fn render(response: &SearchResponse, diagnostics: bool) -> String {
    let mut blocks = Vec::new();
    for result in &response.results {
        let source = result.source();
        let mut title = source.path.clone();
        if let Some(first) = source.evidence.first() {
            title.push_str(&format!(":{}-{}", first.start_line, first.end_line));
        }
        if let Some(name) = source.entity.qualname.as_deref().filter(|n| !n.is_empty()) {
            title.push_str(" :: ");
            title.push_str(name);
        }
        if let SearchResult::Piece(piece) = result
            && matches!(piece.piece_kind.as_str(), "class" | "module" | "file")
        {
            title.push_str(&format!(" ({})", piece.piece_kind));
        }
        if source.stale {
            title.push_str(" [stale]");
        } else if source.truncated {
            title.push_str(" [partial]");
        }
        let mut parts = vec![title];
        for (index, fragment) in source.evidence.iter().enumerate() {
            if index != 0 {
                parts.push(format!("@{}-{}", fragment.start_line, fragment.end_line));
            }
            for (offset, line) in fragment.content.split('\n').enumerate() {
                parts.push(format!("{} | {line}", fragment.start_line + offset));
            }
        }
        if diagnostics {
            let signals = match result {
                SearchResult::Owner(owner) => owner
                    .signals
                    .as_ref()
                    .map(|s| serde_json::to_value(s).expect("serializable numeric search signals")),
                SearchResult::Piece(piece) => piece.signals.clone(),
            };
            if let Some(signals) = signals.filter(has_signals) {
                parts.push(format!("signals: {}", diagnostic_json(&signals)));
            }
        }
        blocks.push(parts.join("\n"));
    }
    if blocks.is_empty() {
        blocks.push("No matches.".into());
    }
    if response.omitted_count != 0 {
        blocks.push(format!("{} more results omitted.", response.omitted_count));
    }
    blocks.extend(response.warnings.iter().cloned());
    blocks.join("\n\n")
}
