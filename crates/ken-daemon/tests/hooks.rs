use ken_daemon::hooks::{
    HookCommand, canonical_tool_name, classify_tool, extract_last_assistant_text, normalize,
};
use serde_json::json;
#[test]
fn hooks_normalize_both_host_payloads_without_leaking_tool_output_into_context() {
    let normalized=normalize(HookCommand::ToolPost,&json!({"session_id":"s","tool_name":"functions.apply_patch","tool_input":{"patch":"*** Update File: src/a.rs"},"tool_response":{"ok":false},"success":false})).unwrap();
    assert_eq!(normalized.path, "/tools/post");
    assert_eq!(
        normalized.payload,
        json!({"session_id":"s","tool":"functions.apply_patch","input":{"patch":"*** Update File: src/a.rs"},"output":{"ok":false},"success":false})
    );
    let direct=normalize(HookCommand::Stop,&json!({"session_id":"s","last_assistant_message":"direct assistant text","transcript_path":"/missing"})).unwrap();
    assert_eq!(direct.payload["assistant_text"], "direct assistant text");
    assert!(normalize(HookCommand::UserPrompt, &json!({"session_id":12})).is_none());
    assert_eq!(
        normalize(
            HookCommand::UserPrompt,
            &json!({"session_id":"s","prompt":""})
        )
        .unwrap()
        .payload["prompt"],
        ""
    );
}
#[test]
fn canonical_tool_classification_keeps_neutral_unknowns_and_asymmetric_stem_matching() {
    for (name, input, event, path) in [
        (
            "functions.apply_patch",
            json!({"patch":"*** Update File: src/a.rs\n@@"}),
            "edit",
            Some("src/a.rs"),
        ),
        (
            "functions.exec_command",
            json!({"cmd":"cat src/a.rs"}),
            "read",
            Some("src/a.rs"),
        ),
        (
            "functions.exec_command",
            json!({"cmd":"cargo check","workdir":"/repo"}),
            "read",
            Some("/repo"),
        ),
        ("code_search", json!({"path":"src"}), "read", Some("src")),
        ("add_note", json!({"text":"notes"}), "neutral", None),
        (
            "thing_edit",
            json!({"path":"a.rs"}),
            "neutral",
            Some("a.rs"),
        ),
        ("write_file", json!({"path":"a.rs"}), "edit", Some("a.rs")),
    ] {
        let classified = classify_tool(name, &input);
        assert_eq!(
            (classified.event.as_str(), classified.target.as_deref()),
            (event, path),
            "{name}"
        );
    }
    assert_eq!(canonical_tool_name(" some.namespace.Read "), "read");
}
#[test]
fn transcript_tail_is_bounded_tolerates_partial_lines_and_selects_last_assistant_text_blocks() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("transcript.jsonl");
    let mut text = format!(
        "{{\"type\":\"user\",\"padding\":\"{}\"}}\n",
        "x".repeat(70000)
    );
    text.push_str("{\"type\":\"assistant\",\"message\":{\"content\":\"old\"}}\nmalformed\n");
    text.push_str("{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"one\"},{\"type\":\"tool_use\",\"text\":\"hidden\"},{\"type\":\"text\",\"text\":\"two🦀\"}]}}\n");
    text.push_str("{\"type\":\"user\",\"message\":{\"content\":\"later\"}}\n");
    std::fs::write(&path, text).unwrap();
    assert_eq!(extract_last_assistant_text(&path, 50000), "one\ntwo🦀");
    assert_eq!(
        extract_last_assistant_text(&dir.path().join("missing"), 50000),
        ""
    );
}
