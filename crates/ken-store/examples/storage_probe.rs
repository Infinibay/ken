//! Validation protocol over public native storage operations, without expected payloads.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_store::ProjectStore;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::HashSet, io::Read};
#[path = "storage_probe/history.rs"]
mod history;
#[path = "storage_probe/schema.rs"]
mod schema;
type ProbeResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    input: Input,
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "kebab-case", deny_unknown_fields)]
enum Input {
    Schema {
        legacy: bool,
    },
    Metadata {
        values: Vec<String>,
    },
    Marker {
        marker: String,
        model: String,
    },
    Slots {
        rollback: bool,
    },
    Cascade,
    Unique,
    Vectors {
        slots: Vec<i64>,
        vectors_le_hex: Vec<String>,
        query_le_hex: String,
        dim: usize,
    },
    Migrate {
        twice: bool,
    },
    Compact {
        interrupt: bool,
    },
    Vacuum,
    Manifest {
        field: String,
        value: Value,
    },
    SqlError,
}
fn run(raw: &str) -> ProbeResult<Value> {
    let started = std::time::Instant::now();
    let request: Request = serde_json::from_str(raw)?;
    let ids: HashSet<_> = request.cases.iter().map(|c| c.id.as_str()).collect();
    if request.cases.is_empty()
        || ids.len() != request.cases.len()
        || ids.iter().any(|id| id.is_empty())
    {
        return Err("distinct nonempty case IDs required".into());
    }
    let base = tempfile::tempdir()?;
    let mut results = Vec::new();
    for (index, case) in request.cases.into_iter().enumerate() {
        let root = base.path().join(index.to_string());
        std::fs::create_dir(&root)?;
        let paths = ProjectPaths::at(
            &root,
            &DiscoveryContext {
                cwd: root.clone(),
                forced_root: None,
                home: None,
            },
        )?;
        let mut project = ProjectStore::open(&paths)?;
        project.initialize()?;
        let correction = case.id.starts_with("correction-");
        let (output, measurements) = history::observe(&mut project, &root, case.input, correction)?;
        results.push(json!({"id":case.id,"classification":if correction {"integrity-correction"} else {"compatibility"},"output":output,"measurements":measurements}));
    }
    Ok(
        json!({"format":"ken-storage-native/1","runtime":{"engine":"rust","ken_store":env!("CARGO_PKG_VERSION"),"sqlite":rusqlite::version(),"format":1,"dtype":"float32","little_endian":cfg!(target_endian="little"),"model_runtime_needed":false},"results":results,"metrics":{"peak_rss_bytes":peak_rss()?,"elapsed_ns":started.elapsed().as_nanos()}}),
    )
}
fn peak_rss() -> ProbeResult<u64> {
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::zeroed();
    // getrusage initializes the supplied C struct on success; no pointers escape.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // The successful call above initialized every field read here.
    let usage = unsafe { usage.assume_init() };
    let peak = u64::try_from(usage.ru_maxrss)?;
    #[cfg(target_os = "linux")]
    let peak = peak.checked_mul(1024).ok_or("peak RSS overflow")?;
    Ok(peak)
}
fn main() {
    let result = (|| -> ProbeResult<String> {
        let mut input = String::new();
        std::io::stdin().read_to_string(&mut input)?;
        Ok(serde_json::to_string(&run(&input)?)?)
    })();
    match result {
        Ok(output) => println!("{output}"),
        Err(error) => {
            eprintln!("storage_probe: {error}");
            std::process::exit(1);
        }
    }
}
#[cfg(test)]
mod tests {
    use serde_json::{Value, json};
    #[test]
    fn storage_probe_executes_frozen_inputs_without_expected_payloads() {
        let cases: Value = serde_json::from_str(include_str!(
            "../../../docs/validation/rust-migration-2026-10-19/m2-storage/cases.json"
        ))
        .unwrap();
        let rows: Vec<_> = cases["cases"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| json!({"id":r["id"],"input":r["input"]}))
            .collect();
        let actual = super::run(&json!({"cases":rows}).to_string()).unwrap();
        assert_eq!(actual["format"], "ken-storage-native/1");
        assert!(
            actual["metrics"]["peak_rss_bytes"]
                .as_u64()
                .is_some_and(|n| n > 0)
        );
        assert!(
            actual["metrics"]["elapsed_ns"]
                .as_u64()
                .is_some_and(|n| n > 0)
        );
        assert_eq!(actual["results"].as_array().unwrap().len(), 32);
        assert_eq!(actual["results"][0]["id"], "schema-fresh");
        assert_eq!(
            actual["results"][2]["output"]["values"],
            json!(["", "é/設定", "\0middle\0", "17"])
        );
        assert_eq!(
            actual["results"][10]["output"]["allocations"],
            json!([[0, 1, 2], [1, 3]])
        );
        assert_eq!(
            actual["results"][31]["output"],
            json!({"interrupted":true,"complete_mapping":true,"original_references":true,"journal_absent":true})
        );
    }
    #[test]
    fn storage_probe_rejects_unknown_operations_fields_types_and_duplicate_ids() {
        let valid = json!({"cases":[{"id":"one","input":{"op":"metadata","values":["x"]}}]});
        for bad in [
            json!({}),
            json!({"cases":[]}),
            json!({"cases":[{"id":"","input":{"op":"metadata","values":[]}}]}),
            json!({"cases":[{"id":"one","input":{"op":"execute","sql":"DROP TABLE meta"}}]}),
            json!({"cases":[{"id":"one","input":{"op":"metadata","values":[false]}}]}),
        ] {
            assert!(super::run(&bad.to_string()).is_err(), "accepted {bad}");
        }
        for path in ["", "/cases/0", "/cases/0/input"] {
            for key in ["expected", "source_setup"] {
                let mut bad = valid.clone();
                bad.pointer_mut(path)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .insert(key.into(), json!({}));
                assert!(super::run(&bad.to_string()).is_err(), "accepted {bad}");
            }
        }
        let mut duplicate = valid.clone();
        duplicate["cases"]
            .as_array_mut()
            .unwrap()
            .push(valid["cases"][0].clone());
        assert!(super::run(&duplicate.to_string()).is_err());
    }
}
