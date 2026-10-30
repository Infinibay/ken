use ken_hosts::{
    HookHost, HostSelection, NativeCommand, codex, deepseek, detect, hooks, jsonc, skills,
};
use serde_json::{Value, json};
use std::path::Path;
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/hosts-domain.json")).unwrap()
}
fn command() -> NativeCommand {
    NativeCommand::new("ken", vec![]).unwrap()
}
#[test]
fn native_hook_templates_match_original_merges_and_idempotence() {
    for c in fixture()["hooks"].as_array().unwrap() {
        let host = if c["host"] == "claude" {
            HookHost::Claude
        } else {
            HookHost::Codex
        };
        let input = c.get("input").filter(|v| !v.is_null());
        let (merged, touched) = hooks::merge(input, host, &command()).unwrap();
        assert_eq!(merged, c["merged"]);
        assert_eq!(json!(touched), c["touched"]);
        let (again, twice) = hooks::merge(Some(&merged), host, &command()).unwrap();
        assert_eq!(again, c["again"]);
        assert_eq!(json!(twice), c["twice"]);
        assert_eq!(
            hooks::remove_generated(&merged, host, &command()).unwrap(),
            c["removed"]
        );
    }
}
#[test]
fn jsonc_baseline_matches_original_and_native_string_safety_is_explicit() {
    let f = fixture();
    for c in f["jsonc"].as_array().unwrap().iter().take(2) {
        assert_eq!(
            jsonc::parse(c["input"].as_str().unwrap()).unwrap(),
            c["result"]
        );
    }
    let raw = f["jsonc"][2]["input"].as_str().unwrap();
    assert_ne!(
        f["jsonc"][2]["result"]["literal"], ",}",
        "original unsafe observation remains unchanged"
    );
    let native = jsonc::parse(raw).unwrap();
    assert_eq!(native["literal"], ",}");
    assert_eq!(native["another"], ", ]");
    assert!(jsonc::parse(f["jsonc"][3]["input"].as_str().unwrap()).is_err());
}
#[test]
fn codex_appending_preserves_prefix_and_removal_preserves_edited_registration() {
    let f = fixture();
    for c in f["codex"].as_array().unwrap().iter().take(2) {
        assert_eq!(
            codex::append(c["input"].as_str().unwrap(), &command()).unwrap(),
            c["appended"]
        );
    }
    let exact = f["codex"][2]["input"].as_str().unwrap();
    assert_eq!(
        codex::remove_owned(exact, &command()).unwrap(),
        f["codex"][2]["removed"]
    );
    let edited = f["codex"][3]["input"].as_str().unwrap();
    assert_ne!(
        f["codex"][3]["removed"], edited,
        "unsafe original fixture retained"
    );
    assert_eq!(codex::remove_owned(edited, &command()).unwrap(), edited);
    assert!(codex::has_registration("[mcp_servers.\"ken\"]\ncommand='other'\n").unwrap());
    assert!(!codex::has_registration("note='[mcp_servers.ken]'\n").unwrap());
}
#[test]
fn host_detection_and_shared_skill_destinations_match_original() {
    let f = fixture();
    for case in f["detection"].as_array().unwrap() {
        let d = tempfile::tempdir().unwrap();
        for name in case["paths"].as_array().unwrap() {
            let path = d.path().join(name.as_str().unwrap());
            if path.extension().is_some() {
                std::fs::create_dir_all(path.parent().unwrap()).unwrap();
                std::fs::write(path, "{}").unwrap();
            } else {
                std::fs::create_dir_all(path).unwrap();
            }
        }
        assert_eq!(
            json!(detect(d.path(), HostSelection::default()).unwrap().flags()),
            case["result"]
        );
    }
    for case in f["destinations"].as_array().unwrap() {
        let selection: HostSelection = serde_json::from_value(case["selection"].clone()).unwrap();
        assert_eq!(json!(skills::destinations(selection)), case["result"]);
    }
}
#[test]
fn native_executable_declarations_replace_python_and_quote_shell_arguments() {
    let command = NativeCommand::new(
        "/opt/Ken tool's/bin/ken",
        vec!["--resources".into(), "/assets/a b.json".into()],
    )
    .unwrap();
    let root = Path::new("/fixture/project with quotes");
    let entry = deepseek::entry(root, &command).unwrap();
    assert_eq!(entry["config"]["command"], "/opt/Ken tool's/bin/ken");
    assert_eq!(
        entry["config"]["args"],
        json!([
            "--resources",
            "/assets/a b.json",
            "mcp",
            "/fixture/project with quotes"
        ])
    );
    assert_eq!(entry["config"]["cwd"], "/fixture/project with quotes");
    assert!(!entry.to_string().contains("python"));
    let f = fixture();
    assert_eq!(
        deepseek::launch_command(Path::new("/fixture/project's path")),
        f["deepseek"]["launch"]
    );
    let (merged, _) = hooks::merge(None, HookHost::Codex, &command).unwrap();
    let hook = merged["hooks"]["Stop"][0]["hooks"][0]["command"]
        .as_str()
        .unwrap();
    assert!(hook.contains("'\"'\"'"));
    assert!(hook.contains("'/assets/a b.json'"));
    assert!(NativeCommand::new("bad\0command", vec![]).is_err());
}
