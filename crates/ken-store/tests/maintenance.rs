mod support;
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_store::{ProjectStore, VectorSpace, compact, migrate_inline, reclaim_database, verify};
use std::io::BufReader;
use std::os::unix::fs::{MetadataExt, PermissionsExt};

fn fixture() -> (tempfile::TempDir, ProjectStore) {
    let root = tempfile::tempdir().unwrap();
    let context = DiscoveryContext {
        cwd: root.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(root.path(), &context).unwrap();
    let mut project = ProjectStore::open(&paths).unwrap();
    project.initialize().unwrap();
    (root, project)
}
fn blob(values: &[f32]) -> Vec<u8> {
    values.iter().flat_map(|n| n.to_le_bytes()).collect()
}

#[test]
fn compaction_preserves_nested_private_directory_permissions() {
    // Catches disclosure through a recreated parent with broader permissions.
    if std::env::var_os("KEN_PRIVATE_DIRECTORY_CHILD").is_none() {
        use std::os::unix::process::CommandExt;
        let mut command = std::process::Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "compaction_preserves_nested_private_directory_permissions",
            ])
            .env("KEN_PRIVATE_DIRECTORY_CHILD", "1");
        unsafe {
            command.pre_exec(|| {
                libc::umask(0o022);
                Ok(())
            });
        }
        assert!(command.status().unwrap().success());
        return;
    }
    let (root, mut project) = fixture();
    let private = root.path().join(".ken/vectors/private");
    let nested = private.join("nested");
    std::fs::create_dir_all(&nested).unwrap();
    std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::set_permissions(&nested, std::fs::Permissions::from_mode(0o710)).unwrap();
    std::fs::write(nested.join("data"), "private contents").unwrap();
    std::fs::set_permissions(nested.join("data"), std::fs::Permissions::from_mode(0o644)).unwrap();
    compact(&mut project, 2, |_| {}).unwrap();
    assert_eq!(std::fs::metadata(&private).unwrap().mode() & 0o777, 0o700);
    assert_eq!(std::fs::metadata(&nested).unwrap().mode() & 0o777, 0o710);
    assert_eq!(
        std::fs::metadata(nested.join("data")).unwrap().mode() & 0o777,
        0o644
    );
    assert_eq!(
        std::fs::read_to_string(nested.join("data")).unwrap(),
        "private contents"
    );
}
fn file(project: &ProjectStore, id: i64, embedding: &[f32]) {
    project.database().connection().execute("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,embedding) VALUES(?1,?2,x'',0,0,?3)",rusqlite::params![id,format!("f{id}"),blob(embedding)]).unwrap();
}

#[test]
fn inline_migration_is_batched_restartable_and_preserves_foreign_dimensions() {
    // Catches foreign-dimension starvation, partial batch publication, or lost prior commits.
    let (_root, mut project) = fixture();
    file(&project, 1, &[1., 0., 0.]);
    file(&project, 2, &[3., 4.]);
    file(&project, 3, &[0., 0.]);
    file(&project, 4, &[f32::NAN, 0.]);
    assert!(migrate_inline(&mut project, 2, None, 0, |_| {}).is_err());
    let mut events = Vec::new();
    assert!(migrate_inline(&mut project, 2, Some("model"), 1, |e| events.push(e)).is_err());
    let conn = project.database().connection();
    let rows: Vec<(i64, bool, Option<i64>)> = conn
        .prepare("SELECT id,embedding IS NOT NULL,vec_slot FROM ci_files ORDER BY id")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    assert_eq!(
        rows,
        [
            (1, true, None),
            (2, false, Some(0)),
            (3, false, Some(1)),
            (4, true, None)
        ]
    );
    conn.execute(
        "UPDATE ci_files SET embedding=?1 WHERE id=4",
        [blob(&[1., 0.])],
    )
    .unwrap();
    let moved = migrate_inline(&mut project, 2, Some("model"), 1, |_| {}).unwrap();
    assert_eq!(moved[&VectorSpace::Files], 1);
    assert_eq!(
        migrate_inline(&mut project, 2, Some("model"), 1, |_| {}).unwrap()[&VectorSpace::Files],
        0
    );
    let store = project
        .vectors(VectorSpace::Files, 2, Some("model"))
        .unwrap();
    let rows = store.read(&[0, 1, 2]).unwrap();
    assert!((rows[0][0] - 0.6).abs() < 1e-6 && (rows[0][1] - 0.8).abs() < 1e-6);
    assert_eq!(rows[1..], [vec![0., 0.], vec![1., 0.]]);
    let conn = project.database().connection();
    assert_eq!(
        conn.query_row("SELECT embedding FROM ci_files WHERE id=1", [], |r| r
            .get::<_, Vec<u8>>(0))
            .unwrap(),
        blob(&[1., 0., 0.])
    );
    conn.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(reclaim_database(project.database_mut()).is_err());
    project
        .database()
        .connection()
        .execute_batch("ROLLBACK")
        .unwrap();
    reclaim_database(project.database_mut()).unwrap();
    assert_eq!(
        verify(project.database().connection(), &store)
            .unwrap()
            .referenced,
        3
    );
}

#[test]
fn compaction_preserves_all_three_spaces_and_reuses_a_dense_prefix() {
    // Catches mismatched ID→vector remapping, transient unique collisions or discarded foreign files.
    let (root, mut project) = fixture();
    project.database().connection().execute_batch("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at,vec_slot) VALUES(1,'a',x'',0,0,4),(2,'b',x'',0,0,1); INSERT INTO ci_symbols(id,file_id,kind,name,line_start,line_end,vec_slot) VALUES(1,1,'function','a',1,1,4),(2,2,'function','b',1,1,1); INSERT INTO ci_intent_sources(id,source_kind,text,updated_at,vec_slot) VALUES(1,'module_docstring','a',0,4),(2,'module_docstring','b',0,1);").unwrap();
    for space in VectorSpace::ALL {
        project
            .database()
            .connection()
            .execute(
                "INSERT INTO ci_vec_alloc VALUES(?1,131073)",
                [space.as_str()],
            )
            .unwrap();
        project
            .database()
            .connection()
            .execute(
                "INSERT INTO ci_vec_free VALUES(?1,0),(?1,2),(?1,3)",
                [space.as_str()],
            )
            .unwrap();
        let store = project.vectors(space, 2, Some("módelo")).unwrap();
        store
            .write(
                &[4, 1, 131072],
                &[vec![1., 0.], vec![0., 0.], vec![0., 1.]],
                true,
            )
            .unwrap();
    }
    let foreign = root.path().join(".ken/vectors/foreign.txt");
    std::fs::write(&foreign, "keep").unwrap();
    std::fs::write(root.path().join(".ken/vectors/ci_files.1.vec"), "unmanaged").unwrap();
    std::fs::set_permissions(
        root.path().join(".ken/vectors"),
        std::fs::Permissions::from_mode(0o750),
    )
    .unwrap();
    let mut events = Vec::new();
    let counts = compact(&mut project, 2, |e| {
        events.push(serde_json::to_value(e).unwrap())
    })
    .unwrap();
    for space in VectorSpace::ALL {
        assert_eq!(counts[&space].before, 131073);
        assert_eq!(counts[&space].after, 2);
        let conn = project.database().connection();
        let pairs: Vec<(i64, i64)> = conn
            .prepare(&format!("SELECT id,vec_slot FROM {space} ORDER BY id"))
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
            .unwrap()
            .map(Result::unwrap)
            .collect();
        assert_eq!(pairs, [(1, 1), (2, 0)]);
        let store = project.vectors(space, 2, Some("módelo")).unwrap();
        assert_eq!(store.read(&[1, 0]).unwrap(), [vec![1., 0.], vec![0., 0.]]);
        let report = verify(conn, &store).unwrap();
        assert_eq!(
            (
                report.high_water,
                report.leaked,
                report.free,
                report.segments
            ),
            (2, 0, 0, 1)
        );
        assert!(
            !root
                .path()
                .join(format!(".ken/vectors/{space}.0002.vec"))
                .exists()
        );
    }
    assert_eq!(std::fs::read_to_string(foreign).unwrap(), "keep");
    assert_eq!(
        std::fs::read_to_string(root.path().join(".ken/vectors/ci_files.1.vec")).unwrap(),
        "unmanaged"
    );
    assert_eq!(
        std::fs::metadata(root.path().join(".ken/vectors"))
            .unwrap()
            .mode()
            & 0o777,
        0o750
    );
    assert_eq!(
        project
            .database()
            .connection()
            .query_row(
                "SELECT count(*) FROM meta WHERE key LIKE '__ken_vector_%'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
    let phases: Vec<_> = events
        .iter()
        .filter_map(|e| e["phase"].as_str())
        .filter(|p| !matches!(*p, "compacted" | "migrated"))
        .collect();
    assert_eq!(
        phases,
        [
            "staging_ready",
            "journal_published",
            "backup_renamed",
            "new_published",
            "database_committed",
            "cleaned"
        ]
    );
    let script = format!(
        "{}\n{}",
        support::ORIGINAL_IMPORTS,
        r#"
import sqlite3
conn=sqlite3.connect(root/'.ken/ken.db')
out={}
for space in vectors.SPACES:
    with vectors.VectorStore(root,space,dim=2) as store:
        rows=conn.execute(f'SELECT id,vec_slot FROM {space} ORDER BY id').fetchall()
        out[space]=[store.read([slot]).tolist()[0] for _,slot in rows]
event(out)
assert input() == 'done'
"#
    );
    let mut child = support::original_python(&script, root.path());
    let mut events = BufReader::new(child.stdout.take().unwrap());
    let actual = support::event(&mut events);
    for space in VectorSpace::ALL {
        assert_eq!(
            actual[space.as_str()],
            serde_json::json!([[1., 0.], [0., 0.]])
        );
    }
    support::signal(child.stdin.as_mut().unwrap(), "done");
    assert!(child.wait().unwrap().success());
}
