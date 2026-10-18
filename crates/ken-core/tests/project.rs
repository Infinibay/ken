use ken_core::project::{DiscoveryContext, ProjectError, ProjectPaths, locate_project};
use std::{ffi::OsString, fs, path::Path};
use tempfile::TempDir;

fn context(cwd: &Path) -> DiscoveryContext {
    DiscoveryContext {
        cwd: cwd.to_path_buf(),
        forced_root: None,
        home: Some(cwd.join("home")),
    }
}
fn marker(root: &Path) {
    fs::create_dir_all(root.join(".ken")).unwrap();
    fs::write(root.join(".ken/meta.json"), "{}").unwrap();
}

#[test]
fn nearest_root_wins() {
    let t = TempDir::new().unwrap();
    let outer = t.path().join("project ü with spaces");
    marker(&outer);
    let inner = outer.join("inner");
    marker(&inner);
    let ctx = context(t.path());
    let paths = locate_project(&inner.join("absent/tail"), &ctx)
        .unwrap()
        .unwrap();
    assert_eq!(paths.root(), fs::canonicalize(&inner).unwrap());
    assert_eq!(paths.meta(), paths.root().join(".ken/meta.json"));
    assert_eq!(paths.db(), paths.root().join(".ken/ken.db"));
    assert_eq!(paths.port(), paths.root().join(".ken/daemon.port"));
    assert_eq!(paths.pid(), paths.root().join(".ken/daemon.pid"));
    assert_eq!(paths.log(), paths.root().join(".ken/daemon.log"));
}

#[cfg(unix)]
#[test]
fn cyclic_marker_is_not_a_file_and_ancestor_discovery_continues() {
    use std::os::unix::fs::symlink;

    let t = TempDir::new().unwrap();
    marker(t.path());
    let nested = t.path().join("nested");
    fs::create_dir_all(nested.join(".ken")).unwrap();
    symlink("meta.json", nested.join(".ken/meta.json")).unwrap();
    assert_eq!(
        locate_project(&nested, &context(t.path()))
            .unwrap()
            .unwrap()
            .root(),
        t.path().canonicalize().unwrap()
    );
}
#[test]
fn invalid_override_has_no_fallback() {
    let t = TempDir::new().unwrap();
    marker(t.path());
    let mut ctx = context(t.path());
    ctx.forced_root = Some(OsString::from("missing"));
    assert!(locate_project(t.path(), &ctx).unwrap().is_none());
    fs::create_dir_all(t.path().join("missing/.ken/meta.json")).unwrap();
    assert!(locate_project(t.path(), &ctx).unwrap().is_none());
}
#[test]
fn empty_override_uses_start() {
    let t = TempDir::new().unwrap();
    marker(t.path());
    let mut ctx = context(t.path());
    ctx.forced_root = Some(OsString::new());
    assert_eq!(
        locate_project(Path::new("."), &ctx)
            .unwrap()
            .unwrap()
            .root(),
        fs::canonicalize(t.path()).unwrap()
    );
}
#[cfg(unix)]
#[test]
fn symlink_parent_order_and_missing_tail() {
    use std::os::unix::fs::symlink;
    let t = TempDir::new().unwrap();
    let root = t.path().join("root");
    marker(&root);
    fs::create_dir_all(root.join("deep/target")).unwrap();
    symlink(root.join("deep/target"), root.join("link")).unwrap();
    let ctx = context(t.path());
    let paths = ProjectPaths::at(&root, &ctx).unwrap();
    assert_eq!(
        paths
            .resolve_inside(Path::new("link/../missing/tail"), &ctx)
            .unwrap(),
        fs::canonicalize(&root).unwrap().join("deep/missing/tail")
    );
    symlink(root.join("missing/target"), root.join("dangling")).unwrap();
    assert_eq!(
        paths
            .resolve_inside(Path::new("dangling/../new"), &ctx)
            .unwrap(),
        fs::canonicalize(&root).unwrap().join("missing/new")
    );
    symlink(root.join("link/../missing"), root.join("indirect")).unwrap();
    assert_eq!(
        paths
            .resolve_inside(Path::new("indirect/tail"), &ctx)
            .unwrap(),
        fs::canonicalize(&root).unwrap().join("deep/missing/tail")
    );
    symlink("loop", root.join("loop")).unwrap();
    assert!(paths.resolve_inside(Path::new("loop"), &ctx).is_err());
}
#[cfg(unix)]
#[test]
fn rejects_sibling_prefix_and_symlink_escape() {
    use std::os::unix::fs::symlink;
    let t = TempDir::new().unwrap();
    let root = t.path().join("root");
    marker(&root);
    let ctx = context(t.path());
    let paths = ProjectPaths::at(&root, &ctx).unwrap();
    let external = t.path().join("root-other/new");
    assert!(matches!(
        paths.resolve_inside(&external, &ctx),
        Err(ProjectError::EscapesRoot { .. })
    ));
    symlink(t.path(), root.join("escape")).unwrap();
    assert!(matches!(
        paths.resolve_inside(Path::new("escape/new"), &ctx),
        Err(ProjectError::EscapesRoot { .. })
    ));
    assert!(
        paths
            .resolve_inside(Path::new("../new"), &ctx)
            .unwrap_err()
            .to_string()
            .starts_with("path escapes project root:")
    );
}
#[cfg(unix)]
#[test]
fn tilde_and_named_user_match_python() {
    use uzers::os::unix::UserExt;
    let t = TempDir::new().unwrap();
    let mut ctx = context(t.path());
    let home = ctx.home.clone().unwrap();
    marker(&home.join("project"));
    ctx.forced_root = Some(OsString::from("~/project"));
    assert_eq!(
        locate_project(Path::new("absent"), &ctx)
            .unwrap()
            .unwrap()
            .root(),
        fs::canonicalize(home.join("project")).unwrap()
    );
    ctx.forced_root = None;
    assert!(
        locate_project(Path::new("~/project"), &ctx)
            .unwrap()
            .is_none()
    );
    let paths = ProjectPaths::at(&home, &ctx).unwrap();
    assert_eq!(
        paths.resolve_inside(Path::new("~/project"), &ctx).unwrap(),
        fs::canonicalize(home.join("project")).unwrap()
    );
    assert!(
        paths
            .resolve_inside(Path::new("~ken_nonexistent_user_1294728/x"), &ctx)
            .is_err()
    );
    let user = uzers::get_user_by_uid(uzers::get_current_uid()).unwrap();
    ctx.home = None;
    let real_home = ProjectPaths::at(user.home_dir(), &ctx).unwrap();
    assert_eq!(
        real_home.resolve_inside(Path::new("~"), &ctx).unwrap(),
        real_home.root()
    );
    let named = format!("~{}", user.name().to_str().unwrap());
    assert_eq!(
        real_home.resolve_inside(Path::new(&named), &ctx).unwrap(),
        real_home.root()
    );
    use std::os::unix::ffi::OsStringExt;
    assert!(
        real_home
            .resolve_inside(Path::new(&OsString::from_vec(b"~\xff".to_vec())), &ctx)
            .is_err()
    );
}
