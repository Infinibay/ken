use std::collections::BTreeSet;
#[test]
fn python_module_candidates_preserve_ambiguity_relative_packages_and_src_layout() {
    let paths: BTreeSet<_> = [
        "foo.py",
        "foo/__init__.py",
        "src/foo.py",
        "pkg/foo.py",
        "pkg/child.py",
        "pkg/__init__.py",
        "root.py",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect();
    assert_eq!(
        ken_program::python_module_targets("pkg/use.py", "foo", &paths),
        vec!["foo.py", "foo/__init__.py", "pkg/foo.py", "src/foo.py"]
    );
    assert_eq!(
        ken_program::python_module_targets("pkg/use.py", ".child", &paths),
        vec!["pkg/child.py"]
    );
    assert_eq!(
        ken_program::python_module_targets("pkg/nested/use.py", "..child", &paths),
        vec!["pkg/child.py"]
    );
    assert_eq!(
        ken_program::python_module_targets("pkg/use.py", ".", &paths),
        vec!["pkg/__init__.py"]
    );
    assert!(ken_program::python_module_targets("pkg/use.py", "missing", &paths).is_empty());
}
