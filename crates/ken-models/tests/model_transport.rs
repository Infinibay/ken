//! Public requests validate immutable data before touching any connection.
use ken_models::{ArtifactRequest, ArtifactTransport, PublicModelTransport};

#[test]
fn invalid_public_identifiers_revisions_and_paths_fail_before_connecting() {
    let transport = PublicModelTransport::new().unwrap();
    for (model_id, revision, name) in [
        ("../model", "a".repeat(40), "config.json"),
        ("owner/..", "a".repeat(40), "config.json"),
        ("https://elsewhere/model", "a".repeat(40), "config.json"),
        ("owner/model", "main".into(), "config.json"),
        ("owner/model", "a".repeat(40), "../config.json"),
        ("owner/model", "a".repeat(40), "config.json?token=bad"),
    ] {
        assert!(
            transport
                .open(&ArtifactRequest {
                    model_id: model_id.into(),
                    revision,
                    name: name.into()
                })
                .is_err()
        );
    }
}
