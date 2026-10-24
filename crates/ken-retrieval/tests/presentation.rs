use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    EntityKey, Passage,
    json_transport::python_strings,
    piece_cards::{PieceCard, build_card, build_piece_cards},
    presentation::{present, present_cards},
    query::{CodeMatch, SearchRequest},
    source_catalog::{PieceIdentity, SourceCatalog},
    source_snapshot::SourceAuthority,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::Value;
use std::{collections::BTreeMap, fs, sync::Arc};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    result: Observation,
}
#[derive(Deserialize)]
struct Observation {
    response: Response,
    characters: usize,
}
#[derive(Debug, PartialEq, Deserialize)]
struct Response {
    query: PythonText,
    #[serde(flatten)]
    body: BTreeMap<String, Value>,
}
#[derive(Deserialize)]
struct Input {
    operation: String,
    profile_version: String,
    request: SearchRequest,
    matches: Vec<CodeMatch>,
    files: Option<BTreeMap<String, Vec<u8>>>,
    catalog: Option<Physical>,
    piece_kind: Option<String>,
    query: Option<PythonText>,
    primary: Option<Value>,
    #[serde(default)]
    supporting: Vec<EntityKey>,
    limit: Option<usize>,
    card_updates: Option<Value>,
    mutation: Option<Mutation>,
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
    bytes: Vec<u8>,
}
fn update(card: &mut PieceCard, updates: &Value) {
    let mut value = serde_json::to_value(&*card).unwrap();
    for (key, v) in updates["card"].as_object().into_iter().flatten() {
        value[key] = v.clone();
    }
    for (key, v) in updates["unit"].as_object().into_iter().flatten() {
        value["unit"][key] = v.clone();
    }
    for (index, fields) in updates["excerpts"].as_object().into_iter().flatten() {
        for (key, v) in fields.as_object().unwrap() {
            value["excerpts"][index.parse::<usize>().unwrap()][key] = v.clone();
        }
    }
    if updates["duplicate"] == true {
        let first = value["excerpts"][0].clone();
        value["excerpts"].as_array_mut().unwrap().push(first);
    }
    *card = serde_json::from_value(value).unwrap();
}
#[test]
fn presentation_quotes_current_whole_lines_with_exact_identity() {
    let raw = if let Some(directory) = std::env::var_os("KEN_PIECE_REFERENCE_DIR") {
        fs::read_to_string(
            std::path::PathBuf::from(directory).join("piece-reference-presentation.json"),
        )
        .unwrap()
    } else {
        use std::io::Read;
        let mut raw = String::new();
        flate2::read::GzDecoder::new(
            &include_bytes!("fixtures/piece-reference-presentation-linux-x86_64.json.gz")[..],
        )
        .read_to_string(&mut raw)
        .unwrap();
        raw
    };
    let corpus: Corpus = serde_json::from_str(&python_strings(&raw).unwrap()).unwrap();
    assert_eq!(corpus.cases.len(), 117);
    for case in corpus.cases {
        let temporary = tempfile::tempdir().unwrap();
        let root = temporary.path().join("project");
        fs::create_dir(&root).unwrap();
        let data = case.input;
        let files = data
            .files
            .as_ref()
            .unwrap_or_else(|| &data.catalog.as_ref().unwrap().files);
        for (name, bytes) in files {
            let target = root.join(name);
            fs::create_dir_all(target.parent().unwrap()).unwrap();
            fs::write(target, bytes).unwrap();
        }
        let context = DiscoveryContext {
            cwd: root.clone(),
            forced_root: None,
            home: None,
        };
        let paths = ProjectPaths::at(&root, &context).unwrap();
        let authority = Arc::new(SourceAuthority::new(&paths).unwrap());
        let mut catalog = None;
        let mut cards = Vec::new();
        if data.operation == "cards" {
            let physical = data.catalog.unwrap();
            catalog = Some(
                SourceCatalog::new(
                    authority.clone(),
                    physical
                        .owners
                        .into_iter()
                        .map(|o| (o.key, o.passages))
                        .collect(),
                )
                .unwrap(),
            );
            let catalog = catalog.as_ref().unwrap();
            let kind = data.piece_kind.as_deref().unwrap();
            let query = data.query.as_ref().unwrap();
            cards = if let Some(primary) = data.primary {
                let primary = if let Some(path) = primary.as_str() {
                    PieceIdentity::Path(path.into())
                } else {
                    PieceIdentity::Entity(serde_json::from_value(primary).unwrap())
                };
                vec![build_card(&primary, kind, &data.supporting, query, catalog).unwrap()]
            } else {
                build_piece_cards(
                    &data.matches,
                    kind,
                    query,
                    catalog,
                    data.limit.unwrap_or(20),
                )
                .unwrap()
            };
            if let Some(updates) = data.card_updates {
                update(&mut cards[0], &updates);
            }
        }
        if let Some(mutation) = data.mutation {
            let target = root.join(mutation.path);
            match mutation.op.as_str() {
                "write" => fs::write(target, mutation.bytes).unwrap(),
                "delete" => fs::remove_file(target).unwrap(),
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
                    fs::write(target, mutation.bytes).unwrap();
                }
                _ => panic!("unsupported input-only mutation"),
            }
        }
        let mut response = if data.operation == "cards" {
            present_cards(
                &cards,
                &data.request,
                catalog.as_ref().unwrap(),
                &data.profile_version,
            )
            .unwrap()
        } else {
            present(
                &data.matches,
                &authority,
                &data.request,
                &data.profile_version,
            )
            .unwrap()
        };
        for warning in &mut response.warnings {
            *warning = warning
                .replace(root.to_str().unwrap(), "{project}")
                .replace(temporary.path().to_str().unwrap(), "{scenario}");
        }
        let actual: Response = serde_json::from_str(
            &python_strings(&serde_json::to_string(&response).unwrap()).unwrap(),
        )
        .unwrap();
        assert_eq!(actual, case.result.response, "response {}", case.id);
        assert_eq!(
            response.python_characters(),
            case.result.characters,
            "characters {}",
            case.id
        );
    }
}
