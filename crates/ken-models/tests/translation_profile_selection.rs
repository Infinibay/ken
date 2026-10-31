#[path = "support/translation_oracle.rs"]
mod translation_oracle;

#[test]
fn dnnl_selects_the_complete_independently_observed_original() {
    let original = translation_oracle::for_backend("linux", "x86_64", "DNNL", "DNNL")
        .expect("independent DNNL original");
    assert_eq!(original["platform"], "Linux");
    assert_eq!(original["architecture"], "x86_64");
    assert_eq!(original["cases"].as_array().unwrap().len(), 29);
    assert_eq!(original["results"].as_array().unwrap().len(), 29);
    let lexicon = original["results"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["id"] == "spanish-lexicon")
        .unwrap();
    assert_eq!(
        lexicon["calls"][0]["output"],
        "Look for the class that contains this method."
    );
}

#[test]
fn mkl_requires_its_own_independently_observed_original() {
    let error = translation_oracle::for_backend("linux", "x86_64", "MKL", "MKL")
        .expect_err("DNNL observations cannot qualify MKL");
    assert!(error.contains("independent original translation oracle required"));
    assert!(error.contains("MKL/MKL"));
}

#[test]
fn mixed_backend_pairs_cannot_borrow_another_original() {
    for (float_backend, int8_backend) in [("DNNL", "MKL"), ("MKL", "DNNL")] {
        let error = translation_oracle::for_backend("linux", "x86_64", float_backend, int8_backend)
            .expect_err("the complete backend pair must match");
        assert!(error.contains("independent original translation oracle required"));
        assert!(error.contains(&format!("{float_backend}/{int8_backend}")));
    }
}

#[test]
fn unknown_platforms_have_no_implicit_translation_original() {
    for (os, arch) in [("windows", "x86_64"), ("linux", "unknown")] {
        let error = translation_oracle::for_backend(os, arch, "DNNL", "DNNL")
            .expect_err("platform must be explicitly registered");
        assert!(error.contains("independent original translation oracle required"));
    }
}

#[test]
fn registry_rejects_duplicate_profiles_and_shared_original_observations() {
    let original: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/translation-reference-profiles.json")).unwrap();
    for relabel in [false, true] {
        let mut registry = original.clone();
        let mut duplicate = registry["profiles"][0].clone();
        if relabel {
            duplicate["float_backend"] = "MKL".into();
            duplicate["int8_backend"] = "MKL".into();
        }
        registry["profiles"].as_array_mut().unwrap().push(duplicate);
        let error = translation_oracle::select_profile(
            &registry,
            "Linux",
            "x86_64",
            if relabel { "MKL" } else { "DNNL" },
            if relabel { "MKL" } else { "DNNL" },
        )
        .expect_err("one original cannot qualify two profiles");
        assert!(error.contains("duplicate translation reference profile or shared observations"));
    }
}
