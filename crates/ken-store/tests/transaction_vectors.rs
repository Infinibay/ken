use ken_store::{ProjectDatabase, VectorSpace, VectorStore, allocate};
use std::{
    io::{BufRead, BufReader, Write},
    path::Path,
    process::{Command, Stdio},
};

fn seed(root: &Path, space: VectorSpace) {
    let mut db = ProjectDatabase::open(&root.join("ken.db")).unwrap();
    db.initialize().unwrap();
    let store = VectorStore::open(&root.join("vectors"), space, 2, None).unwrap();
    let mut tx = db.immediate().unwrap();
    assert_eq!(allocate(&mut tx, space, 1).unwrap(), [0]);
    tx.connection().execute("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,vec_slot) VALUES(1,'owner',x'',0,0,?1)", [if space == VectorSpace::Files { Some(0) } else { None }]).unwrap();
    if space == VectorSpace::Symbols {
        tx.connection().execute("INSERT INTO ci_symbols(id,file_id,kind,name,line_start,line_end,vec_slot) VALUES(1,1,'function','owner',1,1,0)", []).unwrap();
    }
    if space == VectorSpace::IntentSources {
        tx.connection().execute("INSERT INTO ci_intent_sources(id,source_kind,text,updated_at,vec_slot) VALUES(1,'module_docstring','owner',0,0)", []).unwrap();
    }
    store.write(&[0], &[vec![1., 0.]], true).unwrap();
    tx.commit().unwrap();
}

fn replace_without_commit(root: &Path, space: VectorSpace, wait: bool) {
    let mut db = ProjectDatabase::open(&root.join("ken.db")).unwrap();
    let store = VectorStore::open(&root.join("vectors"), space, 2, None).unwrap();
    let mut tx = db.immediate().unwrap();
    let table = if space == VectorSpace::Symbols {
        "ci_files"
    } else {
        space.as_str()
    };
    tx.connection()
        .execute(&format!("DELETE FROM {table} WHERE id=1"), [])
        .unwrap();
    let slots = allocate(&mut tx, space, 1).unwrap();
    store.write(&slots, &[vec![0., 1.]], true).unwrap();
    if wait {
        println!("replacement-written");
        std::io::stdout().flush().unwrap();
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).unwrap();
    }
    // Drop rolls SQL back; committed vector bytes must still match the owner.
}

fn assert_original(root: &Path, space: VectorSpace) {
    let db = ProjectDatabase::open(&root.join("ken.db")).unwrap();
    let slot: i64 = db
        .connection()
        .query_row(
            &format!("SELECT vec_slot FROM {space} WHERE id=1"),
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(slot, 0);
    let store = VectorStore::open(&root.join("vectors"), space, 2, None).unwrap();
    assert_eq!(
        store.read(&[slot]).unwrap(),
        [vec![1., 0.]],
        "rollback changed committed {space} bytes"
    );
}

#[test]
fn deleting_or_cascading_then_writing_and_rolling_back_preserves_committed_vectors() {
    // Catches reuse of a deleted committed owner's bytes before SQL commits.
    for space in VectorSpace::ALL {
        let root = tempfile::tempdir().unwrap();
        seed(root.path(), space);
        replace_without_commit(root.path(), space, false);
        assert_original(root.path(), space);
    }
}

#[test]
fn replacement_process() {
    let Some(root) = std::env::var_os("KEN_SLOT_ROLLBACK_CHILD") else {
        return;
    };
    let space = std::env::var("KEN_SLOT_ROLLBACK_SPACE")
        .unwrap()
        .parse()
        .unwrap();
    replace_without_commit(Path::new(&root), space, true);
}

#[test]
fn killing_a_replacement_writer_preserves_deleted_and_cascaded_owners() {
    // Catches the same corruption when Drop cannot execute after SIGKILL.
    for space in VectorSpace::ALL {
        let root = tempfile::tempdir().unwrap();
        seed(root.path(), space);
        let mut process = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "replacement_process", "--nocapture"])
            .env("KEN_SLOT_ROLLBACK_CHILD", root.path())
            .env("KEN_SLOT_ROLLBACK_SPACE", space.as_str())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let mut output = BufReader::new(process.stdout.take().unwrap());
        let mut line = String::new();
        loop {
            assert!(output.read_line(&mut line).unwrap() > 0);
            if line.contains("replacement-written") {
                break;
            }
            line.clear();
        }
        process.kill().unwrap();
        assert!(!process.wait().unwrap().success());
        assert_original(root.path(), space);
    }
}

#[test]
fn missing_or_lowered_counters_reject_allocation_without_touching_owned_bytes() {
    // Catches a fresh range overlapping current or rollback-restorable owners.
    for space in VectorSpace::ALL {
        for missing in [false, true] {
            let root = tempfile::tempdir().unwrap();
            seed(root.path(), space);
            let mut db = ProjectDatabase::open(&root.path().join("ken.db")).unwrap();
            let sql = if missing {
                "DELETE FROM ci_vec_alloc WHERE space=?1"
            } else {
                "UPDATE ci_vec_alloc SET next_slot=0 WHERE space=?1"
            };
            db.connection().execute(sql, [space.as_str()]).unwrap();
            let before: Option<i64> = db
                .connection()
                .query_row(
                    "SELECT max(next_slot) FROM ci_vec_alloc WHERE space=?1",
                    [space.as_str()],
                    |r| r.get(0),
                )
                .unwrap();
            let mut tx = db.immediate().unwrap();
            assert!(
                allocate(&mut tx, space, 1).is_err(),
                "accepted corrupt {space} counter (missing={missing})"
            );
            let after: Option<i64> = tx
                .connection()
                .query_row(
                    "SELECT max(next_slot) FROM ci_vec_alloc WHERE space=?1",
                    [space.as_str()],
                    |r| r.get(0),
                )
                .unwrap();
            assert_eq!(after, before);
            drop(tx);
            assert_original(root.path(), space);
        }
    }
}
