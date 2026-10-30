use ken_daemon::native::user_model_policy;
use std::collections::BTreeMap;
#[test]
fn explicit_config_directory_wins_over_xdg_and_home_and_invalid_config_degrades_to_default() {
    let root = tempfile::tempdir().unwrap();
    for directory in ["explicit", "xdg/ken", "home/.config/ken"] {
        std::fs::create_dir_all(root.path().join(directory)).unwrap();
    }
    for (directory, model) in [
        ("explicit", "explicit-model"),
        ("xdg/ken", "xdg-model"),
        ("home/.config/ken", "home-model"),
    ] {
        std::fs::write(
            root.path().join(directory).join("config.json"),
            format!("{{\"default_model\":\"{model}\"}}"),
        )
        .unwrap();
    }
    let mut env = BTreeMap::from([
        (
            "KEN_CONFIG_DIR".into(),
            root.path().join("explicit").to_string_lossy().into_owned(),
        ),
        (
            "XDG_CONFIG_HOME".into(),
            root.path().join("xdg").to_string_lossy().into_owned(),
        ),
        (
            "HOME".into(),
            root.path().join("home").to_string_lossy().into_owned(),
        ),
    ]);
    assert_eq!(
        user_model_policy(&env).recommended_model(),
        "explicit-model"
    );
    env.remove("KEN_CONFIG_DIR");
    assert_eq!(user_model_policy(&env).recommended_model(), "xdg-model");
    env.remove("XDG_CONFIG_HOME");
    assert_eq!(user_model_policy(&env).recommended_model(), "home-model");
    std::fs::write(root.path().join("home/.config/ken/config.json"), "not-json").unwrap();
    assert_eq!(
        user_model_policy(&env).recommended_model(),
        ken_models::model_policy::POTION_MODEL
    );
}

#[test]
fn captured_cpu_device_policy_ignores_accelerator_ids_and_unknown_transformer_preferences_stay_cpu()
{
    let env = BTreeMap::from([
        ("KEN_EMBED_DEVICE".into(), " CPU ".into()),
        ("KEN_EMBED_DEVICE_ID".into(), "not-an-id".into()),
    ]);
    let (fast, transformer) = ken_daemon::native::device_requests(&env);
    assert_eq!(fast.preference(), "cpu");
    assert!(fast.invalid_ids());
    assert_eq!(
        fast.providers_for(&["CPUExecutionProvider", "CUDAExecutionProvider"]),
        ["CPUExecutionProvider"]
    );
    assert_eq!(transformer, ken_models::TransformerDeviceRequest::Cpu);
    let (_, unknown) = ken_daemon::native::device_requests(&BTreeMap::from([(
        "KEN_EMBED_DEVICE".into(),
        "unrecognized".into(),
    )]));
    assert_eq!(unknown, ken_models::TransformerDeviceRequest::Cpu);
    let (_, automatic) = ken_daemon::native::device_requests(&BTreeMap::new());
    assert_eq!(automatic, ken_models::TransformerDeviceRequest::Auto);
    let (_, gpu) = ken_daemon::native::device_requests(&BTreeMap::from([(
        "KEN_EMBED_DEVICE".into(),
        "gpu".into(),
    )]));
    assert_eq!(
        gpu,
        ken_models::TransformerDeviceRequest::Auto,
        "original gpu preference permits CPU fallback"
    );
}
