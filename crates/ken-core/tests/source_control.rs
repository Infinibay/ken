use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_reader::SourceFileReader,
};
#[test]
fn bounded_read_stops_mid_file_without_returning_partial_source_bytes() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("large.py"), vec![b'x'; 200000]).unwrap();
    let context = DiscoveryContext {
        cwd: d.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(d.path(), &context).unwrap();
    let reader = SourceFileReader::new(&paths).unwrap();
    let file = reader.open(std::path::Path::new("large.py")).unwrap();
    let mut calls = 0;
    let result = file.read_bounded_checked(300000, &mut || {
        calls += 1;
        if calls == 5 {
            Err(std::io::Error::other("mid-read cancellation"))
        } else {
            Ok(())
        }
    });
    assert_eq!(result.unwrap_err().to_string(), "mid-read cancellation");
    assert_eq!(calls, 5);
    assert_eq!(
        reader
            .open(std::path::Path::new("large.py"))
            .unwrap()
            .read_bounded(300000)
            .unwrap()
            .unwrap()
            .len(),
        200000
    );
}
