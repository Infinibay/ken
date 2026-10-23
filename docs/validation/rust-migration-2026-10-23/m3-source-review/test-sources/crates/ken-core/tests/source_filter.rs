//! Public membership decisions compared with independently captured Python values.
use ken_core::source_filter::SourceFilter;
use serde_json::Value;
use std::{fs, path::Path};

fn populate(root: &Path, case: &Value) {
    for field in ["files", "byte_files"] {
        if let Some(files) = case[field].as_object() {
            for (name, content) in files {
                let path = root.join(name);
                fs::create_dir_all(path.parent().unwrap()).unwrap();
                let text = content.as_str().unwrap();
                let bytes = if field == "files" {
                    text.as_bytes().to_vec()
                } else {
                    (0..text.len())
                        .step_by(2)
                        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
                        .collect()
                };
                fs::write(path, bytes).unwrap();
            }
        }
    }
}

#[test]
fn original_all_builtin_scoped_negation_unicode_and_escaped_pattern_decisions() {
    let original: Value =
        serde_json::from_str(include_str!("fixtures/source-discovery/reference.json")).unwrap();
    let definitions = original["definitions"].as_array().unwrap();
    let captures = original["cases"].as_array().unwrap();
    let mut comparisons = 0;
    for (case, expected) in definitions.iter().zip(captures) {
        assert_eq!(case["id"], expected["id"]);
        let temp = tempfile::tempdir().unwrap();
        populate(temp.path(), case);
        let mut filter = SourceFilter::new(temp.path()).unwrap();
        for (query, ignored) in case["queries"]
            .as_array()
            .unwrap()
            .iter()
            .zip(expected["ignored"].as_array().unwrap())
        {
            let path = query["path"].as_str().unwrap();
            let actual = filter
                .is_ignored(Path::new(path), query["is_dir"].as_bool().unwrap())
                .unwrap();
            assert_eq!(
                actual,
                ignored.as_bool().unwrap(),
                "case={} path={path}",
                case["id"]
            );
            comparisons += 1;
        }
    }
    assert_eq!(comparisons, 270);
}

#[test]
fn reviewed_original_braces_character_wildcards_and_directory_precedence() {
    let original: Value = serde_json::from_str(include_str!(
        "fixtures/source-discovery/reference-review.json"
    ))
    .unwrap();
    for (case, expected) in original["definitions"]
        .as_array()
        .unwrap()
        .iter()
        .zip(original["cases"].as_array().unwrap())
    {
        let temp = tempfile::tempdir().unwrap();
        populate(temp.path(), case);
        let mut filter = SourceFilter::new(temp.path()).unwrap();
        for (query, ignored) in case["queries"]
            .as_array()
            .unwrap()
            .iter()
            .zip(expected["ignored"].as_array().unwrap())
        {
            assert_eq!(
                filter
                    .is_ignored(
                        Path::new(query["path"].as_str().unwrap()),
                        query["is_dir"].as_bool().unwrap()
                    )
                    .unwrap(),
                ignored.as_bool().unwrap(),
                "case={} query={query}",
                case["id"]
            );
        }
    }
}

#[test]
fn descending_ranges_and_dangling_escapes_are_errors_but_unclosed_classes_are_noops() {
    for rule in ["a[z-a].py", "a\\", "!", "a[a--b].py"] {
        let temp = tempfile::tempdir().unwrap();
        fs::write(temp.path().join(".gitignore"), rule).unwrap();
        let mut filter = SourceFilter::new(temp.path()).unwrap();
        assert!(
            filter.is_ignored(Path::new("az.py"), false).is_err(),
            "rule={rule}"
        );
    }
    for rule in ["a[.py", "a[].py", "a[!].py"] {
        let temp = tempfile::tempdir().unwrap();
        fs::write(temp.path().join(".gitignore"), rule).unwrap();
        let mut filter = SourceFilter::new(temp.path()).unwrap();
        assert!(
            !filter.is_ignored(Path::new("az.py"), false).unwrap(),
            "rule={rule}"
        );
    }
}

#[test]
fn root_barriers_cannot_be_overridden_but_nested_git_rules_can_override_git() {
    let temp = tempfile::tempdir().unwrap();
    fs::create_dir(temp.path().join("pkg")).unwrap();
    fs::write(temp.path().join(".gitignore"), "*.env\n*.py\n").unwrap();
    fs::write(
        temp.path().join(".kenignore"),
        "src/\n!secret.env\n!.ken/\n",
    )
    .unwrap();
    fs::write(
        temp.path().join("pkg/.gitignore"),
        "!keep.py\n!secret.env\n",
    )
    .unwrap();
    let mut filter = SourceFilter::new(temp.path()).unwrap();
    assert!(filter.is_ignored(Path::new("secret.env"), false).unwrap());
    assert!(
        filter
            .is_ignored(Path::new(".ken/cache.py"), false)
            .unwrap()
    );
    assert!(!filter.is_ignored(Path::new("pkg/keep.py"), false).unwrap());
    assert!(
        !filter
            .is_ignored(Path::new("pkg/secret.env"), false)
            .unwrap()
    );
    assert!(
        filter
            .is_ignored(Path::new("src/current.py"), false)
            .unwrap()
    );
}

#[test]
fn matcher_rejects_non_relative_identity_instead_of_reading_ancestor_rules() {
    let temp = tempfile::tempdir().unwrap();
    let mut filter = SourceFilter::new(temp.path()).unwrap();
    for invalid in [Path::new("../outside.py"), Path::new("/outside.py")] {
        assert!(filter.is_ignored(invalid, false).is_err());
    }
}

#[cfg(unix)]
#[test]
fn a_rule_symlink_cannot_read_outside_the_project() {
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("project");
    fs::create_dir_all(root.join("pkg")).unwrap();
    let outside = temp.path().join("outside-rules");
    fs::write(&outside, "*.py\n").unwrap();
    symlink(&outside, root.join("pkg/.gitignore")).unwrap();
    let mut filter = SourceFilter::new(&root).unwrap();
    assert!(
        filter
            .is_ignored(Path::new("pkg/main.py"), false)
            .unwrap_err()
            .to_string()
            .contains("escapes project")
    );
    symlink(&outside, root.join(".kenignore")).unwrap();
    assert!(
        SourceFilter::new(&root)
            .err()
            .unwrap()
            .to_string()
            .contains("escapes project")
    );
    assert_eq!(fs::read_to_string(outside).unwrap(), "*.py\n");
}
