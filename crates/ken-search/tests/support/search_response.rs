//! The established original parity policy: exact structure/discrete values,
//! registered neural tolerance and measured (not deterministic) elapsed times.
pub fn real_response(got: &serde_json::Value, want: &serde_json::Value, key: &str) {
    use serde_json::Value;
    match key {
        "neural_score" | "code_score" | "mean_score" => {
            let a = got.as_f64().unwrap();
            let b = want.as_f64().unwrap();
            assert!(
                a.is_finite() && (b != 0. || a == 0.) && (a - b).abs() <= 1e-5 + 1e-5 * b.abs(),
                "{key}: {a} != {b}"
            );
        }
        "token_ms" | "inference_ms" => {
            let a = got.as_f64().unwrap();
            assert!(a.is_finite() && a >= 0.);
            if want == 0. {
                assert_eq!(a, 0.)
            }
        }
        _ => match want {
            Value::Object(w) => {
                let g = got.as_object().unwrap_or_else(|| panic!("{key}: {got}"));
                assert_eq!(
                    g.keys().collect::<Vec<_>>(),
                    w.keys().collect::<Vec<_>>(),
                    "{key}: {got}"
                );
                for (k, v) in w {
                    real_response(&g[k], v, k)
                }
            }
            Value::Array(w) => {
                let g = got.as_array().unwrap();
                assert_eq!(g.len(), w.len(), "{key}");
                for (a, b) in g.iter().zip(w) {
                    real_response(a, b, "")
                }
            }
            _ => assert_eq!(got, want, "{key}"),
        },
    }
}
