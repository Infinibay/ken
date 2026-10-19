mod support;

use ken_store::{VectorSpace, VectorStore};
use std::{
    io::BufReader,
    process::{Command, Stdio},
};

fn close(actual: &[f32], expected: &[f32]) {
    assert_eq!(actual.len(), expected.len());
    for (a, b) in actual.iter().zip(expected) {
        assert!((a - b).abs() <= 1e-6 + 1e-6 * b.abs(), "{a} != {b}");
    }
}

#[test]
fn python_segments_and_native_segments_are_cross_readable() {
    // Catches a different layout/normalization, a boundary offset error, or lost order/duplicates.
    let root = tempfile::tempdir().unwrap();
    let script = format!(
        "{}\n{}",
        support::ORIGINAL_IMPORTS,
        r#"
store = vectors.VectorStore(root, 'ci_files', dim=2, model='módelo')
store.write([65535, 65536, 131072, 3, 3], np.array([[1,0],[0,1],[0,0],[1,0],[3,4]], dtype=np.float32), durable=True)
store.close()
event({'ready': True})
assert input() == 'read'
with vectors.VectorStore(root, 'ci_files', dim=2, model='módelo') as store:
    event({'rows': store.read([65535,65536,131072,3,2]).tolist(), 'scores': store.scores(np.array([3,4], dtype=np.float32), count=4).tolist()})
"#
    );
    let mut child = support::original_python(&script, root.path());
    let mut events = BufReader::new(child.stdout.take().unwrap());
    assert_eq!(support::event(&mut events)["ready"], true);
    let dir = root.path().join(".ken/vectors");
    let original_manifest = std::fs::read(dir.join("ci_files.json")).unwrap();
    let store = VectorStore::open(&dir, VectorSpace::Files, 2, Some("módelo")).unwrap();
    let rows = store
        .read(&[65536, 65535, 3, 131072, 65536, 196608])
        .unwrap();
    assert_eq!(rows[0], [0., 1.]);
    assert_eq!(rows[1], [1., 0.]);
    close(&rows[2], &[0.6, 0.8]);
    assert_eq!(rows[3], [0., 0.]);
    assert_eq!(rows[4], rows[0]);
    assert_eq!(rows[5], [0., 0.]);
    store
        .write(
            &[65535, 65536, 131072, 3, 3],
            &[
                vec![0., 1.],
                vec![1., 0.],
                vec![0., 0.],
                vec![1., 0.],
                vec![4., 3.],
            ],
            true,
        )
        .unwrap();
    store.flush().unwrap();
    assert_eq!(
        std::fs::read(dir.join("ci_files.json")).unwrap(),
        original_manifest
    );
    support::signal(child.stdin.as_mut().unwrap(), "read");
    let result = support::event(&mut events);
    assert!(child.wait().unwrap().success());
    assert_eq!(result["rows"][0], serde_json::json!([0., 1.]));
    assert_eq!(result["rows"][1], serde_json::json!([1., 0.]));
    assert_eq!(result["rows"][2], serde_json::json!([0., 0.]));
    close(
        &result["rows"][3]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap() as f32)
            .collect::<Vec<_>>(),
        &[0.8, 0.6],
    );
    close(
        &result["scores"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap() as f32)
            .collect::<Vec<_>>(),
        &[0., 0., 0., 0.96],
    );
    assert_eq!(
        VectorStore::open(&dir, VectorSpace::Files, 2, None)
            .unwrap()
            .read(&[65536])
            .unwrap(),
        [vec![1., 0.]]
    );

    // A fresh native manifest must also be consumable by the actual original.
    let native = VectorStore::open(&dir, VectorSpace::Symbols, 2, Some("nativo")).unwrap();
    native.write(&[0], &[vec![0., 2.]], true).unwrap();
    let script = format!(
        "{}\nwith vectors.VectorStore(root, 'ci_symbols', dim=2) as s:\n    event(s.read([0]).tolist())",
        support::ORIGINAL_IMPORTS
    );
    let mut child = support::original_python(&script, root.path());
    let mut events = BufReader::new(child.stdout.take().unwrap());
    assert_eq!(support::event(&mut events), serde_json::json!([[0., 1.]]));
    assert!(child.wait().unwrap().success());
}

#[test]
fn segment_creation_never_exposes_partial_capacity_or_resizes_existing_maps() {
    // Catches publication before sizing, resize-on-grow, and trusting a short existing file.
    let root = tempfile::tempdir().unwrap();
    let dir = root.path().join(".ken/vectors");
    let store = VectorStore::open(&dir, VectorSpace::Files, 2, None).unwrap();
    store.write(&[0], &[vec![1., 0.]], true).unwrap();
    let script = format!(
        "{}\n{}",
        support::ORIGINAL_IMPORTS,
        r#"
with vectors.VectorStore(root, 'ci_files', dim=2) as s:
    view = s._map(0)
    event({'mapped': view[0].tolist()})
    assert input() == 'check'
    event({'mapped': view[0].tolist(), 'new': s.read([65536,65537]).tolist()})
"#
    );
    let mut python = support::original_python(&script, root.path());
    let mut events = BufReader::new(python.stdout.take().unwrap());
    assert_eq!(
        support::event(&mut events)["mapped"],
        serde_json::json!([1., 0.])
    );
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "segment_creator_process", "--nocapture"])
        .env("KEN_VECTOR_TEST_CHILD", &dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .unwrap();
    let mut child_events = BufReader::new(child.stdout.take().unwrap());
    assert_eq!(support::event(&mut child_events)["ready"], true);
    support::signal(child.stdin.as_mut().unwrap(), "go");
    store.write(&[65536], &[vec![0., 1.]], true).unwrap();
    while child.try_wait().unwrap().is_none() {
        for entry in std::fs::read_dir(&dir).unwrap().flatten() {
            if entry.path().extension().is_some_and(|s| s == "vec") {
                assert_eq!(entry.metadata().unwrap().len(), 65536 * 2 * 4);
            }
        }
        std::thread::yield_now();
    }
    assert!(child.wait().unwrap().success());
    assert_eq!(
        store.read(&[65536, 65537]).unwrap(),
        [vec![0., 1.], vec![1., 0.]]
    );
    support::signal(python.stdin.as_mut().unwrap(), "check");
    let observed = support::event(&mut events);
    assert_eq!(observed["mapped"], serde_json::json!([1., 0.]));
    assert_eq!(observed["new"], serde_json::json!([[0., 1.], [1., 0.]]));
    assert!(python.wait().unwrap().success());
    std::fs::OpenOptions::new()
        .write(true)
        .open(dir.join("ci_files.0001.vec"))
        .unwrap()
        .set_len(4)
        .unwrap();
    assert!(store.read(&[65536]).is_err());
    assert!(store.scores(&[1., 0.], 65537).is_err());
    assert!(store.write(&[65536], &[vec![1., 0.]], false).is_err());
    assert_eq!(
        std::fs::metadata(dir.join("ci_files.0001.vec"))
            .unwrap()
            .len(),
        4
    );
}

#[test]
fn segment_creator_process() {
    let Some(dir) = std::env::var_os("KEN_VECTOR_TEST_CHILD") else {
        return;
    };
    let store = VectorStore::open(std::path::Path::new(&dir), VectorSpace::Files, 2, None).unwrap();
    println!("vector-event:{{\"ready\":true}}");
    use std::io::Write;
    std::io::stdout().flush().unwrap();
    let mut line = String::new();
    assert!(std::io::stdin().read_line(&mut line).unwrap() > 0);
    assert_eq!(line.trim(), "go");
    store.write(&[65537], &[vec![1., 0.]], true).unwrap();
}
