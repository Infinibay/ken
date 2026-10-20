use ken_models::FastEmbedDeviceRequest;

#[test]
fn preference_normalization_and_targeted_provider_order_match_original() {
    let available = [
        "ROCMExecutionProvider",
        "CoreMLExecutionProvider",
        "CUDAExecutionProvider",
        "TensorrtExecutionProvider",
    ];
    for (raw, expected) in [
        (None, "auto"),
        (Some(" AUTO "), "auto"),
        (Some("GPU"), "gpu"),
        (Some("cuda"), "gpu"),
        (Some("cpu"), "cpu"),
        (Some("rocm"), "auto"),
        (Some("unknown"), "auto"),
    ] {
        let request = FastEmbedDeviceRequest::from_inputs(raw, None);
        assert_eq!(request.preference(), expected);
        let wanted = if expected == "cpu" {
            vec!["CPUExecutionProvider"]
        } else {
            vec![
                "CUDAExecutionProvider",
                "ROCMExecutionProvider",
                "CPUExecutionProvider",
            ]
        };
        assert_eq!(request.providers_for(&available), wanted);
        assert_eq!(
            request.providers_for(&["CoreMLExecutionProvider", "TensorrtExecutionProvider"]),
            vec!["CPUExecutionProvider"]
        );
    }
}

#[test]
fn device_ids_retain_validation_and_empty_list_without_claiming_application() {
    for (raw, expected) in [
        (None, None),
        (Some("  "), None),
        (Some("0, 1,,2"), Some(vec!["0", "1", "2"])),
        (Some(",,"), Some(vec![])),
        (Some("-1,+2,1_0"), Some(vec!["-1", "+2", "1_0"])),
        (
            Some("9999999999999999999999999999999999999"),
            Some(vec!["9999999999999999999999999999999999999"]),
        ),
        (Some("١,２"), Some(vec!["١", "２"])),
    ] {
        let request = FastEmbedDeviceRequest::from_inputs(Some("gpu"), raw);
        assert_eq!(
            request
                .requested_ids()
                .map(|ids| ids.iter().map(String::as_str).collect::<Vec<_>>()),
            expected
        );
        assert!(!request.invalid_ids());
        assert!(!request.device_ids_applied());
    }
    for raw in ["x", "0,x", "1.5", "1__0", "_1", "+", "0,\t,1"] {
        let request = FastEmbedDeviceRequest::from_inputs(None, Some(raw));
        assert!(request.invalid_ids(), "{raw}");
        assert!(request.requested_ids().is_none());
        assert!(!request.device_ids_applied());
    }
}
