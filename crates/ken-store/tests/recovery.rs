use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_store::{ProjectDatabase, ProjectStore, VectorSpace, compact, migrate_inline};
use serde_json::{Value, json};
use std::{
    io::{BufRead, BufReader, Write},
    os::unix::process::ExitStatusExt,
    path::Path,
    process::{Child, Command, Stdio},
};

fn paths(root: &Path) -> ProjectPaths {
    ProjectPaths::at(
        root,
        &DiscoveryContext {
            cwd: root.into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap()
}
fn seed(root: &Path) {
    let mut project = ProjectStore::open(&paths(root)).unwrap();
    project.initialize().unwrap();
    project.database().connection().execute_batch("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,vec_slot) VALUES(1,'a',x'',0,0,4),(2,'b',x'',0,0,1); INSERT INTO ci_symbols(id,file_id,kind,name,line_start,line_end,vec_slot) VALUES(1,1,'function','a',1,1,4),(2,2,'function','b',1,1,1); INSERT INTO ci_intent_sources(id,source_kind,text,updated_at,vec_slot) VALUES(1,'module_docstring','a',0,4),(2,'module_docstring','b',0,1);").unwrap();
    for space in VectorSpace::ALL {
        project
            .database()
            .connection()
            .execute("INSERT INTO ci_vec_alloc VALUES(?1,5)", [space.as_str()])
            .unwrap();
        project
            .vectors(space, 2, None)
            .unwrap()
            .write(&[4, 1], &[vec![1., 0.], vec![0., 1.]], true)
            .unwrap();
    }
}
fn emit(value: Value) {
    println!("recovery-event:{value}");
    std::io::stdout().flush().unwrap();
}
fn event(reader: &mut impl BufRead) -> Value {
    loop {
        let mut line = String::new();
        assert!(reader.read_line(&mut line).unwrap() > 0, "child ended");
        if let Some((_, payload)) = line.split_once("recovery-event:") {
            return serde_json::from_str(payload.trim()).unwrap();
        }
    }
}
fn child(root: &Path, phase: &str) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "recovery_process", "--nocapture"])
        .env("KEN_STORAGE_CHILD_ROOT", root)
        .env("KEN_STORAGE_CHILD_PHASE", phase)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .unwrap()
}
fn kill_at(root: &Path, phase: &str) {
    let mut process = child(root, phase);
    let mut events = BufReader::new(process.stdout.take().unwrap());
    assert_eq!(event(&mut events)["phase"], phase);
    process.kill().unwrap();
    assert_eq!(process.wait().unwrap().signal(), Some(9));
}
fn reopen_process(root: &Path) -> Value {
    let mut process = child(root, "recover");
    let mut events = BufReader::new(process.stdout.take().unwrap());
    let result = event(&mut events);
    assert!(process.wait().unwrap().success());
    result
}
#[test]
fn recovery_process() {
    let Some(root) = std::env::var_os("KEN_STORAGE_CHILD_ROOT") else {
        return;
    };
    let root = Path::new(&root);
    let phase = std::env::var("KEN_STORAGE_CHILD_PHASE").unwrap();
    let mut project = ProjectStore::open(&paths(root)).unwrap();
    project.initialize().unwrap();
    if phase == "migrated" {
        migrate_inline(&mut project, 2, None, 1, |event| {
            let value = serde_json::to_value(event).unwrap();
            emit(value);
            let mut line = String::new();
            assert!(std::io::stdin().read_line(&mut line).unwrap() > 0);
        })
        .unwrap();
    } else if phase != "recover" && phase != "migrate_recover" {
        compact(&mut project, 2, |event| {
            let value = serde_json::to_value(event).unwrap();
            if value["phase"] == phase {
                emit(value);
                let mut line = String::new();
                assert!(std::io::stdin().read_line(&mut line).unwrap() > 0);
            }
        })
        .unwrap();
    } else {
        if phase == "migrate_recover" {
            migrate_inline(&mut project, 2, None, 1, |_| {}).unwrap();
        }
        let mut result = serde_json::Map::new();
        for space in VectorSpace::ALL {
            let conn = project.database().connection();
            let pairs: Vec<(i64, i64)> = conn
                .prepare(&format!(
                    "SELECT id,vec_slot FROM {space} WHERE vec_slot IS NOT NULL ORDER BY id"
                ))
                .unwrap()
                .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
                .unwrap()
                .map(Result::unwrap)
                .collect();
            let store = project.vectors(space, 2, None).unwrap();
            result.insert(space.to_string(),json!({"pairs":pairs,"rows":store.read(&pairs.iter().map(|p|p.1).collect::<Vec<_>>()).unwrap()}));
        }
        emit(Value::Object(result));
    }
}

#[test]
fn killed_inline_migration_keeps_committed_batches_and_resumes() {
    let root = tempfile::tempdir().unwrap();
    let mut project = ProjectStore::open(&paths(root.path())).unwrap();
    project.initialize().unwrap();
    for (id, values) in [
        (1, vec![0f32, 1., 0.]),
        (2, vec![1., 0.]),
        (3, vec![0., 1.]),
    ] {
        let blob: Vec<_> = values.iter().flat_map(|n| n.to_le_bytes()).collect();
        project.database().connection().execute("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,embedding) VALUES(?1,?2,x'',0,0,?3)",rusqlite::params![id,format!("file{id}"),blob]).unwrap();
    }
    drop(project);
    kill_at(root.path(), "migrated");
    let db = ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
    let states: Vec<(i64, bool, Option<i64>)> = db
        .connection()
        .prepare("SELECT id,embedding IS NOT NULL,vec_slot FROM ci_files ORDER BY id")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    assert_eq!(
        states,
        [(1, true, None), (2, false, Some(0)), (3, true, None)]
    );
    drop(db);
    let mut process = child(root.path(), "migrate_recover");
    let mut output = BufReader::new(process.stdout.take().unwrap());
    let actual = event(&mut output);
    assert!(process.wait().unwrap().success());
    assert_eq!(actual["ci_files"]["pairs"], json!([[2, 0], [3, 1]]));
    assert_eq!(actual["ci_files"]["rows"], json!([[1., 0.], [0., 1.]]));
    assert_eq!(reopen_process(root.path()), actual);
    println!(
        "recovery-observation:{}",
        json!({"killed_at":"migrated_batch1","actual":actual,"repeat_equal":true})
    );
}
#[test]
fn killed_compaction_recovers_before_project_data_is_exposed() {
    // Catches any DB/file generation hybrid at each real publication/commit boundary.
    use std::os::unix::fs::PermissionsExt;
    for phase in [
        "journal_published",
        "backup_renamed",
        "new_published",
        "database_committed",
    ] {
        let root = tempfile::tempdir().unwrap();
        seed(root.path());
        let private = root.path().join(".ken/vectors/private");
        std::fs::create_dir(&private).unwrap();
        std::fs::write(private.join("data"), "readonly contents").unwrap();
        std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o500)).unwrap();
        std::fs::write(root.path().join(".ken/foreign-sentinel"), "keep").unwrap();
        kill_at(root.path(), phase);
        let actual = reopen_process(root.path());
        assert_eq!(reopen_process(root.path()), actual);
        let private_mode = std::fs::metadata(&private).unwrap().permissions().mode() & 0o777;
        let private_contents = std::fs::read_to_string(private.join("data")).unwrap();
        std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o700)).unwrap();
        assert_eq!(private_mode, 0o500);
        assert_eq!(private_contents, "readonly contents");
        for space in VectorSpace::ALL {
            assert_eq!(actual[space.as_str()]["rows"], json!([[1., 0.], [0., 1.]]));
            let expected = if phase == "database_committed" {
                json!([[1, 1], [2, 0]])
            } else {
                json!([[1, 4], [2, 1]])
            };
            assert_eq!(actual[space.as_str()]["pairs"], expected);
        }
        assert_eq!(
            std::fs::read_to_string(root.path().join(".ken/foreign-sentinel")).unwrap(),
            "keep"
        );
        for entry in std::fs::read_dir(root.path().join(".ken"))
            .unwrap()
            .flatten()
        {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            assert!(
                !name.starts_with(".vectors-") && name != "vectors-maintenance.json",
                "orphan: {name}"
            );
        }
        println!(
            "recovery-observation:{}",
            json!({"killed_at":phase,"actual":actual,"repeat_equal":true})
        );
    }
}

#[test]
fn partial_discard_cleanup_resumes_after_its_internal_owner_receipt_is_deleted() {
    // Construct the exact durable crash image after unlinking the internal owner.
    // Recursive deletion order is unspecified; waiting for this interval with
    // SIGSTOP raced with rmdir when the owner happened to be removed last.
    // Actual external SIGKILL publication-boundary cases remain above.
    let root = tempfile::tempdir().unwrap();
    seed(root.path());
    let live = root.path().join(".ken/vectors");
    let many = live.join("zz-many");
    std::fs::create_dir(&many).unwrap();
    for n in 0..15_000 {
        std::fs::write(many.join(format!("{n:05}")), []).unwrap();
    }
    kill_at(root.path(), "new_published");
    let owner = live.join(".ken-storage-owner.json");
    assert!(owner.is_file());
    let journal = root.path().join(".ken/vectors-maintenance.json");
    let mut record: Value = serde_json::from_slice(&std::fs::read(&journal).unwrap()).unwrap();
    assert_eq!(record["phase"], "prepared");
    record["phase"] = json!("discarding_new");
    std::fs::write(&journal, serde_json::to_vec(&record).unwrap()).unwrap();
    std::fs::File::open(&journal).unwrap().sync_all().unwrap();
    std::fs::File::open(journal.parent().unwrap())
        .unwrap()
        .sync_all()
        .unwrap();
    std::fs::remove_file(&owner).unwrap();
    std::fs::remove_file(many.join("00000")).unwrap();
    std::fs::File::open(&many).unwrap().sync_all().unwrap();
    std::fs::File::open(&live).unwrap().sync_all().unwrap();
    assert!(!owner.exists());
    assert_eq!(std::fs::read_dir(&many).unwrap().count(), 14_999);
    assert!(live.join("ci_files.json").is_file());
    let hidden = root.path().join(".ken/interrupted-generation");
    std::fs::rename(&live, &hidden).unwrap();
    std::fs::create_dir(&live).unwrap();
    std::fs::write(live.join("foreign"), "keep").unwrap();
    assert!(ProjectStore::open(&paths(root.path())).is_err());
    assert_eq!(
        std::fs::read_to_string(live.join("foreign")).unwrap(),
        "keep"
    );
    std::fs::remove_file(live.join("foreign")).unwrap();
    std::fs::remove_dir(&live).unwrap();
    std::fs::rename(&hidden, &live).unwrap();
    let actual = reopen_process(root.path());
    for space in VectorSpace::ALL {
        assert_eq!(actual[space.as_str()]["pairs"], json!([[1, 4], [2, 1]]));
        assert_eq!(actual[space.as_str()]["rows"], json!([[1., 0.], [0., 1.]]));
    }
    assert_eq!(reopen_process(root.path()), actual);
    assert_eq!(std::fs::read_dir(&many).unwrap().count(), 15_000);
    assert!(!root.path().join(".ken/vectors-maintenance.json").exists());
}
#[test]
fn malformed_recovery_journal_cannot_touch_unrelated_paths() {
    // Catches unconfined paths, forged ownership, unknown phases/markers and silent empty recovery.
    let root = tempfile::tempdir().unwrap();
    seed(root.path());
    kill_at(root.path(), "journal_published");
    let journal = root.path().join(".ken/vectors-maintenance.json");
    let original: Value = serde_json::from_slice(&std::fs::read(&journal).unwrap()).unwrap();
    let foreign = root.path().join("foreign");
    std::fs::create_dir(&foreign).unwrap();
    std::fs::write(foreign.join("keep"), "sentinel").unwrap();
    for (key, value) in [
        ("staging", json!(foreign)),
        ("staging", json!("../foreign")),
        ("backup", json!("other/backup")),
        ("id", json!("wrong")),
        ("phase", json!("invented")),
        ("format", json!(9)),
    ] {
        let mut bad = original.clone();
        bad[key] = value;
        std::fs::write(&journal, serde_json::to_vec(&bad).unwrap()).unwrap();
        assert!(
            ProjectStore::open(&paths(root.path())).is_err(),
            "accepted {key}"
        );
        assert_eq!(
            std::fs::read_to_string(foreign.join("keep")).unwrap(),
            "sentinel"
        );
    }
    std::fs::write(&journal, serde_json::to_vec(&original).unwrap()).unwrap();
    let db = ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
    db.set_meta("__ken_vector_compaction", "wrong").unwrap();
    assert!(ProjectStore::open(&paths(root.path())).is_err());
    db.connection()
        .execute("DELETE FROM meta WHERE key='__ken_vector_compaction'", [])
        .unwrap();
    drop(db);
    reopen_process(root.path());

    let committed = tempfile::tempdir().unwrap();
    seed(committed.path());
    kill_at(committed.path(), "database_committed");
    let committed_journal = committed.path().join(".ken/vectors-maintenance.json");
    let committed_raw = std::fs::read(&committed_journal).unwrap();
    let mut invalid_cleanup: Value = serde_json::from_slice(&committed_raw).unwrap();
    invalid_cleanup["phase"] = json!("discarding_new");
    std::fs::write(
        &committed_journal,
        serde_json::to_vec(&invalid_cleanup).unwrap(),
    )
    .unwrap();
    assert!(ProjectStore::open(&paths(committed.path())).is_err());
    std::fs::write(&committed_journal, committed_raw).unwrap();
    let live = committed.path().join(".ken/vectors");
    let hidden = committed.path().join(".ken/hidden-committed");
    std::fs::rename(&live, &hidden).unwrap();
    assert!(ProjectStore::open(&paths(committed.path())).is_err());
    assert!(!live.exists());
    std::fs::rename(&hidden, &live).unwrap();
    reopen_process(committed.path());
}

#[test]
fn null_commit_marker_never_reinterprets_committed_rows_as_rollback() {
    // A legacy nullable meta table must not turn a corrupt marker into an absent commit.
    let root = tempfile::tempdir().unwrap();
    seed(root.path());
    kill_at(root.path(), "database_committed");
    let journal = root.path().join(".ken/vectors-maintenance.json");
    let original_raw = std::fs::read(&journal).unwrap();
    let original: Value = serde_json::from_slice(&original_raw).unwrap();
    let db = ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
    db.connection().execute_batch("ALTER TABLE meta RENAME TO meta_previous; CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); INSERT INTO meta SELECT key,value FROM meta_previous; DROP TABLE meta_previous; UPDATE meta SET value=NULL WHERE key='__ken_vector_compaction';").unwrap();
    assert!(ProjectStore::open(&paths(root.path())).is_err());
    assert_eq!(std::fs::read(&journal).unwrap(), original_raw);
    db.connection()
        .execute(
            "UPDATE meta SET value=?1 WHERE key='__ken_vector_compaction'",
            [original["id"].as_str().unwrap()],
        )
        .unwrap();
    drop(db);
    let actual = reopen_process(root.path());
    assert_eq!(actual["ci_files"]["pairs"], json!([[1, 1], [2, 0]]));
}
