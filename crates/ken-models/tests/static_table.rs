use ken_models::StaticTableEncoder;
use serde_json::Value;
use std::{fs, path::PathBuf};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/table")
}

fn vector(want: &Value, got: &[f32], context: &str) {
    let want = want.as_array().unwrap();
    assert_eq!(want.len(), got.len(), "{context}");
    let mut dot = 0_f64;
    let mut norm_a = 0_f64;
    let mut norm_b = 0_f64;
    let zero = want.iter().all(|v| v.as_f64().unwrap() == 0.);
    for (expected, actual) in want.iter().zip(got) {
        let expected = expected.as_f64().unwrap();
        let actual = *actual as f64;
        assert!(actual.is_finite(), "{context}");
        if zero {
            assert_eq!(actual, 0., "{context}");
        } else {
            assert!(
                (expected - actual).abs() <= 2e-6 + 1e-5 * expected.abs(),
                "{context}: wanted {expected}, got {actual}"
            );
        }
        dot += expected * actual;
        norm_a += expected * expected;
        norm_b += actual * actual;
    }
    if !zero {
        assert!(dot / (norm_a * norm_b).sqrt() >= 0.999999, "{context}");
    }
}

fn parity(encoder: &StaticTableEncoder, oracle: &Value) {
    assert_eq!(
        encoder.dim(),
        oracle["dimension"].as_u64().unwrap() as usize
    );
    assert_eq!(encoder.meta(), &oracle["meta"]);
    for (case, result) in oracle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(oracle["results"].as_array().unwrap())
    {
        for (call, expected) in case["calls"]
            .as_array()
            .unwrap()
            .iter()
            .zip(result["calls"].as_array().unwrap())
        {
            let context = format!("{} {}", case["id"], call["op"]);
            match call["op"].as_str().unwrap() {
                "tokens" => assert_eq!(
                    serde_json::to_value(encoder.tokenize(call["text"].as_str().unwrap()).unwrap())
                        .unwrap(),
                    *expected,
                    "{context}"
                ),
                "count" => assert_eq!(
                    encoder.token_count(call["text"].as_str().unwrap()).unwrap() as u64,
                    expected.as_u64().unwrap(),
                    "{context}"
                ),
                "query" => vector(
                    expected,
                    &encoder.embed_query(call["text"].as_str().unwrap()).unwrap(),
                    &context,
                ),
                op @ ("passages" | "queries") => {
                    let texts: Vec<_> = call["texts"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|v| v.as_str().unwrap())
                        .collect();
                    let got: Vec<Vec<f32>> = if op == "passages" {
                        encoder.embed_passages(&texts)
                    } else {
                        encoder.embed_queries(&texts)
                    }
                    .unwrap();
                    let wanted = expected.as_array().unwrap();
                    assert_eq!(got.len(), wanted.len(), "{context}");
                    for (a, b) in wanted.iter().zip(got) {
                        vector(a, &b, &context);
                    }
                }
                _ => panic!("unknown fixture operation"),
            }
        }
    }
}

macro_rules! fixture_test {
    ($test:ident, $name:literal) => {
        #[test]
        fn $test() {
            let encoder = StaticTableEncoder::from_npz(
                &fs::read(fixtures().join(concat!($name, ".npz"))).unwrap(),
            )
            .unwrap();
            let oracle: Value = serde_json::from_slice(
                &fs::read(fixtures().join(concat!($name, ".json"))).unwrap(),
            )
            .unwrap();
            parity(&encoder, &oracle);
        }
    };
}
fixture_test!(float32_sum_projection_empty_and_long_batches, "f32");
fixture_test!(float16_is_converted_before_pooling, "f16");
fixture_test!(float64_is_cast_to_float32_before_inference, "f64");
fixture_test!(int8_uses_individual_row_scales, "int8");
fixture_test!(fortran_and_big_endian_keep_matrix_coordinates, "fortran-be");
fixture_test!(negative_lut_indexes_from_the_end, "negative-lut");
fixture_test!(cancellation_uses_frozen_float32_reduction, "cancellation");
fixture_test!(
    serialized_padding_truncation_unknown_and_count_are_preserved,
    "serialized-policy"
);

#[test]
fn corrupt_tables_fail_without_panicking_or_executing_pickle() {
    let manifest: Value =
        serde_json::from_slice(&fs::read(fixtures().join("manifest.json")).unwrap()).unwrap();
    for name in manifest["invalid"].as_array().unwrap() {
        let bytes = fs::read(fixtures().join(format!("{}.npz", name.as_str().unwrap()))).unwrap();
        assert!(StaticTableEncoder::from_npz(&bytes).is_err(), "{name}");
    }
}

#[test]
fn overflowing_array_header_returns_error() {
    use std::io::{Cursor, Read, Write};
    use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};
    let bytes = fs::read(fixtures().join("f32.npz")).unwrap();
    let mut source = ZipArchive::new(Cursor::new(bytes)).unwrap();
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    for index in 0..source.len() {
        let mut entry = source.by_index(index).unwrap();
        writer
            .start_file(entry.name(), SimpleFileOptions::default())
            .unwrap();
        if entry.name() == "A.npy" {
            let header =
                "{'descr': '<f4', 'fortran_order': False, 'shape': (18446744073709551615, 2), }\n";
            writer.write_all(b"\x93NUMPY\x01\x00").unwrap();
            writer
                .write_all(&(header.len() as u16).to_le_bytes())
                .unwrap();
            writer.write_all(header.as_bytes()).unwrap();
        } else {
            let mut bytes = Vec::new();
            entry.read_to_end(&mut bytes).unwrap();
            writer.write_all(&bytes).unwrap();
        }
    }
    let bytes = writer.finish().unwrap().into_inner();
    assert!(StaticTableEncoder::from_npz(&bytes).is_err());
}

#[test]
fn results_are_independent_owned_vectors() {
    let encoder =
        StaticTableEncoder::from_npz(&fs::read(fixtures().join("f32.npz")).unwrap()).unwrap();
    let mut batch = encoder.embed_passages(&["alfa", "alfa"]).unwrap();
    let original = batch[1].clone();
    batch[0].fill(99.);
    assert_eq!(batch[1], original);
    assert_eq!(encoder.embed_query("alfa").unwrap(), original);
}

#[test]
fn bundled_table_matches_all_frozen_case_outputs() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let encoder = StaticTableEncoder::from_npz(
        &fs::read(repo.join("src/ken/embedder/data/ken__static-qwen3-r512-v2.npz")).unwrap(),
    )
    .unwrap();
    let oracle: Value = serde_json::from_slice(
        &fs::read(repo.join("docs/validation/rust-migration-2026-10-18/m2-table/reference.json"))
            .unwrap(),
    )
    .unwrap();
    parity(&encoder, &oracle);
}
