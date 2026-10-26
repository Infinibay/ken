use ken_retrieval::{
    Result,
    alignment::{FloatMatrix, FloatVector, TermAlignment, TermCoverage},
    matrix::Matrix,
};
use serde::Deserialize;
use serde_json::Value;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "../../ken-models/tests/support/oracle_profiles.rs"]
mod profiles;
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Input,
    result: Option<Value>,
    error: Option<Value>,
}
#[derive(Deserialize)]
struct Input {
    query: Numbers,
    weights: Numbers,
    documents: Option<Numbers>,
    similarities: Option<Numbers>,
    maxima: Option<Numbers>,
    present: Option<Vec<bool>>,
}
#[derive(Deserialize)]
struct Numbers {
    dtype: String,
    rows: Option<usize>,
    columns: Option<usize>,
    values: Vec<Value>,
}
fn number(v: &Value) -> f64 {
    v.as_f64()
        .unwrap_or_else(|| match v["$float"].as_str().unwrap() {
            "nan" => f64::NAN,
            "inf" => f64::INFINITY,
            "-inf" => f64::NEG_INFINITY,
            _ => panic!("unknown number"),
        })
}
impl Numbers {
    fn matrix(&self) -> FloatMatrix {
        let values: Vec<_> = self.values.iter().map(number).collect();
        if self.dtype == "float32" {
            FloatMatrix::F32(
                Matrix::new(
                    self.rows.unwrap(),
                    self.columns.unwrap(),
                    values.into_iter().map(|v| v as f32).collect(),
                )
                .unwrap(),
            )
        } else {
            FloatMatrix::F64(
                Matrix::new(self.rows.unwrap(), self.columns.unwrap(), values).unwrap(),
            )
        }
    }
    fn vector(&self) -> FloatVector {
        if self.dtype == "float32" {
            FloatVector::F32(self.values.iter().map(|v| number(v) as f32).collect())
        } else {
            FloatVector::F64(self.values.iter().map(number).collect())
        }
    }
}
fn close(got: f64, want: &Value, is32: bool, id: &str) {
    let want = number(want);
    if !want.is_finite() {
        assert!(
            if want.is_nan() {
                got.is_nan()
            } else {
                got == want
            },
            "{id}: {got} vs {want}"
        );
        return;
    }
    let tolerance = if is32 { 1e-6 } else { 1e-12 };
    assert!(
        got.is_finite() && (got - want).abs() <= tolerance + tolerance * want.abs(),
        "{id}: {got:?} vs {want:?}"
    );
}
fn coverage(got: TermCoverage, want: &Value, is32: bool, weights32: bool, id: &str) {
    for (name, value) in [
        ("mean", got.mean),
        ("minimum", got.minimum),
        ("quartile", got.quartile),
        ("above50", got.above50),
        ("above70", got.above70),
        ("weighted", got.weighted),
    ] {
        if matches!(name, "above50" | "above70") {
            assert_eq!(value, number(&want[name]), "threshold {id}/{name}");
        } else {
            close(
                value,
                &want[name],
                is32 && (name != "weighted" || weights32),
                &format!("{id}/{name}"),
            );
        }
    }
}
#[test]
fn full_original_dtype_dispatch_and_term_summary_observations() {
    if let Some(raw) = platform_reference("alignment") {
        observe(&raw, 245);
        return;
    }
    #[cfg(target_os = "macos")]
    let raw: std::borrow::Cow<'_, str> =
        include_str!("fixtures/numeric-reference-alignment.json").into();
    #[cfg(all(target_os = "linux", target_arch = "aarch64"))]
    let raw: std::borrow::Cow<'_, str> =
        include_str!("fixtures/numeric-reference-alignment-linux.json").into();
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    let raw: std::borrow::Cow<'_, str> = {
        use std::io::Read;
        let mut raw = String::new();
        flate2::read::GzDecoder::new(
            &include_bytes!("fixtures/numeric-reference-alignment-linux-x86_64.json.gz")[..],
        )
        .read_to_string(&mut raw)
        .unwrap();
        raw.into()
    };
    observe(&raw, 245);
}
#[test]
fn original_rounding_floor_and_overflow_observations() {
    if let Some(raw) = platform_reference("alignment-edges") {
        observe(&raw, 22);
        return;
    }
    #[cfg(target_os = "macos")]
    let raw = include_str!("fixtures/numeric-reference-alignment-edges.json");
    #[cfg(target_os = "linux")]
    let raw = include_str!("fixtures/numeric-reference-alignment-edges-linux.json");
    observe(raw, 22);
}
fn platform_reference(family: &str) -> Option<String> {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        if family != "alignment" {
            return None;
        }
        let runtime = ken_retrieval::dense_runtime_identity().expect("actual loaded BLAS identity");
        let descriptor = serde_json::json!({"format":"ken-alignment-profile/1","target":"linux-x86_64","numpy":"2.4.4","core":runtime.core,"threads":runtime.threads,"sha256":runtime.sha256});
        let repo = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let reference = profiles::registered(family, &descriptor, &repo)
            .expect("registered original for actual alignment execution profile");
        use std::io::Read;
        let mut raw = String::new();
        match reference.encoding.as_str() {
            "gzip" => {
                flate2::read::GzDecoder::new(reference.bytes.as_slice())
                    .read_to_string(&mut raw)
                    .unwrap();
            }
            "json" => {
                raw = String::from_utf8(reference.bytes).unwrap();
            }
            _ => unreachable!("validated reference encoding"),
        }
        Some(raw)
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    std::env::var_os("KEN_NUMERIC_REFERENCE_DIR").map(|directory| {
        std::fs::read_to_string(
            std::path::PathBuf::from(directory).join(format!("numeric-reference-{family}.json")),
        )
        .expect("read authenticated same-host numeric reference")
    })
}
fn observe(raw: &str, count: usize) {
    let corpus: Corpus = serde_json::from_str(raw).unwrap();
    assert_eq!(corpus.cases.len(), count);
    for case in corpus.cases {
        let got = (|| -> Result<()> {
            let alignment =
                TermAlignment::new(case.input.query.matrix(), case.input.weights.vector())?;
            let want = case.result.as_ref().unwrap_or(&Value::Null);
            match case.kind.as_str() {
                "similarities" | "coverage" => {
                    let documents = case.input.documents.as_ref().unwrap().matrix();
                    let values = alignment.similarities(&documents)?;
                    let (rows, cols, is32, values) = match values {
                        FloatMatrix::F32(m) => (
                            m.rows(),
                            m.columns(),
                            true,
                            m.values().iter().map(|v| *v as f64).collect::<Vec<_>>(),
                        ),
                        FloatMatrix::F64(m) => (m.rows(), m.columns(), false, m.values().to_vec()),
                    };
                    if case.kind == "coverage" {
                        let measured = alignment.coverage(&documents)?;
                        coverage(
                            measured,
                            &want["coverage"],
                            is32,
                            case.input.weights.dtype == "float32",
                            &case.id,
                        );
                    }
                    assert_eq!(want["rows"], rows);
                    assert_eq!(want["columns"], cols);
                    assert_eq!(want["dtype"], if is32 { "float32" } else { "float64" });
                    let expected = want["values"].as_array().unwrap();
                    assert_eq!(values.len(), expected.len());
                    for (a, b) in values.iter().zip(expected) {
                        close(*a, b, is32, &case.id);
                    }
                }
                "summarize" => {
                    let input = case.input.similarities.as_ref().unwrap();
                    coverage(
                        alignment.summarize(&input.matrix())?,
                        want,
                        input.dtype == "float32",
                        case.input.weights.dtype == "float32",
                        &case.id,
                    );
                }
                "maxima" => {
                    let input = case.input.maxima.as_ref().unwrap();
                    let measured = alignment
                        .summarize_maxima(&input.matrix(), case.input.present.as_ref().unwrap())?;
                    let expected = want.as_array().unwrap();
                    assert_eq!(measured.len(), expected.len());
                    for (a, b) in measured.into_iter().zip(expected) {
                        coverage(
                            a,
                            b,
                            input.dtype == "float32",
                            case.input.weights.dtype == "float32",
                            &case.id,
                        );
                    }
                }
                _ => panic!("unknown operation"),
            }
            Ok(())
        })();
        match (got, case.error) {
            (Ok(()), None) => {}
            (Err(got), Some(want)) => {
                assert_eq!(want["type"], "ValueError");
                assert_eq!(
                    got.to_string(),
                    want["message"].as_str().unwrap(),
                    "{}",
                    case.id
                );
            }
            (got, want) => panic!("{}: {got:?}, expected {want:?}", case.id),
        }
    }
}
#[test]
fn alignment_rejects_output_overflow_before_allocation_or_ffi() {
    let query = FloatMatrix::F32(Matrix::new(2, 0, vec![]).unwrap());
    let alignment = TermAlignment::new(query, FloatVector::F32(vec![1., 1.])).unwrap();
    let documents = FloatMatrix::F32(Matrix::new(usize::MAX, 0, vec![]).unwrap());
    assert!(alignment.similarities(&documents).is_err());
}

#[test]
fn frozen_statistic_dtype_controls_numeric_forest_branches() {
    use ken_retrieval::numeric_ranker::NumericRanker;
    let alignment = TermAlignment::new(
        FloatMatrix::F32(Matrix::new(4, 1, vec![0.; 4]).unwrap()),
        FloatVector::F64(vec![1.; 4]),
    )
    .unwrap();
    let value = alignment
        .summarize_maxima(
            &FloatMatrix::F32(Matrix::new(1, 4, vec![0.1, 0.2, 0.3, 0.4]).unwrap()),
            &[true],
        )
        .unwrap()[0];
    assert_eq!(value.quartile.to_bits(), 0.17499999701976776_f64.to_bits());
    let weighted = TermAlignment::new(
        FloatMatrix::F64(Matrix::new(1, 1, vec![0.]).unwrap()),
        FloatVector::F32(vec![1e-9]),
    )
    .unwrap()
    .summarize_maxima(
        &FloatMatrix::F64(Matrix::new(1, 1, vec![0.7]).unwrap()),
        &[true],
    )
    .unwrap()[0]
        .weighted;
    assert_eq!(weighted.to_bits(), 0.6999999802026479_f64.to_bits());
    for (feature, value, threshold) in [
        ("quartile", value.quartile, 0.175),
        ("weighted", weighted, 0.699999985),
    ] {
        let model=NumericRanker::from_json(&format!(r#"{{"schema":1,"features":["{feature}"],"trees":[{{"feature":0,"threshold":{threshold},"left":{{"value":-1}},"right":{{"value":1}}}}]}}"#)).unwrap();
        assert_eq!(
            model
                .predict(&Matrix::new(1, 1, vec![value]).unwrap())
                .unwrap(),
            vec![-1.],
            "{feature} dtype must retain the original branch"
        );
    }
}
