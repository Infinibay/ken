use ken_native_model_api::{
    HandleRegistry, TransformerCall, TransformerControl, TransformerControlRequest,
};
#[test]
fn cpu_conversion_is_an_explicit_control_without_a_fabricated_tensor_batch() {
    let request = TransformerControlRequest {
        schema: 1,
        operation: TransformerControl::CpuFloat32,
    };
    request.validate().unwrap();
    let raw = serde_json::to_string(&request).unwrap();
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&raw).unwrap(),
        serde_json::json!({"schema":1,"operation":"cpu_float32"})
    );
    assert!(matches!(
        serde_json::from_str::<TransformerCall>(&raw).unwrap(),
        TransformerCall::Control(_)
    ));
    assert!(
        serde_json::from_str::<TransformerCall>(
            r#"{"schema":1,"operation":"cpu_float32","batch":{}}"#
        )
        .is_err()
    );
    assert!(
        TransformerControlRequest {
            schema: 2,
            ..request
        }
        .validate()
        .is_err()
    );
    let mut handles = HandleRegistry::default();
    let handle = handles.insert("gpu").unwrap();
    *handles.get_mut(handle).unwrap() = "cpu";
    assert_eq!(*handles.get(handle).unwrap(), "cpu");
    handles.remove(handle).unwrap();
    assert!(handles.get_mut(handle).is_err());
}
