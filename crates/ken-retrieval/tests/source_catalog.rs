use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    EntityKey, Passage,
    source_catalog::{PieceIdentity, SourceCatalog, entity_id},
    source_snapshot::SourceAuthority,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, fs, sync::Arc};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Input,
    result: Option<Value>,
    error: Option<Value>,
}
#[derive(Deserialize)]
struct Input {
    files: BTreeMap<String, Vec<u8>>,
    owners: Vec<Owner>,
    #[serde(default)]
    symlinks: Vec<Link>,
}
#[derive(Deserialize)]
struct Owner {
    key: EntityKey,
    passages: Vec<Passage>,
}
#[derive(Deserialize)]
struct Link {
    path: String,
    target: String,
}
fn observe(catalog: &SourceCatalog) -> Value {
    let projections: Vec<_> = catalog
        .owners()
        .iter()
        .map(|(key, _)| {
            let primary: BTreeMap<_, _> = ["class", "module", "symbol", "file"]
                .into_iter()
                .map(|kind| {
                    let identity = catalog.primary(key, kind).unwrap().map(|p| match p {
                        PieceIdentity::Entity(key) => entity_id(&key),
                        PieceIdentity::Path(path) => path,
                    });
                    (kind, identity)
                })
                .collect();
            json!({"identity":entity_id(key),"extent":catalog.extent(key).unwrap(),
                "owned_ranges":catalog.owned_ranges(key,false).unwrap(),
                "implementation_ranges":catalog.owned_ranges(key,true).unwrap(),
                "scope_members":catalog.scope_members(key).unwrap().map(|keys|keys.into_iter().map(|k|entity_id(&k)).collect::<Vec<_>>()),
                "enclosing_callable":catalog.enclosing_callable(key).unwrap().map(|k|entity_id(&k)),"primary":primary})
        })
        .collect();
    let lines: BTreeMap<_, _> = catalog
        .snapshots()
        .iter()
        .map(|(p, s)| (p, s.lines()))
        .collect();
    let hashes: BTreeMap<_, _> = catalog
        .snapshots()
        .iter()
        .map(|(p, s)| (p, s.hash()))
        .collect();
    json!({"inventory":catalog.source_inventory().unwrap(),"projections":projections,"lines":lines,"hashes":hashes})
}
#[test]
fn source_catalog_confines_current_bytes_and_preserves_owner_gaps() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/piece-reference-catalog.json")).unwrap();
    assert_eq!(corpus.cases.len(), 38);
    for case in corpus.cases {
        let temporary = tempfile::tempdir().unwrap();
        let root = temporary.path().join("project");
        fs::create_dir(&root).unwrap();
        for (name, bytes) in case.input.files {
            let path = root.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, bytes).unwrap();
        }
        for link in case.input.symlinks {
            let path = root.join(link.path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::os::unix::fs::symlink(link.target, path).unwrap();
        }
        let context = DiscoveryContext {
            cwd: root.clone(),
            forced_root: None,
            home: None,
        };
        let paths = ProjectPaths::at(&root, &context).unwrap();
        let source = Arc::new(SourceAuthority::new(&paths).unwrap());
        let owners = case
            .input
            .owners
            .into_iter()
            .map(|o| (o.key, o.passages))
            .collect();
        let got = SourceCatalog::new(source, owners);
        if case.kind == "catalog_admission" {
            assert!(got.is_err(), "source admission {}", case.id);
        } else if let Some(expected) = case.error {
            let error = got.err().expect("original source error");
            assert_eq!(error.kind(), expected["type"], "kind {}", case.id);
            assert_eq!(
                error.to_string(),
                expected["message"],
                "message {}",
                case.id
            );
        } else {
            assert_eq!(observe(&got.unwrap()), case.result.unwrap(), "{}", case.id);
        }
    }
}
