#[path = "../examples/support/context_preparation.rs"]
mod support;
use serde_json::Value;
use std::io::Read;
fn corpus() -> Value {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/context-preparation-reference.json.gz").as_slice(),
    )
    .read_to_string(&mut raw)
    .unwrap();
    serde_json::from_str(&raw).unwrap()
}
#[test]
fn contextual_preparation_and_cache_match_all_independent_original_histories() {
    for case in corpus()["cases"].as_array().unwrap() {
        let actual =
            support::observe(serde_json::from_value(case["input"].clone()).unwrap()).unwrap();
        if actual != case["events"] {
            panic!(
                "{}: {}",
                case["id"],
                difference(&actual, &case["events"], "events")
                    .unwrap_or_else(|| "numeric JSON category differs".into())
            );
        }
    }
}

fn difference(a: &Value, b: &Value, path: &str) -> Option<String> {
    if a == b {
        return None;
    }
    match (a, b) {
        (Value::Object(a), Value::Object(b)) if a.keys().eq(b.keys()) => {
            for (k, v) in a {
                if let Some(d) = difference(v, &b[k], &format!("{path}.{k}")) {
                    return Some(d);
                }
            }
        }
        (Value::Array(a), Value::Array(b)) if a.len() == b.len() => {
            for (i, (a, b)) in a.iter().zip(b).enumerate() {
                if let Some(d) = difference(a, b, &format!("{path}[{i}]")) {
                    return Some(d);
                }
            }
        }
        _ => return Some(format!("{path}: actual{a} expected{b}")),
    }
    None
}

fn first_input() -> Value {
    corpus()["cases"][0]["input"].clone()
}
fn snapshot(directory: &std::path::Path) -> std::path::PathBuf {
    std::fs::read_dir(directory.join("snapshots"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path()
}
#[test]
fn open_generation_mappings_survive_atomic_replacement_and_unlink() {
    use ken_retrieval::context_preparation::prepare_context;
    use std::{fs, rc::Rc};
    let input = first_input();
    let (_source, catalog) =
        support::catalog(serde_json::from_value(input["physical"].clone()).unwrap()).unwrap();
    let cache = tempfile::tempdir().unwrap();
    let encoder = Rc::new(support::Source::new(&input["model_registration"]).unwrap());
    let old = prepare_context(&catalog, 7, encoder.clone(), cache.path()).unwrap();
    let expected = old.source_snapshot().matrix().values.to_vec();
    assert!(old.source_views().unwrap().matrix().is_mapped);
    let published = snapshot(cache.path());
    let retired = cache.path().join("retired");
    fs::rename(&published, &retired).unwrap();
    *encoder.mode.borrow_mut() = "error".into();
    encoder.calls.borrow_mut().clear();
    let new = prepare_context(&catalog, 8, encoder.clone(), cache.path()).unwrap();
    fs::remove_dir_all(retired).unwrap();
    assert!(encoder.calls.borrow().is_empty());
    assert_eq!(old.source_snapshot().generation(), 7);
    assert_eq!(new.source_snapshot().generation(), 8);
    assert_eq!(old.source_snapshot().matrix().values, expected);
    assert_eq!(new.source_snapshot().matrix().values, expected);
    let policy =
        serde_json::from_value(serde_json::json!({"model":encoder.spec,"view_model":encoder.view}))
            .unwrap();
    let scores = old
        .score(
            &"query".into(),
            &"query".into(),
            catalog.owners(),
            7,
            &policy,
        )
        .unwrap();
    assert_eq!(scores.original(), [0., 0., 0.]);
}
#[test]
fn resealed_npy_layout_and_values_are_rejected_before_use() {
    use ken_retrieval::context_preparation::prepare_context;
    use sha2::{Digest, Sha256};
    use std::{fs, rc::Rc};
    for change in [
        "dtype",
        "endian",
        "shape",
        "fortran",
        "trailing",
        "unaligned",
        "header-size",
        "zero",
    ] {
        let input = first_input();
        let (_source, catalog) =
            support::catalog(serde_json::from_value(input["physical"].clone()).unwrap()).unwrap();
        let cache = tempfile::tempdir().unwrap();
        let encoder = Rc::new(support::Source::new(&input["model_registration"]).unwrap());
        drop(prepare_context(&catalog, 7, encoder.clone(), cache.path()).unwrap());
        let published = snapshot(cache.path());
        let path = published.join("full.npy");
        let mut data = fs::read(&path).unwrap();
        let header = String::from_utf8(data[10..128].to_vec()).unwrap();
        match change {
            "dtype" => {
                let i = header.find("<f4").unwrap() + 10;
                data[i + 1] = b'i';
            }
            "endian" => {
                let i = header.find("<f4").unwrap() + 10;
                data[i] = b'>';
            }
            "shape" => {
                let new = header.replace("(3, 768)", "(1, 2304)");
                let mut new = new.trim_end().to_owned();
                new.extend(std::iter::repeat_n(' ', 117 - new.len()));
                new.push('\n');
                data[10..128].copy_from_slice(new.as_bytes());
            }
            "fortran" => {
                let i = header.find("False").unwrap() + 10;
                data[i..i + 5].copy_from_slice(b"True ");
            }
            "trailing" => data.extend([0; 4]),
            "unaligned" => {
                data.remove(126);
                data[8..10].copy_from_slice(&117u16.to_le_bytes());
            }
            "header-size" => data[8..10].copy_from_slice(&u16::MAX.to_le_bytes()),
            "zero" => data[128..128 + 768 * 4].fill(0),
            _ => unreachable!(),
        }
        fs::write(&path, &data).unwrap();
        let manifest_path = published.join("manifest.json");
        let mut manifest: Value =
            serde_json::from_slice(&fs::read(&manifest_path).unwrap()).unwrap();
        manifest["artifacts"]["full.npy"] = format!("{:x}", Sha256::digest(&data)).into();
        fs::write(manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        encoder.calls.borrow_mut().clear();
        *encoder.mode.borrow_mut() = "error".into();
        assert!(
            prepare_context(&catalog, 8, encoder.clone(), cache.path()).is_err(),
            "admitted {change}"
        );
        assert!(encoder.calls.borrow().is_empty());
    }
}
#[test]
fn simultaneous_source_publishers_reuse_one_complete_snapshot() {
    use ken_retrieval::context_preparation::prepare_context;
    use std::{
        rc::Rc,
        sync::{Arc, Barrier},
    };
    let input = first_input();
    let (_source, catalog) =
        support::catalog(serde_json::from_value(input["physical"].clone()).unwrap()).unwrap();
    let cache = tempfile::tempdir().unwrap();
    let catalog = Arc::new(catalog);
    let barrier = Arc::new(Barrier::new(2));
    let registration = input["model_registration"].clone();
    let results = std::thread::scope(|scope| {
        let mut threads = vec![];
        for generation in [7, 8] {
            let catalog = catalog.clone();
            let barrier = barrier.clone();
            let registration = registration.clone();
            let directory = cache.path();
            threads.push(scope.spawn(move || {
                let encoder = Rc::new(support::Source::new(&registration).unwrap());
                barrier.wait();
                let runtime = prepare_context(&catalog, generation, encoder, directory).unwrap();
                assert_eq!(runtime.source_snapshot().generation(), generation);
                runtime.source_snapshot().matrix().values.to_vec()
            }));
        }
        threads
            .into_iter()
            .map(|t| t.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert_eq!(results[0], results[1]);
    assert_eq!(
        std::fs::read_dir(cache.path().join("snapshots"))
            .unwrap()
            .count(),
        1
    );
}
#[test]
fn source_policy_mismatch_and_invalid_generation_cannot_be_used() {
    use ken_retrieval::context_preparation::prepare_context;
    use std::rc::Rc;
    let input = first_input();
    let (_source, catalog) =
        support::catalog(serde_json::from_value(input["physical"].clone()).unwrap()).unwrap();
    let cache = tempfile::tempdir().unwrap();
    let mut bad = support::Source::new(&input["model_registration"]).unwrap();
    bad.spec.backend = ken_models::EncoderBackend::Model2Vec;
    let bad = Rc::new(bad);
    assert!(prepare_context(&catalog, 7, bad.clone(), cache.path()).is_err());
    assert!(bad.calls.borrow().is_empty());
    let encoder = Rc::new(support::Source::new(&input["model_registration"]).unwrap());
    drop(prepare_context(&catalog, 7, encoder.clone(), cache.path()).unwrap());
    encoder.calls.borrow_mut().clear();
    *encoder.mode.borrow_mut() = "error".into();
    let error = match prepare_context(&catalog, -1, encoder.clone(), cache.path()) {
        Ok(_) => panic!("negative generation accepted"),
        Err(e) => e,
    };
    assert!(
        error
            .to_string()
            .contains("invalid contextual source generation")
    );
    assert!(encoder.calls.borrow().is_empty());
}

// Admission must reject malformed, reauthenticated cache bytes before general
// NPY parsing can perform arithmetic or recursively construct unbounded types.
fn reject_resealed_header(header: &str) {
    use ken_retrieval::context_preparation::prepare_context;
    use sha2::{Digest, Sha256};
    use std::{fs, rc::Rc};
    let input = first_input();
    let (_source, catalog) =
        support::catalog(serde_json::from_value(input["physical"].clone()).unwrap()).unwrap();
    let cache = tempfile::tempdir().unwrap();
    let encoder = Rc::new(support::Source::new(&input["model_registration"]).unwrap());
    drop(prepare_context(&catalog, 7, encoder.clone(), cache.path()).unwrap());
    let published = snapshot(cache.path());
    let path = published.join("full.npy");
    let original = fs::read(&path).unwrap();
    let mut header = header.trim_end().as_bytes().to_vec();
    let padded = (12 + header.len() + 1).div_ceil(64) * 64 - 12;
    header.resize(padded - 1, b' ');
    header.push(b'\n');
    let mut data = b"\x93NUMPY\x02\x00".to_vec();
    data.extend(u32::try_from(header.len()).unwrap().to_le_bytes());
    data.extend(header);
    data.extend_from_slice(&original[128..]);
    fs::write(&path, &data).unwrap();
    let manifest_path = published.join("manifest.json");
    let mut manifest: Value = serde_json::from_slice(&fs::read(&manifest_path).unwrap()).unwrap();
    manifest["artifacts"]["full.npy"] = format!("{:x}", Sha256::digest(&data)).into();
    fs::write(manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    encoder.calls.borrow_mut().clear();
    *encoder.mode.borrow_mut() = "error".into();
    assert!(
        prepare_context(&catalog, 8, encoder.clone(), cache.path()).is_err(),
        "malformed header admitted"
    );
    assert!(encoder.calls.borrow().is_empty());
}
#[test]
fn resealed_declared_shape_cannot_overflow_record_or_stride_products() {
    let nested = format!("{}3{}", "[".repeat(10000), "]".repeat(10000));
    // A long-string key containing an ordinary quote must not disguise nested
    // containers from the lexical budget preceding literal conversion.
    reject_resealed_header(&format!(
        "{{'''padding'key''': {nested}, 'descr': '<f4', 'fortran_order': False, 'shape': (3, 768), }}"
    ));
    for shape in [
        "(18446744073709551615, 768)",
        "(0, 18446744073709551615, 18446744073709551615)",
        &nested,
    ] {
        reject_resealed_header(&format!(
            "{{'descr': '<f4', 'fortran_order': False, 'shape': {shape}, }}"
        ));
    }
}
#[test]
fn resealed_flat_subarray_rank_is_rejected_before_recursive_dtype_construction() {
    reject_resealed_header(&format!(
        "{{'descr': [('field', '<f4', ({}))], 'fortran_order': False, 'shape': (3, 768), }}",
        "1,".repeat(100000)
    ));
}
