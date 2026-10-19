use ken_store::{ProjectDatabase, VectorSpace, allocate, high_water, release};
use serde_json::{Value, json};
use std::{
    error::Error as _,
    io::{BufRead, BufReader, Write},
    process::{Command, Stdio},
    time::Instant,
};

fn fixture() -> (tempfile::TempDir, ProjectDatabase) {
    let root = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("ken.db")).unwrap();
    db.initialize().unwrap();
    (root, db)
}

#[test]
fn immediate_slot_allocations_reuse_freed_slots_and_rollback() {
    let (_root, mut db) = fixture();
    {
        let mut tx = db.immediate().unwrap();
        assert_eq!(
            allocate(&mut tx, VectorSpace::Files, 3).unwrap(),
            vec![0, 1, 2]
        );
        release(&mut tx, VectorSpace::Files, &[1, 1]).unwrap();
        assert_eq!(
            allocate(&mut tx, VectorSpace::Files, 2).unwrap(),
            vec![1, 3]
        );
        assert_eq!(allocate(&mut tx, VectorSpace::Symbols, 1).unwrap(), vec![0]);
        assert!(!tx.connection().is_autocommit());
        tx.commit().unwrap();
    }
    assert_eq!(high_water(db.connection(), VectorSpace::Files).unwrap(), 4);
    {
        let mut tx = db.immediate().unwrap();
        release(&mut tx, VectorSpace::Files, &[0]).unwrap();
        assert_eq!(
            allocate(&mut tx, VectorSpace::Files, 2).unwrap(),
            vec![0, 4]
        );
    }
    assert_eq!(high_water(db.connection(), VectorSpace::Files).unwrap(), 4);
    assert_eq!(
        db.connection()
            .query_row("SELECT count(*) FROM ci_vec_free", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
    assert!(db.connection().is_autocommit());
}

#[test]
fn invalid_slot_ranges_and_unknown_spaces_fail_without_mutating_allocator() {
    let (_root, mut db) = fixture();
    assert!("ci_files; DROP TABLE meta".parse::<VectorSpace>().is_err());
    let mut tx = db.immediate().unwrap();
    assert!(allocate(&mut tx, VectorSpace::Files, usize::MAX).is_err());
    assert_eq!(high_water(tx.connection(), VectorSpace::Files).unwrap(), 0);
    assert_eq!(
        allocate(&mut tx, VectorSpace::Files, 0).unwrap(),
        Vec::<i64>::new()
    );
    assert!(release(&mut tx, VectorSpace::Files, &[-1]).is_err());
    tx.connection()
        .execute("INSERT INTO ci_vec_alloc VALUES('ci_files',?1)", [i64::MAX])
        .unwrap();
    assert!(allocate(&mut tx, VectorSpace::Files, 1).is_err());
    assert_eq!(
        high_water(tx.connection(), VectorSpace::Files).unwrap(),
        i64::MAX
    );
}

fn event(value: Value) {
    println!("store-event:{value}");
    std::io::stdout().flush().unwrap();
}

#[test]
fn writer_process() {
    let Some(path) = std::env::var_os("KEN_STORE_TEST_CHILD_DB") else {
        return;
    };
    let mut db = ProjectDatabase::open(std::path::Path::new(&path)).unwrap();
    event(json!({"phase":"trying"}));
    let started = Instant::now();
    match db.immediate() {
        Ok(tx) => {
            drop(tx);
            event(json!({"phase":"unexpectedly_acquired"}));
            return;
        }
        Err(error) => {
            let code = error
                .source()
                .and_then(|e| e.downcast_ref::<rusqlite::Error>())
                .and_then(rusqlite::Error::sqlite_error_code);
            assert_eq!(code, Some(rusqlite::ErrorCode::DatabaseBusy));
            event(json!({"phase":"busy","elapsed_ms":started.elapsed().as_millis() as u64}));
        }
    }
    let mut line = String::new();
    assert!(std::io::stdin().read_line(&mut line).unwrap() > 0);
    assert_eq!(line.trim(), "retry");
    let mut tx = db.immediate().unwrap();
    let slots = allocate(&mut tx, VectorSpace::Files, 2).unwrap();
    tx.commit().unwrap();
    event(json!({"phase":"committed","slots":slots}));
}

fn read_event(reader: &mut impl BufRead) -> Value {
    loop {
        let mut line = String::new();
        assert!(
            reader.read_line(&mut line).unwrap() > 0,
            "child ended before its event"
        );
        if let Some(index) = line.find("store-event:") {
            return serde_json::from_str(line[index + 12..].trim()).unwrap();
        }
    }
}

#[test]
fn writers_serialize_slot_ownership() {
    let (root, mut db) = fixture();
    // Hold the lock before even reading or allocating: Deferred must fail here.
    let mut tx = db.immediate().unwrap();
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "writer_process", "--nocapture"])
        .env("KEN_STORE_TEST_CHILD_DB", root.path().join("ken.db"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .unwrap();
    let mut output = BufReader::new(child.stdout.take().unwrap());
    assert_eq!(read_event(&mut output)["phase"], "trying");
    let blocked = read_event(&mut output);
    assert_eq!(blocked["phase"], "busy");
    assert!(blocked["elapsed_ms"].as_u64().unwrap() >= 4500);
    assert_eq!(
        allocate(&mut tx, VectorSpace::Files, 2).unwrap(),
        vec![0, 1]
    );
    tx.commit().unwrap();
    child.stdin.as_mut().unwrap().write_all(b"retry\n").unwrap();
    let committed = read_event(&mut output);
    assert_eq!(committed["phase"], "committed");
    assert_eq!(committed["slots"], json!([2, 3]));
    assert!(child.wait().unwrap().success());
    assert_eq!(high_water(db.connection(), VectorSpace::Files).unwrap(), 4);
}

#[test]
fn a_corrupt_free_list_cannot_reallocate_a_slot_still_owned_by_a_row() {
    let (_root, mut db) = fixture();
    let mut tx = db.immediate().unwrap();
    assert_eq!(allocate(&mut tx, VectorSpace::Files, 1).unwrap(), vec![0]);
    tx.connection().execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,vec_slot) VALUES('owner.py',x'00',0,0,0)", []).unwrap();
    tx.connection()
        .execute(
            "INSERT INTO ci_vec_free(space,slot) VALUES('ci_files',0)",
            [],
        )
        .unwrap();
    assert!(allocate(&mut tx, VectorSpace::Files, 1).is_err());
    assert_eq!(high_water(tx.connection(), VectorSpace::Files).unwrap(), 1);
    assert_eq!(
        tx.connection()
            .query_row(
                "SELECT count(*) FROM ci_vec_free WHERE space='ci_files' AND slot=0",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        1
    );
    assert_eq!(
        tx.connection()
            .query_row(
                "SELECT vec_slot FROM ci_files WHERE path='owner.py'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
}
