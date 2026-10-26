#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn dense_runtime_identity_reports_the_loaded_verified_backend() {
    let identity = ken_retrieval::dense_runtime_identity().unwrap();
    assert!(!identity.core.is_empty());
    assert!(identity.threads > 0);
    assert_eq!(
        identity.sha256,
        "05c9f9eb89ee68a4b9d673184fa91c99587e736392c0c2d49180a8aa5303d080"
    );
}
