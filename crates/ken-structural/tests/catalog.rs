use flate2::read::GzDecoder;
use ken_structural::application::catalog::{Catalog, RuleLibrary, SavedRule};
use serde_json::{Value, json};
use sha2::Digest;
use std::{io::Read, path::Path};
fn original() -> Value {
    let bytes = include_bytes!("fixtures/catalog-documents-reference.json.gz");
    assert_eq!(bytes.len(), 117044);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "652d081ddca87d2aa71891efc1cc521c7a6cf5caa64752ead8bfede9e04e81a1"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    serde_json::from_str(&text).unwrap()
}
#[test]
fn native_embedded_catalogue_has_exact_resources_libraries_and_metadata() {
    let expected = original();
    let catalog = Catalog::packaged().unwrap();
    assert_eq!(
        serde_json::to_value(catalog.sources()).unwrap(),
        expected["resources"]
    );
    assert_eq!(
        serde_json::to_value(catalog.libraries()).unwrap(),
        expected["libraries"]
    );
    assert_eq!(
        serde_json::to_value(catalog.rules()).unwrap(),
        expected["rules"]
    );
}
#[test]
fn custom_toml_json_selection_reserved_ids_and_atomic_roundtrip() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let catalog = Catalog::packaged().unwrap();
    std::fs::create_dir_all(root.join(".ken/rules")).unwrap();
    std::fs::write(root.join(".ken/rules/user.toml"),"id='user.value'\nquery='require $unit ENTITY CLASS'\nname='A custom rule'\ntags=['local']\ncollections=['team']\n").unwrap();
    let registry = RuleLibrary::load(root, &catalog, &[]).unwrap();
    let selected = registry
        .select(&["user.value".into()], &["team".into()], &["local".into()])
        .unwrap();
    assert_eq!(selected.len(), 1);
    assert_eq!(selected[0].name, "A custom rule");
    assert!(registry.select(&["missing".into()], &[], &[]).is_err());
    std::fs::write(
        root.join("extra.json"),
        json!({"version":1,"rules":[{"id":"json.value","query":"class(name:\"A\") as x;"}]})
            .to_string(),
    )
    .unwrap();
    assert!(
        RuleLibrary::load(root, &catalog, &["extra.json".into()])
            .unwrap()
            .select(&["json.value".into()], &[], &[])
            .is_ok()
    );
    let custom:SavedRule=serde_json::from_value(json!({"id":"saved.value","query":"require $c ENTITY CLASS","description":"line one\nquote \"two\"","operations":[{"id":"scan","status":"ready","query":"require $x ENTITY CLASS"}]})).unwrap();
    let path = registry.save(root, &custom, false).unwrap();
    assert!(path.ends_with("saved.value.toml"));
    let reloaded = RuleLibrary::load(root, &catalog, &[]).unwrap();
    assert_eq!(
        reloaded.select(&["saved.value".into()], &[], &[]).unwrap()[0],
        custom
    );
    assert!(reloaded.save(root, &custom, false).is_err());
    assert!(reloaded.save(root, &custom, true).is_ok());
    std::fs::write(
        root.join(".ken/rules/shadow.toml"),
        "id='gof.singleton'\nquery='require $x ENTITY CLASS'\n",
    )
    .unwrap();
    assert!(RuleLibrary::load(root, &catalog, &[]).is_err());
    assert!(RuleLibrary::load(root, &catalog, &[Path::new("../outside.toml").into()]).is_err());
}
#[test]
fn catalogue_relations_and_variants_compile_to_native_named_plans() {
    let temp = tempfile::tempdir().unwrap();
    let catalog = Catalog::packaged().unwrap();
    let registry = RuleLibrary::load(temp.path(), &catalog, &[]).unwrap();
    let queries = registry.queries().unwrap();
    assert!(queries.contains_key("singleton"));
    assert!(queries.contains_key("gof.singleton"));
    assert!(queries.keys().any(|id| id.contains('#')));
    assert!(queries.keys().any(|id| id.starts_with("legacy.gof.")));
}
#[test]
fn catalogue_publication_rejects_metadata_symlinks_without_outside_writes() {
    use std::os::unix::fs::symlink;
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    symlink(outside.path(), root.path().join(".ken")).unwrap();
    let clean = tempfile::tempdir().unwrap();
    let catalog = Catalog::packaged().unwrap();
    let registry = RuleLibrary::load(clean.path(), &catalog, &[]).unwrap();
    let rule: SavedRule =
        serde_json::from_value(json!({"id":"new.rule","query":"require $x ENTITY CLASS"})).unwrap();
    assert!(registry.save(root.path(), &rule, false).is_err());
    assert_eq!(std::fs::read_dir(outside.path()).unwrap().count(), 0);
}
