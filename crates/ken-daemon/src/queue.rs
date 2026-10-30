//! One joined worker owns indexing; senders own no SQLite/model state.
use crate::{Error, Result};
use std::{
    collections::VecDeque,
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Reindex,
    Delete,
}
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Batch {
    pub resync: bool,
    pub events: Vec<(String, Action)>,
}
pub trait BatchIndexer {
    fn apply(&mut self, batch: &Batch) -> Result<()>;
}
#[derive(Clone, Debug)]
pub struct QueueOptions {
    pub drain: Duration,
    pub max_paths: usize,
}
impl Default for QueueOptions {
    fn default() -> Self {
        Self {
            drain: Duration::from_millis(500),
            max_paths: 256,
        }
    }
}
enum Message {
    Event(String, Action),
    Resync,
    Barrier(mpsc::Sender<Result<()>>),
}
struct Shared {
    pending: Mutex<VecDeque<Message>>,
    wake: Condvar,
    closed: AtomicBool,
}
struct WorkerExit(Arc<Shared>);
impl Drop for WorkerExit {
    fn drop(&mut self) {
        self.0.closed.store(true, Ordering::Release);
        let mut pending = self.0.pending.lock().unwrap_or_else(|e| e.into_inner());
        for message in pending.drain(..) {
            if let Message::Barrier(tx) = message {
                let _ = tx.send(Err(Error::Closed));
            }
        }
        self.0.wake.notify_all();
    }
}
#[derive(Clone)]
pub struct QueueSender {
    shared: Arc<Shared>,
}
impl QueueSender {
    fn push(&self, message: Message) -> Result<()> {
        let mut pending = self
            .shared
            .pending
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        if self.shared.closed.load(Ordering::Acquire) {
            return Err(Error::Closed);
        }
        pending.push_back(message);
        self.shared.wake.notify_one();
        Ok(())
    }
    pub fn reindex(&self, path: &str) -> Result<()> {
        self.push(Message::Event(path.into(), Action::Reindex))
    }
    pub fn delete(&self, path: &str) -> Result<()> {
        self.push(Message::Event(path.into(), Action::Delete))
    }
    pub fn resync(&self) -> Result<()> {
        self.push(Message::Resync)
    }
}
pub struct IndexQueue {
    sender: QueueSender,
    worker: Option<JoinHandle<()>>,
}
impl IndexQueue {
    pub fn start<F>(factory: F, options: QueueOptions) -> Result<Self>
    where
        F: FnOnce() -> Result<Box<dyn BatchIndexer>> + Send + 'static,
    {
        if options.max_paths == 0 || options.max_paths > 256 {
            return Err(Error::Invalid("queue batch bound must be1..256".into()));
        }
        let shared = Arc::new(Shared {
            pending: Mutex::new(VecDeque::new()),
            wake: Condvar::new(),
            closed: AtomicBool::new(false),
        });
        let worker_shared = shared.clone();
        let (start_tx, start_rx) = mpsc::sync_channel(1);
        let worker = thread::Builder::new()
            .name("ken-indexer".into())
            .spawn(move || {
                let _exit = WorkerExit(worker_shared.clone());
                let mut indexer = match factory() {
                    Ok(value) => {
                        let _ = start_tx.send(Ok(()));
                        value
                    }
                    Err(error) => {
                        let _ = start_tx.send(Err(error));
                        return;
                    }
                };
                work(&worker_shared, &options, indexer.as_mut());
            })?;
        match start_rx.recv() {
            Ok(Ok(())) => Ok(Self {
                sender: QueueSender { shared },
                worker: Some(worker),
            }),
            Ok(Err(error)) => {
                let _ = worker.join();
                Err(error)
            }
            Err(_) => {
                let _ = worker.join();
                Err(Error::Invalid("index worker failed during startup".into()))
            }
        }
    }
    pub fn sender(&self) -> QueueSender {
        self.sender.clone()
    }
    pub fn flush(&self) -> Result<()> {
        let (tx, rx) = mpsc::channel();
        self.sender.push(Message::Barrier(tx))?;
        rx.recv().map_err(|_| Error::Closed)?
    }
    pub fn stop(mut self) -> Result<()> {
        self.close()
    }
    fn close(&mut self) -> Result<()> {
        self.sender.shared.closed.store(true, Ordering::Release);
        self.sender.shared.wake.notify_all();
        if let Some(worker) = self.worker.take() {
            worker
                .join()
                .map_err(|_| Error::Invalid("index worker panicked".into()))?;
        }
        Ok(())
    }
}
impl Drop for IndexQueue {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
fn work(shared: &Shared, options: &QueueOptions, indexer: &mut dyn BatchIndexer) {
    let mut failure: Option<String> = None;
    loop {
        let mut pending = shared.pending.lock().unwrap_or_else(|e| e.into_inner());
        while pending.is_empty() && !shared.closed.load(Ordering::Acquire) {
            pending = shared.wake.wait(pending).unwrap_or_else(|e| e.into_inner());
        }
        if shared.closed.load(Ordering::Acquire) {
            return;
        }
        if let Some(Message::Barrier(_)) = pending.front() {
            if let Some(Message::Barrier(tx)) = pending.pop_front() {
                let _ = tx.send(failure.take().map_or(Ok(()), |e| Err(Error::Invalid(e))));
            }
            continue;
        }
        let deadline = Instant::now() + options.drain;
        let mut batch = Batch::default();
        loop {
            while let Some(message) = pending.front() {
                if matches!(message, Message::Barrier(_)) {
                    break;
                }
                let message = pending.pop_front().unwrap();
                match message {
                    Message::Resync => {
                        batch.resync = true;
                        batch.events.clear();
                    }
                    Message::Event(path, action) => {
                        if !batch.resync {
                            if let Some((_, old)) =
                                batch.events.iter_mut().find(|(p, _)| p == &path)
                            {
                                *old = action;
                            } else {
                                batch.events.push((path, action));
                            }
                        }
                    }
                    Message::Barrier(_) => unreachable!(),
                }
                if batch.events.len() >= options.max_paths {
                    break;
                }
            }
            if shared.closed.load(Ordering::Acquire) {
                return;
            }
            if batch.events.len() >= options.max_paths
                || matches!(pending.front(), Some(Message::Barrier(_)))
                || Instant::now() >= deadline
            {
                break;
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            pending = shared
                .wake
                .wait_timeout(pending, remaining)
                .unwrap_or_else(|e| e.into_inner())
                .0;
        }
        drop(pending);
        if let Err(error) = indexer.apply(&batch) {
            eprintln!("ken index batch failed: {error}");
            failure = Some(error.to_string());
        }
    }
}
