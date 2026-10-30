use ken_contracts::checks::{
    self, Clock, ModuleResolver, QueryEngine, QueryRequest, Service, SourceInputs, Store,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/checks-domain.json")).unwrap()
}
fn project() -> tempfile::TempDir {
    let d = tempfile::tempdir().unwrap();
    std::fs::create_dir(d.path().join("src")).unwrap();
    std::fs::write(
        d.path().join("src/a.py"),
        "def target(items=None): return items\n",
    )
    .unwrap();
    d
}
struct FixtureClock(AtomicU64);
impl Clock for FixtureClock {
    fn now(&self) -> String {
        "2026-10-30T12:00:00+00:00".into()
    }
    fn run_id(&self) -> String {
        format!("{:032x}", self.0.fetch_add(1, Ordering::SeqCst) + 1)
    }
}
#[derive(Default)]
struct Modules;
impl ModuleResolver for Modules {
    fn resolve(
        &mut self,
        _: &Path,
        _: &str,
        explicit: &BTreeMap<String, String>,
    ) -> checks::Result<BTreeMap<String, String>> {
        Ok(explicit.clone())
    }
}
#[derive(Default)]
struct Inputs;
impl SourceInputs for Inputs {
    fn capture(&mut self, root: &Path, scope: &str, budget: Duration) -> checks::Result<Value> {
        checks::capture_sources(root, scope, budget)
    }
    fn dependencies(&mut self, _: &Path, snapshot: &Value, _: Duration) -> checks::Result<Value> {
        Ok(
            json!({"manifest":[],"imports":snapshot["manifest"].as_array().unwrap().iter().map(|p|json!([p[0],[]])).collect::<Vec<_>>(),"issues":[]}),
        )
    }
}
#[derive(Default)]
struct FixtureEngine {
    requests: Vec<QueryRequest>,
    identity: String,
    fail: Option<String>,
    mutate: Option<PathBuf>,
}
impl QueryEngine for FixtureEngine {
    fn identity(&self) -> String {
        if self.identity.is_empty() {
            "checks-engine-fixture/1".into()
        } else {
            self.identity.clone()
        }
    }
    fn run(&mut self, r: &QueryRequest) -> checks::Result<Value> {
        self.requests.push(r.clone());
        if let Some(reason) = &self.fail {
            return Err(checks::Error::Invalid(reason.clone()));
        }
        let source = std::fs::read_to_string(r.root.join("src/a.py"))?;
        if let Some(path) = self.mutate.take() {
            std::fs::write(path, "def target(items=[]): return items\n")?;
        }
        Ok(
            json!({"rows":if source.contains("=[]"){json!([[{"path":"src/a.py","line":1,"name":"target","kind":"function"}]])}else{json!([])},"complete":true,"coverage_complete":true,"unknown_candidates":0,"results_truncated":false,"reason":null}),
        )
    }
}
#[test]
fn lifecycle_and_freshness_match_frozen_policy_receipts() {
    let f = fixture();
    let d = project();
    let mut engine = FixtureEngine::default();
    let mut inputs = Inputs;
    let mut modules = Modules;
    let clock = FixtureClock(AtomicU64::new(0));
    let mut s = Service::new(d.path(), &mut engine, &mut inputs, &mut modules, &clock).unwrap();
    assert_eq!(
        s.manage(&json!({"action":"create","definition":f["definition"],"full":true}))
            .unwrap(),
        f["views"][0]
    );
    assert!(
        s.manage(&json!({"action":"enable","rule_id":"python.mutable-default"}))
            .is_err()
    );
    assert_eq!(
        s.manage(&json!({"action":"validate","rule_id":"python.mutable-default"}))
            .unwrap(),
        f["views"][1]
    );
    assert_eq!(
        s.manage(&json!({"action":"enable","rule_id":"python.mutable-default","automatic":true}))
            .unwrap(),
        f["views"][2]
    );
    let before = s.check(&json!({"full":true})).unwrap();
    assert_eq!(before, f["before"]);
    assert_eq!(
        s.freshness(&before, Duration::from_secs(1)).unwrap(),
        f["fresh"]
    );
    std::fs::write(
        d.path().join("src/a.py"),
        "def target(items=[]): return items\n",
    )
    .unwrap();
    assert_eq!(
        s.freshness(&before, Duration::from_secs(1)).unwrap(),
        f["stale"]
    );
    let after = s
        .check(&json!({"compare":before["run_id"],"full":true}))
        .unwrap();
    assert_eq!(after, f["after"]);
    std::fs::write(
        d.path().join("src/a.py"),
        "def target(items=None): return items\n",
    )
    .unwrap();
    let fixed = s
        .check(&json!({"compare":after["run_id"],"full":true}))
        .unwrap();
    assert_eq!(fixed, f["fixed"]);
    assert_eq!(s.related("src/a.py", 10).unwrap(), f["related"]);
    assert_eq!(
        s.justification(fixed["run_id"].as_str().unwrap(), None)
            .unwrap(),
        f["attached"]
    );
    assert_eq!(s.resume().unwrap(), f["resume"]);
    let mut changed = f["definition"].clone();
    changed["description"] = json!("Changed definition");
    assert_eq!(
        s.manage(
            &json!({"action":"update","rule_id":"python.mutable-default","definition":changed})
        )
        .unwrap(),
        f["changed"]
    );
    assert_eq!(
        s.freshness(&fixed, Duration::from_secs(1)).unwrap(),
        f["invalidated"]
    );
}
#[test]
fn judgment_and_reports_preserve_uncertainty() {
    let f = fixture();
    for c in f["judgments"].as_array().unwrap() {
        assert_eq!(checks::judgment(&c["input"], "some_match"), c["some_match"]);
        assert_eq!(checks::judgment(&c["input"], "no_matches"), c["no_matches"]);
    }
    assert_eq!(
        checks::judgment(&json!({"rows":[]}), "no_matches"),
        "unknown"
    );
    assert_eq!(checks::run_view(&f["after"], false).unwrap(), f["compact"]);
    assert_eq!(checks::message(&f["compact"]), f["message"]);
}
#[test]
fn selection_does_not_narrow_scope_and_runtime_failure_is_unknown() {
    let d = project();
    let f = fixture();
    let mut e = FixtureEngine {
        fail: Some("timeout".into()),
        ..Default::default()
    };
    let mut i = Inputs;
    let mut m = Modules;
    let c = FixtureClock(AtomicU64::new(0));
    {
        let mut s = Service::new(d.path(), &mut e, &mut i, &mut m, &c).unwrap();
        s.manage(&json!({"action":"create","definition":f["definition"]}))
            .unwrap();
        let result = s
            .check(&json!({"rules":["python.mutable-default"],"path":"src/a.py","full":true}))
            .unwrap();
        assert_eq!(result["status"], "unknown");
        assert_eq!(result["checks"][0]["result"]["reason"], "timeout");
        assert_eq!(result["checks"][0]["path"], "src");
    }
    assert_eq!(e.requests[0].path, "src");
}
#[test]
fn source_changes_during_query_invalidate_certain_results() {
    let d = project();
    let f = fixture();
    let mut e = FixtureEngine {
        mutate: Some(d.path().join("src/a.py")),
        ..Default::default()
    };
    let mut i = Inputs;
    let mut m = Modules;
    let c = FixtureClock(AtomicU64::new(0));
    let mut s = Service::new(d.path(), &mut e, &mut i, &mut m, &c).unwrap();
    s.manage(&json!({"action":"create","definition":f["definition"]}))
        .unwrap();
    let result = s
        .check(&json!({"rules":["python.mutable-default"],"full":true}))
        .unwrap();
    assert_eq!(result["status"], "unknown");
    assert_eq!(
        result["checks"][0]["result"]["reason"],
        "source_changed_during_check"
    );
}
#[test]
fn store_confines_records_and_cas_immutable_receipts() {
    let d = project();
    let store = Store::new(d.path()).unwrap();
    let f = fixture();
    let record = json!({"version":1,"definition":checks::Rule::read(&f["definition"]).unwrap().data(),"enabled":false,"automatic":false,"validation":null});
    store.save_rule(&record, None).unwrap();
    assert!(store.save_rule(&record, None).is_err());
    assert!(store.read("runs", "../outside").is_err());
    store
        .write_run("fixed", &json!({"version":1,"status":"unknown"}))
        .unwrap();
    assert!(
        store
            .write_run("fixed", &json!({"version":1,"status":"pass"}))
            .is_err()
    );
}
#[cfg(unix)]
#[test]
fn snapshots_and_receipts_reject_symlink_coverage() {
    let d = project();
    std::os::unix::fs::symlink(d.path().join("src"), d.path().join("src/link")).unwrap();
    assert!(checks::capture_sources(d.path(), "src", Duration::from_secs(1)).is_err());
    std::fs::create_dir_all(d.path().join(".ken/checks")).unwrap();
    std::os::unix::fs::symlink(d.path().join("src"), d.path().join(".ken/checks/runs")).unwrap();
    assert!(Store::new(d.path()).unwrap().read("runs", "one").is_err());
}
#[test]
fn scheduler_coalesces_deduplicates_and_cannot_publish_after_close() {
    let mut scheduler = checks::Scheduler::new(Duration::from_millis(500), 3000);
    scheduler.enqueue("s", &["src/b.py".into()], true, Duration::ZERO);
    scheduler.enqueue("s", &["src/a.py".into()], true, Duration::from_millis(100));
    assert!(scheduler.take_ready(Duration::from_millis(599)).is_none());
    let batch = scheduler.take_ready(Duration::from_millis(600)).unwrap();
    assert_eq!(batch.jobs[0].paths, vec!["src/a.py", "src/b.py"]);
    let receipt = checks::run_view(&fixture()["before"], false).unwrap();
    scheduler.complete(&batch, &[Ok(receipt.clone())], Duration::from_millis(610));
    assert!(scheduler.drain("s").contains("pass"));
    assert!(scheduler.drain("s").is_empty());
    scheduler.enqueue("s", &[], true, Duration::from_millis(700));
    let second = scheduler.take_ready(Duration::from_millis(1200)).unwrap();
    scheduler.complete(&second, &[Ok(receipt)], Duration::from_millis(1201));
    assert!(scheduler.drain("s").is_empty());
    scheduler.enqueue("s", &[], true, Duration::from_millis(1300));
    let late = scheduler.take_ready(Duration::from_millis(1800)).unwrap();
    scheduler.close();
    scheduler.complete(
        &late,
        &[Ok(checks::run_view(&fixture()["after"], false).unwrap())],
        Duration::from_millis(1801),
    );
    assert!(scheduler.drain("s").is_empty());
    assert!(scheduler.take_ready(Duration::from_secs(3)).is_none());
}
#[test]
fn invalid_rule_and_failed_validation_cannot_enable() {
    let f = fixture();
    let mut bad = f["definition"].clone();
    bad["path"] = json!("../outside");
    assert!(checks::Rule::read(&bad).is_err());
    bad = f["definition"].clone();
    bad["examples"][0]["files"] = json!({"../escape.py":"x"});
    assert!(checks::Rule::read(&bad).is_err());
    let d = project();
    let mut e = FixtureEngine::default();
    let mut i = Inputs;
    let mut m = Modules;
    let c = FixtureClock(AtomicU64::new(0));
    let mut s = Service::new(d.path(), &mut e, &mut i, &mut m, &c).unwrap();
    let mut wrong = f["definition"].clone();
    wrong["examples"][1]["files"]["src/a.py"] = wrong["examples"][0]["files"]["src/a.py"].clone();
    s.manage(&json!({"action":"create","definition":wrong}))
        .unwrap();
    assert_eq!(
        s.manage(&json!({"action":"validate","rule_id":"python.mutable-default"}))
            .unwrap()["state"],
        "draft"
    );
    assert!(
        s.manage(&json!({"action":"enable","rule_id":"python.mutable-default"}))
            .is_err()
    );
}
#[test]
fn certainty_requires_explicit_complete_coverage_and_candidate_metadata() {
    for result in [
        json!({"rows":[],"complete":true,"coverage_complete":true}),
        json!({"rows":[],"complete":true,"coverage_complete":true,"unknown_candidates":0}),
    ] {
        assert_eq!(checks::judgment(&result, "no_matches"), "unknown");
    }
}
#[test]
fn pending_edits_survive_active_batch_and_obsolete_completion_is_ignored() {
    let mut s = checks::Scheduler::new(Duration::from_millis(10), 3000);
    s.enqueue("a", &["src/a.py".into()], true, Duration::ZERO);
    let first = s.take_ready(Duration::from_millis(10)).unwrap();
    s.enqueue("a", &["src/b.py".into()], true, Duration::from_millis(11));
    assert!(s.take_ready(Duration::from_secs(1)).is_none());
    let pass = checks::run_view(&fixture()["before"], false).unwrap();
    s.complete(&first, &[Ok(pass)], Duration::from_millis(20));
    let next = s.take_ready(Duration::from_millis(30)).unwrap();
    assert_eq!(next.jobs[0].paths, vec!["src/b.py"]);
    assert_eq!(next.jobs[0].compare, "00000000000000000000000000000001");
    s.drain("a");
    s.complete(
        &first,
        &[Ok(checks::run_view(&fixture()["after"], false).unwrap())],
        Duration::from_millis(31),
    );
    assert!(s.is_running());
    assert!(s.drain("a").is_empty());
}
#[test]
fn git_changes_include_deleted_staged_unstaged_and_untracked_source() {
    let d = project();
    let git = |args: &[&str]| {
        let out = std::process::Command::new("git")
            .arg("-C")
            .arg(d.path())
            .args(args)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
    };
    git(&["init"]);
    git(&["add", "src"]);
    git(&[
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture",
    ]);
    assert!(checks::changed_paths(d.path()).unwrap().is_empty());
    std::fs::write(d.path().join("src/new.py"), "NEW = 1").unwrap();
    git(&["add", "src/new.py"]);
    std::fs::write(d.path().join("src/other.py"), "OTHER = 1").unwrap();
    std::fs::remove_file(d.path().join("src/a.py")).unwrap();
    let changes = checks::changed_paths(d.path()).unwrap();
    assert_eq!(changes, vec!["src/a.py", "src/new.py", "src/other.py"]);
    let patch = json!(
        "*** Update File: src/a.py\n*** Add File: src/new.py\n*** Delete File: src/other.py\n"
    );
    assert_eq!(
        checks::edited_paths(d.path(), &patch, Some("/outside.py")),
        changes
    );
}
#[test]
fn oversized_records_are_never_published_and_leave_prior_receipts_readable() {
    let d = project();
    let store = Store::new(d.path()).unwrap();
    let before = json!({"version":1,"run_id":"fixed","status":"unknown"});
    store.write_run("fixed", &before).unwrap();
    let huge = json!({"version":1,"payload":"x".repeat(16000000)});
    assert!(store.write_run("too-large", &huge).is_err());
    assert!(store.read("runs", "too-large").is_err());
    assert!(store.write_run("fixed", &huge).is_err());
    assert_eq!(store.read("runs", "fixed").unwrap(), before);
    let names = std::fs::read_dir(d.path().join(".ken/checks/runs"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    assert_eq!(names, vec!["fixed.json"]);
    let f = fixture();
    let original = json!({"version":1,"definition":checks::Rule::read(&f["definition"]).unwrap().data(),"enabled":false,"automatic":false,"validation":null});
    store.save_rule(&original, None).unwrap();
    let mut oversized = original.clone();
    oversized["extra"] = huge["payload"].clone();
    assert!(store.save_rule(&oversized, Some(&original)).is_err());
    assert_eq!(
        store.read("rules", "python.mutable-default").unwrap(),
        original
    );
}
