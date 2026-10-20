use ken_models::{ModelAssets, ModelFileSource, verify_onnx_dependencies};
use std::{fs, path::Path, time::Instant};
fn main() {
    let args: Vec<_> = std::env::args().collect();
    assert_eq!(args.len(), 5);
    let assets = ModelAssets::from_json(&fs::read_to_string(&args[1]).unwrap()).unwrap();
    let private = Path::new(&args[3]);
    let source = ModelFileSource::new(Path::new(&args[2]), private).unwrap();
    assert_eq!(fs::read_dir(private).unwrap().count(), 0);
    let started = Instant::now();
    let result = assets.verify_files(&source);
    let copy_ns = started.elapsed().as_nanos();
    let (valid, error, audit_ns) = match result {
        Ok(files) => {
            assert_eq!(files.fingerprint(), assets.fingerprint());
            assert_eq!(fs::read_dir(private).unwrap().count(), 1);
            let before = Instant::now();
            verify_onnx_dependencies(&args[4], &files).unwrap();
            let elapsed = before.elapsed().as_nanos();
            drop(files);
            (true, None, elapsed)
        },
        Err(error) => (false, Some(error.to_string()), 0),
    };
    assert_eq!(fs::read_dir(private).unwrap().count(), 0);
    // SAFETY: initialized getrusage output belongs to this process only.
    let mut usage = unsafe { std::mem::zeroed::<libc::rusage>() };
    assert_eq!(unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut usage) }, 0);
    let rss = if cfg!(target_os = "linux") { usage.ru_maxrss as u64 * 1024 } else { usage.ru_maxrss as u64 };
    println!("{}", serde_json::json!({"verified":valid,"error":error,"fingerprint":assets.fingerprint(),
        "copy_ns":copy_ns,"dependency_audit_ns":audit_ns,"peak_rss_bytes":rss,"private_files_removed":true}));
}
