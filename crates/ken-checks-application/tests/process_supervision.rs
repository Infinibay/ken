use ken_checks_application::{ChecksApplication, Resources, WorkerControl, WorkerProgram};
use ken_contracts::checks::{QueryRequest, judgment_observation};
use std::{
    collections::BTreeMap,
    io::Write,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
// The fault probes intentionally kill/exit their immediate parent. Adopt the
// known fixture descendants here so the assertions cannot leave zombie children
// behind even when an earlier assertion unwinds.
struct DescendantReaper {
    pidfile: PathBuf,
    reaped: bool,
}
impl DescendantReaper {
    fn new(pidfile: &Path) -> Self {
        static ENABLED: std::sync::Once = std::sync::Once::new();
        ENABLED.call_once(|| {
            assert_eq!(
                unsafe { libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) },
                0
            )
        });
        Self {
            pidfile: pidfile.into(),
            reaped: false,
        }
    }
    fn pid(&self) -> Option<i32> {
        std::fs::read_to_string(&self.pidfile)
            .ok()?
            .trim()
            .parse()
            .ok()
    }
    fn reap(&mut self) -> std::io::Result<()> {
        let Some(pid) = self.pid() else {
            self.reaped = true;
            return Ok(());
        };
        let until = Instant::now() + Duration::from_secs(1);
        loop {
            let mut status = 0;
            let result = unsafe { libc::waitpid(pid, &mut status, libc::WNOHANG) };
            if result == pid {
                self.reaped = true;
                return Ok(());
            }
            if result < 0 {
                let error = std::io::Error::last_os_error();
                if error.raw_os_error() == Some(libc::EINTR) {
                    continue;
                }
                if error.raw_os_error() == Some(libc::ECHILD)
                    && !Path::new(&format!("/proc/{pid}")).exists()
                {
                    self.reaped = true;
                    return Ok(());
                }
                return Err(error);
            }
            if Instant::now() >= until {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    "supervisor left a live descendant",
                ));
            }
            std::thread::sleep(Duration::from_millis(2));
        }
    }
}
impl Drop for DescendantReaper {
    fn drop(&mut self) {
        if self.reaped {
            return;
        }
        if let Some(pid) = self.pid() {
            unsafe { libc::kill(pid, libc::SIGKILL) };
            loop {
                let mut status = 0;
                let result = unsafe { libc::waitpid(pid, &mut status, 0) };
                if result >= 0
                    || std::io::Error::last_os_error().raw_os_error() != Some(libc::EINTR)
                {
                    break;
                }
            }
        }
    }
}
struct ProbeChild(std::process::Child);
impl Drop for ProbeChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn app(root: &Path, mode: &str, pidfile: &Path) -> ChecksApplication {
    let arguments = [
        "--exact".to_owned(),
        "process_probe".into(),
        "--ignored".into(),
        "--nocapture".into(),
        "--skip".into(),
        format!("probe-mode={mode}"),
        "--skip".into(),
        format!("probe-pidfile={}", pidfile.display()),
    ]
    .into_iter()
    .map(Into::into)
    .collect();
    let worker = WorkerProgram {
        executable: std::env::current_exe().unwrap(),
        arguments,
    };
    let grammar = std::path::PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    let mut resources = Resources::prepared(&grammar, worker).unwrap();
    resources.worker_limits.max_response_bytes = 4096;
    resources.worker_limits.max_stderr_bytes = 1024;
    ChecksApplication::new(root, resources).unwrap()
}
fn request(root: &Path, ms: f64) -> QueryRequest {
    QueryRequest {
        root: root.into(),
        source: r#"language "kql/2";module bounded;query q{select 1;}"#.into(),
        query_name: None,
        libraries: BTreeMap::new(),
        path: ".".into(),
        source_paths: None,
        timeout_ms: Some(ms),
        max_states: Some(200000),
        max_rows: Some(100),
        source_profile: "full".into(),
    }
}
#[test]
fn crash_malformed_and_oversize_worker_output_stay_unknown_and_bounded() {
    let root = tempfile::tempdir().unwrap();
    for mode in ["crash", "malformed", "oversize"] {
        let app = app(root.path(), mode, &root.path().join("unused"));
        let result = app
            .observe(&request(root.path(), 2000.), &WorkerControl::default())
            .unwrap();
        assert_eq!(
            judgment_observation(&result, "some_match"),
            "unknown",
            "{mode}"
        );
        assert_eq!(
            judgment_observation(&result, "no_matches"),
            "unknown",
            "{mode}"
        );
        let result = result.to_json().unwrap();
        assert_eq!(result["complete"], false);
        assert!(
            result["reason"]
                .as_str()
                .is_some_and(|s| !s.is_empty() && s.len() < 8192)
        );
    }
}
#[test]
fn stderr_backpressure_and_descendant_processes_cannot_outlive_deadline() {
    let root = tempfile::tempdir().unwrap();
    for mode in ["stderr", "descendant"] {
        let pidfile = root.path().join(format!("{mode}.pid"));
        let mut descendants = DescendantReaper::new(&pidfile);
        let app = app(root.path(), mode, &pidfile);
        let started = Instant::now();
        let result = app
            .observe(&request(root.path(), 2000.), &WorkerControl::default())
            .unwrap()
            .to_json()
            .unwrap();
        assert_eq!(result["reason"], "timeout");
        assert!(started.elapsed() < Duration::from_secs(5));
        if mode == "descendant" {
            assert!(pidfile.exists(), "native descendant probe started");
            let pid = std::fs::read_to_string(&pidfile)
                .unwrap()
                .trim()
                .parse::<u32>()
                .unwrap();
            descendants
                .reap()
                .expect("supervisor must kill and allow reaping the descendant");
            assert!(
                !Path::new(&format!("/proc/{pid}")).exists(),
                "descendant was not reaped"
            );
        }
    }
}
#[test]
#[ignore = "native subprocess fault harness; selected explicitly by supervisor tests"]
fn process_probe() {
    let args = std::env::args().collect::<Vec<_>>();
    let mode = args
        .iter()
        .find_map(|s| s.strip_prefix("probe-mode="))
        .unwrap();
    let pidfile = args
        .iter()
        .find_map(|s| s.strip_prefix("probe-pidfile="))
        .unwrap();
    match mode {
        "crash" => std::process::exit(23),
        "malformed" => {
            print!("not-json");
            std::io::stdout().flush().unwrap();
            std::process::exit(0);
        }
        "oversize" => {
            std::io::stdout().write_all(&vec![b'x'; 65536]).unwrap();
            std::process::exit(0);
        }
        "stderr" => {
            std::io::stderr()
                .write_all(&vec![b'e'; 2 * 1024 * 1024])
                .unwrap();
        }
        "continuous" => {
            std::fs::write(pidfile, std::process::id().to_string()).unwrap();
            let mut stderr = std::io::stderr().lock();
            let bytes = vec![b'e'; 1024 * 1024];
            loop {
                stderr.write_all(&bytes).unwrap();
            }
        }
        "detached" => {
            let _child = ProbeChild(
                std::process::Command::new(std::env::current_exe().unwrap())
                    .args([
                        "--exact",
                        "process_probe",
                        "--ignored",
                        "--nocapture",
                        "--skip",
                        "probe-mode=child",
                        "--skip",
                        &format!("probe-pidfile={pidfile}"),
                    ])
                    .stdin(std::process::Stdio::null())
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .spawn()
                    .unwrap(),
            );
            let until = Instant::now() + Duration::from_secs(2);
            while !Path::new(pidfile).exists() {
                assert!(Instant::now() < until);
                std::thread::sleep(Duration::from_millis(1));
            }
            print!("{{}}");
            std::io::stdout().flush().unwrap();
            std::process::exit(0);
        }
        "descendant" => {
            let mut child = ProbeChild(
                std::process::Command::new(std::env::current_exe().unwrap())
                    .args([
                        "--exact",
                        "process_probe",
                        "--ignored",
                        "--nocapture",
                        "--skip",
                        "probe-mode=child",
                        "--skip",
                        &format!("probe-pidfile={pidfile}"),
                    ])
                    .stdin(std::process::Stdio::null())
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .spawn()
                    .unwrap(),
            );
            child.0.wait().unwrap();
        }
        "child" => {
            std::fs::write(pidfile, std::process::id().to_string()).unwrap();
        }
        _ => panic!("unknown probe mode"),
    };
    loop {
        std::thread::sleep(Duration::from_millis(10));
    }
}
#[test]
fn cancellation_of_a_running_native_worker_reaps_it_before_return() {
    let root = tempfile::tempdir().unwrap();
    let pidfile = root.path().join("cancelled.pid");
    let app = app(root.path(), "continuous", &pidfile);
    let control = WorkerControl::default();
    let cancellation = control.cancellation.clone();
    let request = request(root.path(), 5000.);
    let child = std::thread::spawn(move || app.observe(&request, &control).unwrap());
    let deadline = Instant::now() + Duration::from_secs(3);
    while !pidfile.exists() {
        assert!(Instant::now() < deadline, "native probe failed to start");
        std::thread::sleep(Duration::from_millis(5));
    }
    let pid = std::fs::read_to_string(&pidfile)
        .unwrap()
        .parse::<u32>()
        .unwrap();
    cancellation.cancel();
    assert_eq!(
        child.join().unwrap().to_json().unwrap()["reason"],
        "cancelled"
    );
    assert!(
        !Path::new(&format!("/proc/{pid}")).exists(),
        "direct child not reaped"
    );
}

#[test]
fn continuous_stderr_cannot_starve_timeout_and_normal_exit_cleans_detached_group() {
    let root = tempfile::tempdir().unwrap();
    for mode in ["continuous", "detached"] {
        let pidfile = root.path().join(format!("{mode}-bounded.pid"));
        let mut descendants = DescendantReaper::new(&pidfile);
        let app = app(root.path(), mode, &pidfile);
        let started = Instant::now();
        let result = app
            .observe(&request(root.path(), 1500.), &WorkerControl::default())
            .unwrap()
            .to_json()
            .unwrap();
        assert!(started.elapsed() < Duration::from_secs(4));
        assert!(pidfile.exists(), "actual native {mode} probe did not start");
        if mode == "continuous" {
            assert_eq!(result["reason"], "timeout");
        } else {
            assert_eq!(result["complete"], false);
        }
        let pid = std::fs::read_to_string(&pidfile)
            .unwrap()
            .parse::<u32>()
            .unwrap();
        descendants
            .reap()
            .expect("supervisor must stop the probe before return");
        assert!(
            !Path::new(&format!("/proc/{pid}")).exists(),
            "{mode} process was not reaped"
        );
    }
}
