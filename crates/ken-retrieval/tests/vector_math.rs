//! Fresh NumPy2.4.4 x86-V3 observations, exercising the real registered BLAS.
use flate2::read::GzDecoder;
use ken_retrieval::vector_math::{NativeVectorMath, QueryNorm};
use serde_json::Value;
use std::io::Read;
fn fixture() -> Value {
    use sha2::Digest;
    let bytes = include_bytes!("fixtures/vector-math-reference.json.gz");
    assert_eq!(bytes.len(), 2789925);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "389d79b67eb1ef71c4852e74589929987a792fa6fcfc91a1257fb062569c9ee3"
    );
    let mut raw = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut raw).unwrap();
    serde_json::from_str(&raw).unwrap()
}
fn values(raw: &Value) -> Vec<f32> {
    raw.as_array()
        .unwrap()
        .iter()
        .map(|v| f32::from_bits(v.as_u64().unwrap() as u32))
        .collect()
}
fn indices(raw: &Value) -> Vec<usize> {
    raw.as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap() as usize)
        .collect()
}
fn same(got: &[f32], raw: &Value, label: &str) {
    let want = values(raw);
    assert_eq!(got.len(), want.len(), "{label}");
    for (i, (a, b)) in got.iter().zip(want).enumerate() {
        assert!(
            a.to_bits() == b.to_bits() || a.is_nan() && b.is_nan(),
            "{label} [{i}] {a:?}/0x{:08x} != {b:?}/0x{:08x}",
            a.to_bits(),
            b.to_bits()
        );
    }
}
fn backend(data: &Value) -> NativeVectorMath {
    assert_eq!(data["metadata"]["numpy"], "2.4.4");
    assert_eq!(data["metadata"]["cpu_features"]["AVX2"], true);
    assert_eq!(data["metadata"]["cpu_features"]["AVX512F"], false);
    let actual = ken_retrieval::dense_runtime_identity().unwrap();
    assert_eq!(
        actual.core,
        data["metadata"]["blas"]["core"].as_str().unwrap()
    );
    assert_eq!(
        actual.threads,
        data["metadata"]["blas"]["threads"].as_i64().unwrap() as i32
    );
    assert_eq!(
        actual.sha256,
        data["metadata"]["files"]["libscipy_openblas64_-32a4b2a6.so"]["sha256"]
            .as_str()
            .unwrap()
    );
    let math = NativeVectorMath::platform().unwrap();
    assert_eq!(math.ordering_profile().unwrap(), "numpy-2.4.4-linux-x86-v3");
    let identity = math.ordering_identity().unwrap();
    assert!(identity.compiler.starts_with("16.2.1"));
    assert_ne!(identity.stdlib, 0);
    assert_eq!(
        identity.source_commit,
        "5adb33411f3cea8bdbafa9d91bd75bc4bf19c7dd"
    );
    use sha2::Digest;
    let sources = include_bytes!("../resources/vector-math-sources.json");
    assert_eq!(sources.len(), 1408);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(sources)),
        "02dea0d9002c3df599d9ca4981a12a419bc29cdb937f9b2915b9e8605f4d4cba"
    );
    math
}
#[test]
fn real_dense_norms_normalizations_scores_and_products_match_original_f32_order() {
    let data = fixture();
    let math = backend(&data);
    let cases = data["math"].as_array().unwrap();
    assert_eq!(cases.len(), 99);
    for c in cases {
        let q = values(&c["query"]);
        let matrix = values(&c["matrix"]);
        let rows = c["rows"].as_u64().unwrap() as usize;
        let width = c["width"].as_u64().unwrap() as usize;
        let label = c["name"].as_str().unwrap();
        same(
            &[math.query_norm(&q).unwrap()],
            &serde_json::json!([c["norm"]]),
            &format!("{label} query_norm"),
        );
        same(
            &math
                .normalize_query(&q, QueryNorm::AddEpsilon(1e-12))
                .unwrap(),
            &c["normalized_add"],
            &format!("{label} normalize_add"),
        );
        same(
            &math
                .normalize_query(&q, QueryNorm::ClampEpsilon(1e-12))
                .unwrap(),
            &c["normalized_clamp"],
            &format!("{label} normalize_clamp"),
        );
        same(
            &math.row_norms(&matrix, rows, width).unwrap(),
            &c["row_norms"],
            &format!("{label} row_norms"),
        );
        let unit = math
            .normalize_rows_additive(&matrix, rows, width, 1e-12)
            .unwrap();
        same(
            &unit,
            &c["normalized_rows"],
            &format!("{label} normalize_rows"),
        );
        same(
            &math.scores(&matrix, rows, width, &q).unwrap(),
            &c["scores"],
            &format!("{label} scores"),
        );
        same(
            &math.cosine_against(&q, &matrix, rows, width).unwrap(),
            &c["cosine"],
            &format!("{label} cosine"),
        );
        same(
            &math.product(&unit, rows, width, &unit, rows).unwrap(),
            &c["product"],
            &format!("{label} symmetric_product"),
        );
    }
}
#[test]
fn stored_blob_dimensions_strictness_and_original_kept_positions_are_preserved() {
    let data = fixture();
    let math = backend(&data);
    let cases = data["rank"].as_array().unwrap();
    assert_eq!(cases.len(), 50);
    for c in cases {
        let q = values(&c["query"]);
        let blobs: Vec<Option<Vec<u8>>> = c["blobs"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| {
                v.as_str().map(|s| {
                    (0..s.len())
                        .step_by(2)
                        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
                        .collect()
                })
            })
            .collect();
        let borrowed: Vec<_> = blobs.iter().map(|b| b.as_deref()).collect();
        let result = math.rank_against(&q, &borrowed, c["strict"].as_bool().unwrap());
        if c["expected"].get("error").is_some() {
            assert!(result.is_err(), "{}", c["name"]);
            continue;
        }
        let ranked = result.unwrap();
        assert_eq!(
            ranked.kept,
            indices(&c["expected"]["kept"]),
            "{}",
            c["name"]
        );
        same(
            &ranked.scores,
            &c["expected"]["scores"],
            c["name"].as_str().unwrap(),
        );
    }
}
#[test]
fn actual_x86_sort_partition_ties_nonfinite_and_reduction_results_match() {
    let data = fixture();
    let math = backend(&data);
    let cases = data["order"].as_array().unwrap();
    assert_eq!(cases.len(), 202);
    for c in cases {
        let input = values(&c["values"]);
        let label = c["name"].as_str().unwrap();
        assert_eq!(
            math.argsort_descending_f32(&input).unwrap(),
            indices(&c["descending"]),
            "{label} argsort"
        );
        let (mean, std) = math.mean_std_f32(&input).unwrap();
        same(&[mean, std], &c["mean_std"], label);
        for p in c["partitions"].as_array().unwrap() {
            assert_eq!(
                math.argpartition_f32(&input, p["kth"].as_u64().unwrap() as usize)
                    .unwrap(),
                indices(&p["indices"]),
                "{label} kth {}",
                p["kth"]
            );
        }
        for t in c["thresholds"].as_array().unwrap() {
            assert_eq!(
                math.indices_at_least_f32(&input, t["threshold"].as_f64().unwrap()),
                indices(&t["indices"]),
                "{label} threshold {}",
                t["threshold"]
            );
        }
    }
}
#[test]
fn malformed_shapes_are_rejected_before_foreign_kernel_access() {
    let data = fixture();
    let math = backend(&data);
    assert!(math.scores(&[], 1, 2, &[1., 1.]).is_err());
    assert!(math.scores(&[], usize::MAX, 2, &[1., 1.]).is_err());
    assert!(math.scores(&[1.], 1, 1, &[1., 2.]).is_err());
    assert!(math.row_norms(&[], 2, 1).is_err());
    assert!(math.product(&[], usize::MAX, 0, &[], 2).is_err());
    assert!(math.argpartition_f32(&[1.], 1).is_err());
    assert!(
        math.normalize_query(&[1.], QueryNorm::AddEpsilon(f32::NAN))
            .is_err()
    );
}
#[test]
fn f64_consumers_reuse_distinct_qualified_numpy_and_python_reductions() {
    let values = [1e16, 1., -1e16];
    assert_eq!(ken_retrieval::vector_math::sum_f64(&values), 0.);
    assert_eq!(ken_retrieval::vector_math::python_sum_f64(&values), 1.);
    assert_eq!(
        ken_retrieval::vector_math::sum_f64(&[-0.]).to_bits(),
        0f64.to_bits()
    );
    assert_eq!(
        ken_retrieval::vector_math::python_sum_f64(&[-0.]).to_bits(),
        0f64.to_bits()
    );
}
#[test]
fn symmetric_pointer_alias_dispatch_is_distinct_from_equal_copied_inputs() {
    let data = fixture();
    let math = backend(&data);
    let c = data["math"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "random/2049/7")
        .unwrap();
    let unit = values(&c["normalized_rows"]);
    let copied = unit.clone();
    let aliased = math.product(&unit, 7, 2049, &unit, 7).unwrap();
    let separate = math.product(&unit, 7, 2049, &copied, 7).unwrap();
    same(&aliased, &c["product"], "original aliased SSYRK");
    // This exact SGEMM bit pattern was observed in repair-context-math-group.log.
    // NumPy's source dispatches equal-valued separate buffers to that existing
    // qualified GEMM owner, so value equality must not trigger alias optimization.
    assert_eq!(separate[2].to_bits(), 0x380e1e00);
    assert_eq!(aliased[2].to_bits(), 0x380e1d00);
    for i in 0..7 {
        for j in 0..7 {
            assert_eq!(aliased[i * 7 + j].to_bits(), aliased[j * 7 + i].to_bits());
        }
    }
    // Zero/single-row/single-width cases retain their original special dispatch.
    for c in data["math"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["rows"].as_u64().unwrap() <= 1 || c["width"].as_u64().unwrap() <= 1)
    {
        let unit = values(&c["normalized_rows"]);
        let copied = unit.clone();
        let rows = c["rows"].as_u64().unwrap() as usize;
        let width = c["width"].as_u64().unwrap() as usize;
        let a = math.product(&unit, rows, width, &unit, rows).unwrap();
        let b = math.product(&unit, rows, width, &copied, rows).unwrap();
        assert_eq!(
            a.iter().map(|v| v.to_bits()).collect::<Vec<_>>(),
            b.iter().map(|v| v.to_bits()).collect::<Vec<_>>()
        );
    }
}
#[test]
fn single_column_matmul_starts_from_positive_zero_before_adding_products() {
    let data = fixture();
    let math = backend(&data);
    let c = data["math"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "special/98")
        .unwrap();
    let q = values(&c["query"]);
    let matrix = values(&c["matrix"]);
    same(
        &math.scores(&matrix, 3, 1, &q).unwrap(),
        &c["scores"],
        "original scalar-vector +0 accumulator",
    );
    same(
        &math.product(&matrix, 3, 1, &matrix, 3).unwrap(),
        &c["product"],
        "original outer-product +0 accumulator",
    );
    for value in [0., -0.] {
        assert_eq!(
            math.scores(&[value], 1, 1, &[-0.]).unwrap()[0].to_bits(),
            0f32.to_bits()
        );
        assert_eq!(
            math.product(&[value], 1, 1, &[-0.], 1).unwrap()[0].to_bits(),
            0f32.to_bits()
        );
    }
}
