use ken_daemon::queue::{Action, Batch, BatchIndexer, IndexQueue, QueueOptions};
use ken_daemon::watcher::FileWatcher;
use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

#[derive(Clone)]
struct Recorder(Arc<Mutex<Vec<Batch>>>);
impl BatchIndexer for Recorder {
    fn apply(&mut self, batch: &Batch) -> ken_daemon::Result<()> {
        self.0.lock().unwrap().push(batch.clone());
        Ok(())
    }
}
fn queue() -> (IndexQueue, Arc<Mutex<Vec<Batch>>>) {
    let output = Arc::new(Mutex::new(Vec::new()));
    let recorder = Recorder(output.clone());
    let queue = IndexQueue::start(
        move || Ok(Box::new(recorder)),
        QueueOptions {
            drain: Duration::from_millis(40),
            max_paths: 256,
        },
    )
    .unwrap();
    (queue, output)
}
#[test]
fn queue_coalesces_last_writer_wins_in_first_encounter_order_and_hard_closes_cloned_senders() {
    let (queue, output) = queue();
    let sender = queue.sender();
    sender.reindex("b.rs").unwrap();
    sender.reindex("a.rs").unwrap();
    sender.delete("b.rs").unwrap();
    queue.flush().unwrap();
    let batches = output.lock().unwrap();
    assert_eq!(batches.len(), 1);
    assert_eq!(
        batches[0].events,
        vec![
            ("b.rs".into(), Action::Delete),
            ("a.rs".into(), Action::Reindex)
        ]
    );
    drop(batches);
    queue.stop().unwrap();
    assert!(sender.reindex("after-close.rs").is_err());
}
#[test]
fn queue_resync_dominates_pending_events_and_batch_bound_is_256_unique_paths() {
    let (queue, output) = queue();
    let sender = queue.sender();
    sender.reindex("discard.rs").unwrap();
    sender.resync().unwrap();
    sender.delete("also-discard.rs").unwrap();
    queue.flush().unwrap();
    assert_eq!(
        *output.lock().unwrap(),
        vec![Batch {
            resync: true,
            events: Vec::new()
        }]
    );
    output.lock().unwrap().clear();
    for i in 0..600 {
        sender.reindex(&format!("{i}.rs")).unwrap();
    }
    queue.flush().unwrap();
    let batches = output.lock().unwrap();
    assert!(batches.iter().all(|b| b.events.len() <= 256));
    assert_eq!(batches.iter().map(|b| b.events.len()).sum::<usize>(), 600);
    drop(batches);
    queue.stop().unwrap();
}
fn wait_for(output: &Arc<Mutex<Vec<Batch>>>, predicate: impl Fn(&[Batch]) -> bool) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if predicate(&output.lock().unwrap()) {
            return;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    panic!("watcher event did not arrive: {:?}", output.lock().unwrap());
}
#[test]
fn actual_recursive_watcher_ignores_internal_writes_and_reloads_nested_exclusions() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("src")).unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    let (queue, output) = queue();
    let mut watcher = FileWatcher::start(root.path(), queue.sender()).unwrap();
    std::fs::write(root.path().join(".ken/journal"), "internal").unwrap();
    std::fs::write(root.path().join("src/a.rs"), "a").unwrap();
    wait_for(&output, |b| {
        b.iter()
            .any(|b| b.events.iter().any(|(p, _)| p == "src/a.rs"))
    });
    assert!(
        output
            .lock()
            .unwrap()
            .iter()
            .flat_map(|b| &b.events)
            .all(|(p, _)| !p.starts_with(".ken/"))
    );
    output.lock().unwrap().clear();
    std::fs::write(root.path().join("src/.gitignore"), "ignored.rs\n").unwrap();
    wait_for(&output, |b| b.iter().any(|b| b.resync));
    output.lock().unwrap().clear();
    std::fs::write(root.path().join("src/ignored.rs"), "ignored").unwrap();
    std::fs::write(root.path().join("src/kept.rs"), "kept").unwrap();
    wait_for(&output, |b| {
        b.iter()
            .any(|b| b.events.iter().any(|(p, _)| p == "src/kept.rs"))
    });
    assert!(
        output
            .lock()
            .unwrap()
            .iter()
            .flat_map(|b| &b.events)
            .all(|(p, _)| p != "src/ignored.rs")
    );
    watcher.stop().unwrap();
    queue.stop().unwrap();
}
#[test]
fn watcher_mass_change_and_root_ignore_creation_removal_request_resynchronization() {
    let root = tempfile::tempdir().unwrap();
    let (queue, output) = queue();
    let mut watcher = FileWatcher::start(root.path(), queue.sender()).unwrap();
    watcher
        .observe(
            (0..512)
                .map(|i| (Action::Reindex, root.path().join(format!("{i}.rs"))))
                .collect(),
        )
        .unwrap();
    queue.flush().unwrap();
    assert!(output.lock().unwrap().iter().any(|b| b.resync));
    output.lock().unwrap().clear();
    std::fs::write(root.path().join(".kenignore"), "*.rs\n").unwrap();
    wait_for(&output, |b| b.iter().any(|b| b.resync));
    output.lock().unwrap().clear();
    std::fs::remove_file(root.path().join(".kenignore")).unwrap();
    wait_for(&output, |b| b.iter().any(|b| b.resync));
    watcher.stop().unwrap();
    queue.stop().unwrap();
}
