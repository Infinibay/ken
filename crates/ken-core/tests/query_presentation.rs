use ken_core::tool_output::{Document, render};
#[test]
fn query_cells_keep_large_numbers_nested_values_and_real_private_protocol_named_keys() {
    let number = "9".repeat(500);
    let raw = format!(
        "{{\"columns\":[\"large\",\"payload\"],\"rows\":[[{number},{{\"$serde_json::private::Number\":\"123\"}}]],\"measure\":0.125,\"complete\":false}}"
    );
    let value = Document::parse_json(&raw).unwrap();
    let text = render(&value, "ken_find", false);
    assert!(
        text.contains(&format!(
            "row 1:\n  large: {number}\n  payload:\n    $serde_json::private::Number: 123"
        )),
        "{text}"
    );
    assert!(text.contains("measure: 0.125"));
    assert!(text.contains("complete: false"));
    assert_eq!(serde_json::to_string(&value).unwrap(), raw);
}
#[test]
fn compact_check_projection_keeps_uncertainty_and_full_mode_preserves_expandable_fields() {
    let document=Document::parse_json(r#"{"run_id":"r1","status":"unknown","scope":"project","selection":".","created_at":3,"claim":"not proof","complete":false}"#).unwrap();
    let compact = render(&document, "ken_check", false);
    assert_eq!(compact, "run_id: r1\nstatus: unknown\ncomplete: false");
    let full = render(&document, "ken_check", true);
    assert!(full.contains("created_at: 3"));
    assert!(full.contains("claim: not proof"));
    assert!(full.contains("scope: project"));
}
