use serde_json::Value;
pub fn json(value: &Value) -> String {
    match value {
        Value::Array(a) => format!("[{}]", a.iter().map(json).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => {
            let mut keys = m.keys().collect::<Vec<_>>();
            keys.sort();
            format!(
                "{{{}}}",
                keys.into_iter()
                    .map(|k| format!("{}: {}", serde_json::to_string(k).unwrap(), json(&m[k])))
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
        _ => serde_json::to_string(value).unwrap(),
    }
}
pub fn ascii_size(value: &Value) -> usize {
    json(value)
        .chars()
        .map(|c| {
            if c.is_ascii() {
                1
            } else if c as u32 > 0xffff {
                12
            } else {
                6
            }
        })
        .sum()
}
pub fn truth(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(m) => !m.is_empty(),
    }
}
pub fn round(v: f64, digits: i32) -> f64 {
    let f = 10f64.powi(digits);
    (v * f).round_ties_even() / f
}
