#[cfg(target_os = "linux")]
#[test]
fn dense_bundle_authenticates_every_platform_sidecar_before_loading() {
    use ken_retrieval::verify_dense_runtime;
    use serde_json::Value;
    let raw = if cfg!(target_arch = "x86_64") {
        include_str!("../resources/dense-runtime-x86_64.json")
    } else {
        include_str!("../resources/dense-runtime.json")
    };
    let manifest: Value = serde_json::from_str(raw).unwrap();
    let directory = tempfile::tempdir().unwrap();
    let error = verify_dense_runtime(directory.path())
        .unwrap_err()
        .to_string();
    assert!(error.contains("prepare dense BLAS runtime"), "{error}");
    for name in manifest["files"].as_object().unwrap().keys() {
        let corrupt = tempfile::tempdir().unwrap();
        for (other, record) in manifest["files"].as_object().unwrap() {
            let source = std::path::PathBuf::from(std::env::var_os("KEN_DENSE_BLAS_DIR").unwrap());
            let bytes = std::fs::read(source.join(other)).unwrap();
            assert_eq!(bytes.len() as u64, record["bytes"].as_u64().unwrap());
            let content: &[u8] = if other == name { b"changed" } else { &bytes };
            std::fs::write(corrupt.path().join(other), content).unwrap();
        }
        assert!(
            verify_dense_runtime(corrupt.path())
                .unwrap_err()
                .to_string()
                .contains("integrity differs")
        );
    }
    let prepared = std::path::PathBuf::from(std::env::var_os("KEN_DENSE_BLAS_DIR").unwrap());
    verify_dense_runtime(&prepared).unwrap();
}
