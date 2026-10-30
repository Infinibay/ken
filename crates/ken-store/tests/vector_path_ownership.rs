//! Segment ownership is enforced by storage for every caller, including install.
#![cfg(unix)]
use ken_store::{VectorSpace, VectorStore};
#[test]
fn existing_and_dangling_segment_symlinks_cannot_be_followed_for_reads_or_writes() {
    for exists in [true, false] {
        let d = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let target = outside.path().join("keep");
        if exists {
            std::fs::write(&target, b"01234567").unwrap();
        }
        std::fs::write(
            d.path().join("ci_files.json"),
            br#"{"format":1,"space":"ci_files","dim":2,"segment_rows":1}"#,
        )
        .unwrap();
        std::os::unix::fs::symlink(&target, d.path().join("ci_files.0000.vec")).unwrap();
        let store = VectorStore::open(d.path(), VectorSpace::Files, 2, None).unwrap();
        assert!(store.read(&[0]).is_err());
        assert!(store.write(&[0], &[vec![1., 0.]], true).is_err());
        if exists {
            assert_eq!(std::fs::read(target).unwrap(), b"01234567");
        } else {
            assert!(!target.exists());
        }
    }
}
#[test]
fn segment_directory_replacement_is_detected_before_creation_or_write() {
    let d = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let directory = d.path().join("vectors");
    let store = VectorStore::open(&directory, VectorSpace::Files, 2, None).unwrap();
    std::fs::rename(&directory, d.path().join("old-vectors")).unwrap();
    std::os::unix::fs::symlink(outside.path(), &directory).unwrap();
    assert!(store.write(&[0], &[vec![1., 0.]], true).is_err());
    assert_eq!(std::fs::read_dir(outside.path()).unwrap().count(), 0);
    assert!(!d.path().join("old-vectors/ci_files.0000.vec").exists());
}
#[test]
fn replacement_segment_is_rechecked_between_preflight_and_write_calls() {
    let d = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let store = VectorStore::open(d.path(), VectorSpace::Files, 2, None).unwrap();
    store.write(&[0], &[vec![1., 0.]], true).unwrap();
    let segment = d.path().join("ci_files.0000.vec");
    let before = std::fs::read(&segment).unwrap();
    let target = outside.path().join("external");
    std::fs::write(&target, &before).unwrap();
    std::fs::remove_file(&segment).unwrap();
    std::os::unix::fs::symlink(&target, &segment).unwrap();
    assert!(store.write(&[0], &[vec![0., 1.]], false).is_err());
    assert_eq!(std::fs::read(target).unwrap(), before);
}
#[test]
fn normal_creation_remains_exclusive_full_capacity_and_reusable_by_another_store() {
    let d = tempfile::tempdir().unwrap();
    let a = VectorStore::open(d.path(), VectorSpace::Files, 2, None).unwrap();
    let b = VectorStore::open(d.path(), VectorSpace::Files, 2, None).unwrap();
    a.write(&[0], &[vec![1., 0.]], true).unwrap();
    b.write(&[1], &[vec![0., 1.]], true).unwrap();
    assert_eq!(a.read(&[0, 1]).unwrap(), vec![vec![1., 0.], vec![0., 1.]]);
    assert_eq!(
        std::fs::metadata(d.path().join("ci_files.0000.vec"))
            .unwrap()
            .len(),
        65536 * 2 * 4
    );
    assert!(
        !std::fs::read_dir(d.path())
            .unwrap()
            .filter_map(Result::ok)
            .any(|entry| entry
                .file_name()
                .to_string_lossy()
                .starts_with(".ken-segment-"))
    );
}
