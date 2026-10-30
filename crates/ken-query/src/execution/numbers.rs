//! Python float coercion is separate from asymmetric equality string spelling.
use super::{ExecutionError, Result};
use ken_program::value::GraphValue;
pub(super) fn actual(value: &GraphValue) -> Result<Option<f64>> {
    Ok(match value {
        GraphValue::Bool(v) => Some(if *v { 1. } else { 0. }),
        GraphValue::Float(v) => Some(*v),
        GraphValue::Int(v) => {
            let n = v.parse::<f64>().ok();
            if n.is_some_and(|n| !n.is_finite()) {
                return Err(ExecutionError::Invalid(
                    "numeric conversion overflow".into(),
                ));
            }
            n
        }
        GraphValue::String(v) => v.to_utf8().and_then(|v| parse(&v)),
        _ => None,
    })
}
pub(super) fn parse(text: &str) -> Option<f64> {
    static ZEROES: std::sync::OnceLock<Vec<u32>> = std::sync::OnceLock::new();
    let zeroes = ZEROES.get_or_init(|| {
        serde_json::from_str(include_str!("../../resources/float-decimal-zeroes.json"))
            .expect("frozen Unicode15 decimal digits")
    });
    let chars: Vec<_> = text
        .trim()
        .chars()
        .map(|c| {
            let n = c as u32;
            let i = zeroes.partition_point(|z| *z <= n);
            if i > 0 && n - zeroes[i - 1] < 10 {
                (b'0' + (n - zeroes[i - 1]) as u8) as char
            } else {
                c
            }
        })
        .collect();
    let mut normalized = String::with_capacity(text.len());
    for (i, c) in chars.iter().enumerate() {
        if *c == '_' {
            if i == 0
                || i + 1 == chars.len()
                || !chars[i - 1].is_ascii_digit()
                || !chars[i + 1].is_ascii_digit()
            {
                return None;
            }
        } else {
            normalized.push(*c);
        }
    }
    normalized.parse().ok()
}
