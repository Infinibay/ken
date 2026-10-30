use ken_contracts::checks::{
    self, Clock, ModuleResolver, QueryEngine, QueryRequest, Receipt, Result, Service, SourceInputs,
    Store,
};
use serde_json::{Value, json};
use std::{cell::Cell, collections::BTreeMap, path::Path, rc::Rc, time::Duration};
struct Engine {
    canceled: Rc<Cell<bool>>,
    identities: Cell<usize>,
}
impl QueryEngine for Engine {
    fn identity(&self) -> String {
        self.identities.set(self.identities.get() + 1);
        "operation-control-fixture".into()
    }
    fn checkpoint(&self) -> Result<()> {
        if self.canceled.get() {
            Err(checks::Error::Invalid("cancelled".into()))
        } else {
            Ok(())
        }
    }
    fn run(&mut self, _: &QueryRequest) -> Result<Value> {
        panic!("admission/freshness tests must not execute a query")
    }
}
struct Inputs;
impl SourceInputs for Inputs {
    fn capture(&mut self, _: &Path, _: &str, _: Duration) -> Result<Value> {
        panic!("identity admission must precede source capture")
    }
    fn dependencies(&mut self, _: &Path, _: &Value, _: Duration) -> Result<Value> {
        panic!("identity admission must precede dependencies")
    }
}
struct Resolver {
    cancel: Rc<Cell<bool>>,
}
impl ModuleResolver for Resolver {
    fn resolve(
        &mut self,
        _: &Path,
        _: &str,
        libraries: &BTreeMap<String, String>,
    ) -> Result<BTreeMap<String, String>> {
        self.cancel.set(true);
        Ok(libraries.clone())
    }
}
struct Time;
impl Clock for Time {
    fn now(&self) -> String {
        "2026-10-30T00:00:00Z".into()
    }
    fn run_id(&self) -> String {
        "operation-control-run".into()
    }
}
fn definition() -> Value {
    json!({"id":"control.rule","description":"Checkpoint before publication","path":".","expectation":"some_match","query":"language \"kql/2\";module operation_control;query q{select 1;}"})
}
#[test]
fn cancellation_during_module_admission_prevents_rule_publication() {
    let root = tempfile::tempdir().unwrap();
    let canceled = Rc::new(Cell::new(false));
    let mut engine = Engine {
        canceled: canceled.clone(),
        identities: Cell::new(0),
    };
    let mut inputs = Inputs;
    let mut resolver = Resolver { cancel: canceled };
    let mut service =
        Service::new(root.path(), &mut engine, &mut inputs, &mut resolver, &Time).unwrap();
    let result = service.manage(&json!({"action":"create","definition":definition()}));
    assert!(result.is_err());
    assert!(result.err().unwrap().to_string().contains("cancel"));
    assert!(Store::new(root.path()).unwrap().rules().unwrap().is_empty());
}
#[test]
fn freshness_zero_budget_does_not_even_call_a_legacy_identity_provider() {
    let root = tempfile::tempdir().unwrap();
    let mut engine = Engine {
        canceled: Rc::new(Cell::new(false)),
        identities: Cell::new(0),
    };
    let mut inputs = Inputs;
    let mut resolver = Resolver {
        cancel: Rc::new(Cell::new(false)),
    };
    let receipt=Receipt::from_json(&json!({"version":1,"run_id":"control-empty","created_at":"2026-10-30T00:00:00Z","scope":"all","selection":"explicit","status":"not_applicable","checks":[]})).unwrap();
    {
        let mut service =
            Service::new(root.path(), &mut engine, &mut inputs, &mut resolver, &Time).unwrap();
        assert!(service.freshness_receipt(&receipt, Duration::ZERO).is_err());
    }
    assert_eq!(engine.identities.get(), 0);
}
#[test]
fn checked_rule_publication_cancels_after_temporary_bytes_exist_but_before_atomic_visibility() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::new(root.path()).unwrap();
    let original = json!({"version":1,"definition":definition(),"enabled":false,"automatic":false,"validation":null});
    store.save_rule(&original, None).unwrap();
    let path = store.path("rules", "control.rule").unwrap();
    let before = std::fs::read(&path).unwrap();
    let mut replacement = original.clone();
    replacement["definition"]["description"] = json!("Changed ".repeat(120));
    let interrupted = Cell::new(false);
    let mut check = || {
        let directory = root.path().join(".ken/checks/rules");
        let partial = std::fs::read_dir(&directory)?.any(|entry| {
            entry.ok().is_some_and(|entry| {
                entry.file_name().to_string_lossy().starts_with(".pending-")
                    && entry.metadata().is_ok_and(|m| m.len() > 0)
            })
        });
        if partial {
            interrupted.set(true);
            Err(checks::Error::Invalid("cancelled".into()))
        } else {
            Ok(())
        }
    };
    assert!(
        store
            .save_rule_checked(&replacement, Some(&original), &mut check)
            .is_err()
    );
    assert!(
        interrupted.get(),
        "checkpoint must poll while writing actual publication bytes"
    );
    assert_eq!(std::fs::read(path).unwrap(), before);
    assert!(
        std::fs::read_dir(root.path().join(".ken/checks/rules"))
            .unwrap()
            .all(|entry| !entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".pending-"))
    );
}
#[test]
fn source_capture_polls_inside_existing_fingerprint_owner_and_keeps_hash_contract() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("large.py"), vec![b'#'; 512 * 1024]).unwrap();
    let polls = Cell::new(0);
    let expected =
        checks::capture_sources(root.path(), "large.py", Duration::from_secs(2)).unwrap();
    let captured = checks::capture_sources_checked(
        root.path(),
        "large.py",
        Duration::from_secs(2),
        &mut || {
            polls.set(polls.get() + 1);
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(captured, expected);
    assert!(
        polls.get() > 40,
        "a large physical hash must cooperate during chunks, not only before/after the whole file"
    );
    let mut count = 0;
    let error = checks::capture_sources_checked(
        root.path(),
        "large.py",
        Duration::from_secs(2),
        &mut || {
            count += 1;
            if count == 8 {
                Err(checks::Error::Invalid("cancelled".into()))
            } else {
                Ok(())
            }
        },
    )
    .unwrap_err();
    assert!(error.to_string().contains("cancel"));
    assert_eq!(count, 8);
}
#[test]
fn checked_immutable_receipt_publication_cancels_before_a_run_becomes_visible() {
    let root = tempfile::tempdir().unwrap();
    let store = Store::new(root.path()).unwrap();
    let receipt=Receipt::from_json(&json!({"version":1,"run_id":"control-canceled-run","created_at":"2026-10-30T00:00:00Z","scope":"all","selection":"explicit","status":"not_applicable","checks":[]})).unwrap();
    let interrupted = Cell::new(false);
    let mut check = || {
        let partial = std::fs::read_dir(root.path().join(".ken/checks/runs"))
            .ok()
            .into_iter()
            .flatten()
            .any(|entry| {
                entry.ok().is_some_and(|entry| {
                    entry.file_name().to_string_lossy().starts_with(".pending-")
                        && entry.metadata().is_ok_and(|m| m.len() > 0)
                })
            });
        if partial {
            interrupted.set(true);
            Err(checks::Error::Invalid("cancelled".into()))
        } else {
            Ok(())
        }
    };
    assert!(store.write_receipt_checked(&receipt, &mut check).is_err());
    assert!(interrupted.get());
    assert!(!store.path("runs", "control-canceled-run").unwrap().exists());
    assert!(store.run_ids().unwrap().is_empty());
}
