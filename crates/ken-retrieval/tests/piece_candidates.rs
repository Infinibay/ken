use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    EntityKey, Passage, Result, RetrievalError,
    description::{OwnerDescription, describe_owner},
    piece_candidates::{PieceAssembler, PieceCandidate},
    query::CodeMatch,
    source_catalog::SourceCatalog,
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
    catalog: Physical,
    matches: Vec<CodeMatch>,
    piece_kind: String,
    limit: usize,
    direct: Option<Direct>,
}
#[derive(Deserialize)]
struct Physical {
    files: BTreeMap<String, Vec<u8>>,
    owners: Vec<Owner>,
}
#[derive(Deserialize)]
struct Owner {
    key: EntityKey,
    passages: Vec<Passage>,
}
#[derive(Deserialize)]
struct Direct {
    kind: String,
    path: String,
    entity: Option<EntityKey>,
    members: Vec<usize>,
    #[serde(default)]
    overrides: BTreeMap<usize, Value>,
}
fn fixture(physical: Physical) -> (tempfile::TempDir, Arc<SourceCatalog>) {
    let directory = tempfile::tempdir().unwrap();
    for (name, bytes) in physical.files {
        let p = directory.path().join(name);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, bytes).unwrap();
    }
    let context = DiscoveryContext {
        cwd: directory.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(directory.path(), &context).unwrap();
    let source = Arc::new(SourceAuthority::new(&paths).unwrap());
    let catalog = Arc::new(
        SourceCatalog::new(
            source,
            physical
                .owners
                .into_iter()
                .map(|o| (o.key, o.passages))
                .collect(),
        )
        .unwrap(),
    );
    (directory, catalog)
}
#[test]
fn complete_piece_membership_and_generation_cache() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/piece-reference-assembly.json")).unwrap();
    assert_eq!(corpus.cases.len(), 45);
    for case in corpus.cases {
        let (_directory, catalog) = fixture(case.input.catalog);
        let mut assembler = PieceAssembler::new(catalog.clone());
        let before = case.input.matches.clone();
        let got = (|| -> Result<Value> {
            if let Some(direct) = case.input.direct {
                let mut members = direct
                    .members
                    .iter()
                    .map(|i| describe_owner(&catalog.owners()[*i].1).map(Arc::new))
                    .collect::<Result<Vec<_>>>()?;
                for (i, updates) in direct.overrides {
                    let mut value = serde_json::to_value(members[i].as_ref())?;
                    value
                        .as_object_mut()
                        .unwrap()
                        .extend(updates.as_object().unwrap().clone());
                    members[i] = Arc::new(serde_json::from_value::<OwnerDescription>(value)?);
                }
                let piece = PieceCandidate::new(
                    direct.kind,
                    direct.path,
                    direct.entity,
                    members,
                    case.input.matches.clone(),
                )?;
                return Ok(json!({"piece":piece,"declaration":piece.declaration()}));
            }
            let pieces = assembler.assemble(
                &case.input.matches,
                &case.input.piece_kind,
                case.input.limit,
            )?;
            let again = assembler.assemble(
                &case.input.matches,
                &case.input.piece_kind,
                case.input.limit,
            )?;
            let reused = pieces.iter().zip(&again).all(|(a, b)| {
                a.members()
                    .iter()
                    .zip(b.members())
                    .all(|(a, b)| Arc::ptr_eq(a, b))
            });
            Ok(
                json!({"declarations":pieces.iter().map(|p|p.declaration()).collect::<Vec<_>>(),"pieces":pieces,"cache_size":assembler.cache_len(),"reused":reused,"unchanged":case.input.matches==before}),
            )
        })();
        if case.kind == "assembly_admission" {
            assert!(
                matches!(got, Err(RetrievalError::Invalid(_))),
                "admission {}",
                case.id
            );
        } else if let Some(expected) = case.error {
            assert_eq!(
                got.unwrap_err().to_string(),
                expected["message"],
                "{}",
                case.id
            );
        } else {
            assert_eq!(got.unwrap(), case.result.unwrap(), "{}", case.id);
        }
    }
}
#[test]
fn independent_catalogs_cannot_share_a_description_cache() {
    let mut corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/piece-reference-assembly.json")).unwrap();
    let input = corpus.cases.remove(0).input;
    let (_directory, catalog) = fixture(input.catalog);
    let other =
        Arc::new(SourceCatalog::new(catalog.source().clone(), catalog.owners().to_vec()).unwrap());
    let a = PieceAssembler::new(catalog)
        .assemble(&input.matches, "class", 10)
        .unwrap();
    let b = PieceAssembler::new(other)
        .assemble(&input.matches, "class", 10)
        .unwrap();
    assert!(!Arc::ptr_eq(&a[0].members()[0], &b[0].members()[0]));
    assert_eq!(a[0].members()[0], b[0].members()[0]);
}
