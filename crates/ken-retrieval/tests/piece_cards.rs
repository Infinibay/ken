use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    EntityKey, Passage,
    piece_cards::{
        CARD_PROJECTION, PieceCard, build_card, build_piece_cards, canonical_card, card_text,
        validate_card,
    },
    query::CodeMatch,
    source_catalog::{PieceIdentity, SourceCatalog},
    source_snapshot::{SourceAuthority, SourceResult},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    sync::Arc,
};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    result: Option<Value>,
    error: Option<Value>,
}
#[derive(Deserialize)]
struct Input {
    catalog: Physical,
    #[serde(default)]
    matches: Vec<CodeMatch>,
    piece_kind: String,
    query: PythonText,
    primary: Option<Value>,
    #[serde(default)]
    supporting: Vec<EntityKey>,
    limit: Option<usize>,
    card_updates: Option<Value>,
    mutation: Option<Mutation>,
    check_disk: Option<bool>,
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
struct Mutation {
    op: String,
    path: String,
    bytes: Option<Vec<u8>>,
}
fn update(card: &mut PieceCard, updates: &Value) {
    let mut value = serde_json::to_value(&*card).unwrap();
    for (field, v) in updates["card"].as_object().into_iter().flatten() {
        value[field] = v.clone();
    }
    for (field, v) in updates["unit"].as_object().into_iter().flatten() {
        value["unit"][field] = v.clone();
    }
    for (index, fields) in updates["excerpts"].as_object().into_iter().flatten() {
        for (field, v) in fields.as_object().unwrap() {
            value["excerpts"][index.parse::<usize>().unwrap()][field] = v.clone();
        }
    }
    if updates["duplicate"] == true {
        let first = value["excerpts"][0].clone();
        value["excerpts"].as_array_mut().unwrap().push(first);
    }
    *card = serde_json::from_value(value).unwrap();
}
#[test]
fn fixed_card_projection_preserves_roles_lines_and_limits() {
    let raw = if let Some(directory) = std::env::var_os("KEN_PIECE_REFERENCE_DIR") {
        fs::read_to_string(std::path::PathBuf::from(directory).join("piece-reference-cards.json"))
            .unwrap()
    } else {
        use std::io::Read;
        let mut raw = String::new();
        flate2::read::GzDecoder::new(
            &include_bytes!("fixtures/piece-reference-cards-linux-x86_64.json.gz")[..],
        )
        .read_to_string(&mut raw)
        .unwrap();
        raw
    };
    let corpus: Corpus = serde_json::from_str(&raw).unwrap();
    assert_eq!(corpus.cases.len(), 60);
    for case in corpus.cases {
        let temporary = tempfile::tempdir().unwrap();
        let root = temporary.path().join("project");
        fs::create_dir(&root).unwrap();
        for (name, bytes) in &case.input.catalog.files {
            let file = root.join(name);
            fs::create_dir_all(file.parent().unwrap()).unwrap();
            fs::write(file, bytes).unwrap();
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
            .catalog
            .owners
            .into_iter()
            .map(|o| (o.key, o.passages))
            .collect();
        let catalog = SourceCatalog::new(source, owners).unwrap();
        let observed = (|| -> SourceResult<Value> {
            let mut cards = if let Some(primary) = case.input.primary {
                let primary = if let Some(path) = primary.as_str() {
                    PieceIdentity::Path(path.into())
                } else {
                    PieceIdentity::Entity(serde_json::from_value(primary).unwrap())
                };
                vec![build_card(
                    &primary,
                    &case.input.piece_kind,
                    &case.input.supporting,
                    &case.input.query,
                    &catalog,
                )?]
            } else {
                build_piece_cards(
                    &case.input.matches,
                    &case.input.piece_kind,
                    &case.input.query,
                    &catalog,
                    case.input.limit.unwrap_or(20),
                )?
            };
            // Builders always produce distinct physical lines, even when support repeats.
            for card in &cards {
                let mut seen = BTreeSet::new();
                for excerpt in &card.excerpts {
                    for line in excerpt.start_line..=excerpt.end_line {
                        assert!(seen.insert(line), "duplicate physical line: {}", case.id);
                    }
                }
                assert!(seen.len() <= 64 && card.excerpts.len() <= 4, "{}", case.id);
                assert!(canonical_card(card).chars().count() <= 12000, "{}", case.id);
            }
            if let Some(updates) = case.input.card_updates {
                update(&mut cards[0], &updates);
            }
            if let Some(mutation) = case.input.mutation {
                let target = root.join(&mutation.path);
                match mutation.op.as_str() {
                    "write" => fs::write(target, mutation.bytes.unwrap()).unwrap(),
                    "symlink" => {
                        let outside = temporary.path().join("outside.py");
                        fs::write(&outside, "outside fixture\n").unwrap();
                        fs::remove_file(&target).unwrap();
                        std::os::unix::fs::symlink(outside, target).unwrap();
                    }
                    "replace-root" => {
                        fs::rename(&root, temporary.path().join("old-project")).unwrap();
                        fs::create_dir(&root).unwrap();
                        fs::create_dir_all(target.parent().unwrap()).unwrap();
                        fs::write(target, mutation.bytes.unwrap()).unwrap();
                    }
                    _ => panic!("unsupported input-only mutation"),
                }
            }
            for card in &cards {
                validate_card(card, &catalog, case.input.check_disk.unwrap_or(true))?;
            }
            let canonical: Vec<_> = cards.iter().map(canonical_card).collect();
            let texts: Vec<_> = cards.iter().map(card_text).collect();
            let characters: Vec<_> = canonical.iter().map(|s| s.chars().count()).collect();
            Ok(
                json!({"cards":cards,"texts":texts,"canonical":canonical,"characters":characters,"projection":CARD_PROJECTION}),
            )
        })();
        if let Some(expected) = case.error {
            let error = observed
                .err()
                .unwrap_or_else(|| panic!("expected original error {}", case.id));
            assert_eq!(error.kind(), expected["type"], "kind {}", case.id);
            assert_eq!(
                error.to_string(),
                expected["message"],
                "message {}",
                case.id
            );
        } else {
            assert_eq!(observed.unwrap(), case.result.unwrap(), "{}", case.id);
        }
    }
}

#[test]
fn card_support_must_belong_to_the_catalog_generation() {
    let raw: BTreeMap<String, Box<serde_json::value::RawValue>> =
        serde_json::from_str(include_str!("fixtures/piece-inputs-cards.json")).unwrap();
    let cases: Vec<Box<serde_json::value::RawValue>> =
        serde_json::from_str(raw["cases"].get()).unwrap();
    let case: BTreeMap<String, Box<serde_json::value::RawValue>> =
        serde_json::from_str(cases[0].get()).unwrap();
    let input: Input = serde_json::from_str(case["input"].get()).unwrap();
    let temporary = tempfile::tempdir().unwrap();
    for (name, bytes) in &input.catalog.files {
        let path = temporary.path().join(name);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, bytes).unwrap();
    }
    let context = DiscoveryContext {
        cwd: temporary.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(temporary.path(), &context).unwrap();
    let source = Arc::new(SourceAuthority::new(&paths).unwrap());
    let catalog = SourceCatalog::new(
        source,
        input
            .catalog
            .owners
            .into_iter()
            .map(|o| (o.key, o.passages))
            .collect(),
    )
    .unwrap();
    assert!(!input.matches.is_empty());
    assert!(
        build_piece_cards(
            &input.matches,
            &input.piece_kind,
            &input.query,
            &catalog,
            20
        )
        .is_ok()
    );
    for change in [
        "stale-match",
        "stale-evidence",
        "foreign-evidence",
        "empty-evidence",
        "unknown-owner",
    ] {
        let mut support = input.matches.clone();
        match change {
            "stale-match" => {
                support[0].source_hash = "stale".into();
                for p in &mut support[0].evidence {
                    p.source_hash = "stale".into();
                }
            }
            "stale-evidence" => support[0].evidence[0].source_hash = "stale".into(),
            "foreign-evidence" => support[0].evidence[0].entity.qualname = Some("foreign".into()),
            "empty-evidence" => support[0].evidence.clear(),
            _ => support[0].entity.qualname = Some("unknown".into()),
        }
        assert!(
            build_piece_cards(&support, &input.piece_kind, &input.query, &catalog, 20).is_err(),
            "{change}"
        );
        let mut assembler = ken_retrieval::piece_candidates::PieceAssembler::new(Arc::new(
            SourceCatalog::new(catalog.source().clone(), catalog.owners().to_vec()).unwrap(),
        ));
        assert!(
            assembler.assemble(&support, &input.piece_kind, 10).is_err(),
            "assembly {change}"
        );
    }
}
