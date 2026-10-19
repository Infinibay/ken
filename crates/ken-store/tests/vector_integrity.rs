use ken_store::{ProjectDatabase, VectorSpace, VectorStore, live_scores, verify};
use serde_json::json;
use std::{
    os::unix::fs::MetadataExt,
    sync::{Arc, Barrier},
};

#[test]
fn sparse_verification_does_not_walk_the_high_water_address_space() {
    // Catches a corrupt/large counter making verification scan trillions of absent files.
    let root = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    db.connection()
        .execute("INSERT INTO ci_vec_alloc VALUES('ci_files',?1)", [i64::MAX])
        .unwrap();
    let store =
        VectorStore::open(&root.path().join("vectors"), VectorSpace::Files, 2, None).unwrap();
    store.write(&[0], &[vec![1., 0.]], true).unwrap();
    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "sparse_verifier_process", "--nocapture"])
        .env("KEN_VECTOR_SPARSE_VERIFY", root.path())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::inherit())
        .spawn()
        .unwrap();
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            assert!(status.success());
            break;
        }
        if std::time::Instant::now() >= deadline {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("verification must inspect existing files, not iterate high-water");
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
}

#[test]
fn sparse_verifier_process() {
    let Some(root) = std::env::var_os("KEN_VECTOR_SPARSE_VERIFY") else {
        return;
    };
    let root = std::path::Path::new(&root);
    let db = ProjectDatabase::open(&root.join("index.db")).unwrap();
    let store = VectorStore::open(&root.join("vectors"), VectorSpace::Files, 2, None).unwrap();
    let report = verify(db.connection(), &store).unwrap();
    assert_eq!(report.high_water, i64::MAX);
    assert_eq!(report.segments, 1);
    assert_eq!(report.leaked, i64::MAX);
}

#[test]
fn invalid_vector_inputs_fail_before_any_referenced_bytes_change() {
    // Catches validation after the first write, overflow-to-false-zero and manifest identity loss.
    let root = tempfile::tempdir().unwrap();
    let store = VectorStore::open(root.path(), VectorSpace::Files, 2, Some("a")).unwrap();
    store.write(&[0], &[vec![1., 0.]], true).unwrap();
    let path = root.path().join("ci_files.0000.vec");
    let before = std::fs::read(&path).unwrap();
    for (slots, rows) in [
        (vec![0, 1], vec![vec![0., 1.]]),
        (vec![0, 1], vec![vec![0., 1.], vec![1.]]),
        (vec![0, -1], vec![vec![0., 1.], vec![1., 0.]]),
        (vec![0, i64::MAX], vec![vec![0., 1.], vec![1., 0.]]),
        (vec![0, 1], vec![vec![0., 1.], vec![f32::NAN, 0.]]),
        (vec![0, 1], vec![vec![0., 1.], vec![f32::INFINITY, 0.]]),
        (vec![0, 1], vec![vec![0., 1.], vec![1e30, 1e30]]),
    ] {
        assert!(store.write(&slots, &rows, false).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), before);
    }
    assert!(store.read(&[-1]).is_err());
    assert!(store.read(&[i64::MAX]).is_err());
    assert!(store.scores(&[f32::NAN, 0.], 1).is_err());
    assert!(store.scores(&[1e30, 1e30], 1).is_err());
    assert!(store.scores(&[1.], 1).is_err());
    assert_eq!(store.scores(&[], 0).unwrap(), Vec::<f32>::new());
    store.write(&[], &[vec![f32::NAN]], false).unwrap();
    store.write(&[1], &[vec![0., 0.]], false).unwrap();
    assert_eq!(store.read(&[1]).unwrap(), [vec![0., 0.]]);
    let manifest = root.path().join("ci_files.json");
    let original = std::fs::read(&manifest).unwrap();
    for (dim, model) in [
        (3, Some("a")),
        (2, Some("b")),
        (0, None),
        (usize::MAX, None),
    ] {
        assert!(VectorStore::open(root.path(), VectorSpace::Files, dim, model).is_err());
        assert_eq!(std::fs::read(&manifest).unwrap(), original);
    }
    for bad in [
        json!({"format":2,"space":"ci_files","dim":2}),
        json!({"format":1,"space":"ci_symbols","dim":2}),
        json!({"format":1,"space":"ci_files","dim":2,"dtype":"float64"}),
        json!({"format":1,"space":"ci_files","dim":2,"segment_rows":0}),
        json!({"format":1,"space":"ci_files","dim":0}),
        json!({"format":1,"space":"ci_files","dim":2,"segment_rows":u64::MAX}),
    ] {
        let raw = serde_json::to_vec(&bad).unwrap();
        std::fs::write(&manifest, &raw).unwrap();
        assert!(VectorStore::open(root.path(), VectorSpace::Files, 2, None).is_err());
        assert_eq!(std::fs::read(&manifest).unwrap(), raw);
    }
    // Compatible omitted fields and unknown keys survive; null never asserts model identity.
    let raw = br#"{"format":1,"space":"ci_files","dim":2,"model":null,"extension":"keep"}"#;
    std::fs::write(&manifest, raw).unwrap();
    VectorStore::open(root.path(), VectorSpace::Files, 2, Some("requested")).unwrap();
    assert_eq!(std::fs::read(&manifest).unwrap(), raw);
}

#[test]
fn verification_and_live_scores_preserve_slot_accounting() {
    // Catches dropping leaked/live slots, accepting SQL errors as empty, or counting free slots in ranking.
    let root = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    let store =
        VectorStore::open(&root.path().join("vectors"), VectorSpace::Files, 2, None).unwrap();
    assert!(
        live_scores(db.connection(), &store, &[1., 0.])
            .unwrap()
            .is_none()
    );
    db.connection().execute_batch("INSERT INTO ci_vec_alloc VALUES('ci_files',5); INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,vec_slot) VALUES(1,'a',x'',0,0,0),(2,'b',x'',0,0,2); INSERT INTO ci_vec_free VALUES('ci_files',1);").unwrap();
    store
        .write(
            &[0, 1, 2, 3],
            &[vec![1., 0.], vec![1., 0.], vec![0., 1.], vec![1., 0.]],
            true,
        )
        .unwrap();
    let report = verify(db.connection(), &store).unwrap();
    assert_eq!(
        serde_json::to_value(report).unwrap(),
        json!({"high_water":5,"referenced":2,"free":1,"leaked":2,"out_of_range":0,"double_booked":0,"segments":1})
    );
    db.connection().execute_batch("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,vec_slot) VALUES(3,'c',x'',0,0,8),(4,'d',x'',0,0,-1); INSERT INTO ci_vec_free VALUES('ci_files',2),('ci_files',-9),('ci_files',99);").unwrap();
    assert_eq!(
        serde_json::to_value(verify(db.connection(), &store).unwrap()).unwrap(),
        json!({"high_water":5,"referenced":4,"free":4,"leaked":0,"out_of_range":2,"double_booked":1,"segments":1})
    );
    let live = live_scores(db.connection(), &store, &[1., 0.])
        .unwrap()
        .unwrap();
    assert_eq!(live.slots, [0, 3, 4]);
    assert_eq!(live.scores, [1., 1., 0.]);
    assert!(live_scores(db.connection(), &store, &[1.]).is_err());
    let metadata = std::fs::metadata(root.path().join("vectors/ci_files.0000.vec")).unwrap();
    assert_eq!(metadata.len(), 65536 * 2 * 4);
    assert_eq!(store.bytes_on_disk().unwrap(), metadata.blocks() * 512);
    // A filesystem may fully allocate a written segment. Keep a genuinely
    // sparse, never-written segment to distinguish physical bytes from length.
    let sparse_dir = root.path().join("sparse");
    let sparse = VectorStore::open(&sparse_dir, VectorSpace::Files, 2, None).unwrap();
    let segment = std::fs::File::create(sparse_dir.join("ci_files.0000.vec")).unwrap();
    segment.set_len(65536 * 2 * 4).unwrap();
    let sparse_metadata = segment.metadata().unwrap();
    assert_eq!(
        sparse.bytes_on_disk().unwrap(),
        sparse_metadata.blocks() * 512
    );
    assert!(sparse.bytes_on_disk().unwrap() < sparse_metadata.len());
    assert_eq!(
        sparse.read(&[0, 65535]).unwrap(),
        [vec![0., 0.], vec![0., 0.]]
    );
    db.connection()
        .execute_batch("DROP TABLE ci_vec_alloc")
        .unwrap();
    assert!(verify(db.connection(), &store).is_err());
    assert!(live_scores(db.connection(), &store, &[1., 0.]).is_err());
}

#[test]
fn flush_and_reads_remain_safe_during_concurrent_writes() {
    // Catches sharing mutable borrowed storage or losing writes across a flush/read handoff.
    let root = tempfile::tempdir().unwrap();
    let store = Arc::new(VectorStore::open(root.path(), VectorSpace::Files, 2, None).unwrap());
    store.write(&[0], &[vec![1., 0.]], false).unwrap();
    let barrier = Arc::new(Barrier::new(2));
    std::thread::scope(|scope| {
        let other = Arc::clone(&store);
        let sync = Arc::clone(&barrier);
        scope.spawn(move || {
            for _ in 0..32 {
                sync.wait();
                other
                    .write(&[0, 1], &[vec![0., 1.], vec![1., 0.]], false)
                    .unwrap();
                sync.wait();
            }
        });
        for _ in 0..32 {
            let owned = store.read(&[0]).unwrap();
            barrier.wait();
            store.flush().unwrap();
            let during = store.read(&[0, 1]).unwrap();
            assert_eq!(during.len(), 2);
            barrier.wait();
            assert!(owned[0] == [1., 0.] || owned[0] == [0., 1.]);
            assert_eq!(store.read(&[0, 1]).unwrap(), [vec![0., 1.], vec![1., 0.]]);
            store.write(&[0], &[vec![1., 0.]], false).unwrap();
        }
    });
    store.flush().unwrap();
    assert_eq!(
        VectorStore::open(root.path(), VectorSpace::Files, 2, None)
            .unwrap()
            .read(&[0, 1])
            .unwrap(),
        [vec![1., 0.], vec![1., 0.]]
    );
}
