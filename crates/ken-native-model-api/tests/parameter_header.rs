use ken_native_model_api::validate_parameter_header;
#[test]
fn bounded_headers_reject_duplicate_names_offsets_and_unsupported_tensor_data() {
    let valid =
        br#"{"w":{"dtype":"F32","shape":[2],"data_offsets":[0,8]},"__metadata__":{"format":"pt"}}"#;
    validate_parameter_header(valid, 8).unwrap();
    for invalid in [
        r#"{"w":{"dtype":"F32","shape":[2],"data_offsets":[0,8]},"w":{"dtype":"F32","shape":[2],"data_offsets":[0,8]}}"#,
        r#"{"w":{"dtype":"I64","shape":[1],"data_offsets":[0,8]}}"#,
        r#"{"w":{"dtype":"F32","shape":[2],"data_offsets":[1,9]}}"#,
        r#"{"w":{"dtype":"F32","shape":[1,1,2],"data_offsets":[0,8]}}"#,
        r#"{"w":{"dtype":"F32","shape":[2],"data_offsets":[0,8]},"v":{"dtype":"F32","shape":[2],"data_offsets":[4,12]}}"#,
        r#"{"w":{"dtype":"F32","shape":[18446744073709551615,2],"data_offsets":[0,8]}}"#,
    ] {
        assert!(
            validate_parameter_header(invalid.as_bytes(), 8).is_err(),
            "{invalid}"
        );
    }
    assert!(validate_parameter_header(valid, 9).is_err());
    assert!(validate_parameter_header(b"{}", 0).is_err());
}
