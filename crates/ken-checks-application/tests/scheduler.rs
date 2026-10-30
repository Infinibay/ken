use ken_checks_application::{
    ChecksApplication, Resources, SchedulerHost, SchedulerOptions, WorkerProgram,
};
use ken_contracts::checks::Store;
use serde_json::json;
use std::{
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
fn app(root: &Path) -> ChecksApplication {
    let grammar = PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    let worker = WorkerProgram::new(PathBuf::from(env!("CARGO_BIN_EXE_ken-check-worker")));
    ChecksApplication::new(root, Resources::prepared(&grammar, worker).unwrap()).unwrap()
}
fn wait(mut ready: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(15);
    while !ready() {
        assert!(
            Instant::now() < deadline,
            "scheduler did not publish within bounded test deadline"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}
#[test]
fn real_scheduler_coalesces_edits_deduplicates_notices_and_closes() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("src")).unwrap();
    std::fs::write(
        root.path().join("src/a.py"),
        "def only(items=None): return items\n",
    )
    .unwrap();
    let app = app(root.path());
    let rule = json!({"id":"application.mutable-default","description":"No mutable argument literal","path":"src","query":"language \"kql/2\";module automatic;query q{edge HAS_HAZARD($site,\"mutable-default-argument\");select $site;}","examples":[{"name":"clean","expect":"pass","files":{"src/a.py":"def only(items=None): return items\n"}},{"name":"mutable","expect":"fail","files":{"src/a.py":"def only(items=[]): return items\n"}}]});
    app.manage(&json!({"action":"create","definition":rule}))
        .unwrap();
    let mut scheduler = SchedulerHost::spawn(
        app.clone(),
        SchedulerOptions {
            delay: Duration::from_millis(30),
            timeout_ms: 10000,
        },
    )
    .unwrap();
    scheduler
        .enqueue("session-a", &["src/a.py".into()])
        .unwrap();
    std::thread::sleep(Duration::from_millis(100));
    assert!(
        Store::new(root.path())
            .unwrap()
            .run_ids()
            .unwrap()
            .is_empty()
    );
    app.manage(&json!({"action":"validate","rule_id":"application.mutable-default"}))
        .unwrap();
    app.manage(
        &json!({"action":"enable","rule_id":"application.mutable-default","automatic":true}),
    )
    .unwrap();
    scheduler
        .enqueue("session-a", &["src/a.py".into()])
        .unwrap();
    scheduler
        .enqueue("session-a", &["src/a.py".into(), "src/new.py".into()])
        .unwrap();
    let mut first = String::new();
    wait(|| {
        first = scheduler.drain("session-a");
        !first.is_empty()
    });
    assert!(first.contains("application.mutable-default: pass"));
    assert_eq!(scheduler.drain("session-a"), "");
    let store = Store::new(root.path()).unwrap();
    assert_eq!(store.run_ids().unwrap().len(), 1);
    scheduler
        .enqueue("session-a", &["src/a.py".into()])
        .unwrap();
    wait(|| store.run_ids().unwrap().len() >= 2);
    assert_eq!(scheduler.drain("session-a"), "");
    std::fs::write(
        root.path().join("src/a.py"),
        "def only(items=[]): return items\n",
    )
    .unwrap();
    scheduler
        .enqueue("session-a", &["src/a.py".into()])
        .unwrap();
    let mut regression = String::new();
    wait(|| {
        regression = scheduler.drain("session-a");
        !regression.is_empty()
    });
    assert!(regression.contains("fail") && regression.contains("regression"));
    scheduler
        .enqueue("session-a", &["src/a.py".into()])
        .unwrap();
    scheduler.close().unwrap();
    let count = store.run_ids().unwrap().len();
    std::thread::sleep(Duration::from_millis(120));
    assert_eq!(store.run_ids().unwrap().len(), count);
    assert_eq!(scheduler.drain("session-a"), "");
    scheduler
        .enqueue("session-a", &["src/a.py".into()])
        .unwrap();
    scheduler.close().unwrap();
}
#[test]
fn closing_an_active_host_cancels_reaps_and_suppresses_late_notice() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("src")).unwrap();
    std::fs::write(root.path().join("src/a.py"), "class Present: pass\n").unwrap();
    let real = app(root.path());
    let rule = json!({"id":"application.active-close","description":"Class exists","path":"src","expectation":"some_match","query":"language \"kql/2\";module active_close;query q{class $c{name:\"Present\";}select $c;}","examples":[{"name":"present","expect":"pass","files":{"src/a.py":"class Present: pass\n"}},{"name":"absent","expect":"fail","files":{"src/a.py":"class Other: pass\n"}}]});
    real.manage(&json!({"action":"create","definition":rule}))
        .unwrap();
    assert_eq!(
        real.manage(&json!({"action":"validate","rule_id":"application.active-close"}))
            .unwrap()["state"],
        "validated"
    );
    real.manage(&json!({"action":"enable","rule_id":"application.active-close","automatic":true}))
        .unwrap();
    let pidfile = root.path().join("active.pid");
    let worker = WorkerProgram {
        executable: std::env::current_exe().unwrap(),
        arguments: [
            "--exact".to_owned(),
            "scheduler_probe".into(),
            "--ignored".into(),
            "--nocapture".into(),
            "--skip".into(),
            format!("probe-pidfile={}", pidfile.display()),
        ]
        .into_iter()
        .map(Into::into)
        .collect(),
    };
    let grammar = PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    let blocked =
        ChecksApplication::new(root.path(), Resources::prepared(&grammar, worker).unwrap())
            .unwrap();
    let mut scheduler = SchedulerHost::spawn(
        blocked,
        SchedulerOptions {
            delay: Duration::ZERO,
            timeout_ms: 10000,
        },
    )
    .unwrap();
    scheduler.enqueue("active", &["src/a.py".into()]).unwrap();
    wait(|| pidfile.exists());
    let pid = std::fs::read_to_string(&pidfile)
        .unwrap()
        .parse::<u32>()
        .unwrap();
    scheduler.close().unwrap();
    assert!(!Path::new(&format!("/proc/{pid}")).exists());
    assert!(scheduler.drain("active").is_empty());
    let store = Store::new(root.path()).unwrap();
    let count = store.run_ids().unwrap().len();
    std::thread::sleep(Duration::from_millis(100));
    assert_eq!(store.run_ids().unwrap().len(), count);
}
#[test]
#[ignore = "native blocking worker for in-flight host shutdown test"]
fn scheduler_probe() {
    let file = std::env::args()
        .find_map(|s| s.strip_prefix("probe-pidfile=").map(str::to_owned))
        .unwrap();
    std::fs::write(file, std::process::id().to_string()).unwrap();
    loop {
        std::thread::sleep(Duration::from_millis(10));
    }
}
