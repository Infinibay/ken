use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_reader::SourceFileReader,
};
use std::{fs, path::Path};
fn reader(root: &Path) -> SourceFileReader {
    let context = DiscoveryContext {
        cwd: root.into(),
        home: Some(root.into()),
        forced_root: None,
    };
    SourceFileReader::new(&ProjectPaths::at(root, &context).unwrap()).unwrap()
}
#[test]
fn source_handle_retains_metadata_and_bytes_after_path_replacement() {
    let root = tempfile::tempdir().unwrap();
    fs::write(root.path().join("a.py"), b"original").unwrap();
    let reader = reader(root.path());
    let opened = reader.open(Path::new("a.py")).unwrap();
    assert_eq!(opened.metadata().unwrap().len(), 8);
    fs::rename(root.path().join("a.py"), root.path().join("old.py")).unwrap();
    fs::write(root.path().join("a.py"), b"new").unwrap();
    assert_eq!(opened.read().unwrap(), b"original");
    assert_eq!(
        reader.open(Path::new("a.py")).unwrap().read().unwrap(),
        b"new"
    );
}
#[test]
fn internal_symlinks_are_admitted_but_escape_and_special_files_are_not() {
    use std::{ffi::CString, os::unix::ffi::OsStrExt, os::unix::fs::symlink};
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    fs::write(root.path().join("a.py"), b"inside").unwrap();
    fs::write(outside.path().join("secret.py"), b"outside").unwrap();
    symlink("a.py", root.path().join("alias.py")).unwrap();
    symlink(outside.path(), root.path().join("external")).unwrap();
    let r = reader(root.path());
    assert_eq!(
        r.open(Path::new("alias.py")).unwrap().read().unwrap(),
        b"inside"
    );
    assert!(r.open(Path::new("external/secret.py")).is_err());
    assert!(r.open(outside.path().join("secret.py").as_path()).is_err());
    assert!(r.open(Path::new(".")).is_err());
    let fifo = CString::new(root.path().join("pipe.py").as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(fifo.as_ptr(), 0o600) }, 0);
    assert!(r.open(Path::new("pipe.py")).is_err());
}
#[test]
fn project_root_replacement_cannot_redirect_initial_root_handle() {
    use std::os::unix::fs::symlink;
    let parent = tempfile::tempdir().unwrap();
    let root = parent.path().join("project");
    let outside = parent.path().join("outside");
    fs::create_dir_all(&root).unwrap();
    fs::create_dir_all(&outside).unwrap();
    let context = DiscoveryContext {
        cwd: root.clone(),
        home: Some(root.clone()),
        forced_root: None,
    };
    let paths = ProjectPaths::at(&root, &context).unwrap();
    fs::rename(&root, parent.path().join("old-project")).unwrap();
    symlink(&outside, &root).unwrap();
    let opened = SourceFileReader::new(&paths);
    fs::remove_file(&root).unwrap();
    fs::rename(parent.path().join("old-project"), &root).unwrap();
    assert!(opened.is_err());
}
