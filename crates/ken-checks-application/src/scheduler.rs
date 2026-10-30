//! One host thread around the domain Scheduler. No analysis under its mutex.
use crate::{ChecksApplication, Error, Result, WorkerControl};
use ken_contracts::checks::{RawReport, Scheduler};
use std::{
    sync::{Arc, Condvar, Mutex},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
#[derive(Clone, Debug)]
pub struct SchedulerOptions {
    pub delay: Duration,
    pub timeout_ms: u64,
}
impl Default for SchedulerOptions {
    fn default() -> Self {
        Self {
            delay: Duration::from_millis(500),
            timeout_ms: 3000,
        }
    }
}
struct State {
    scheduler: Scheduler,
    current: Option<WorkerControl>,
}
struct Shared {
    state: Mutex<State>,
    wake: Condvar,
    started: Instant,
}
pub struct SchedulerHost {
    application: ChecksApplication,
    shared: Arc<Shared>,
    worker: Option<JoinHandle<()>>,
}
impl SchedulerHost {
    pub fn spawn(application: ChecksApplication, options: SchedulerOptions) -> Result<Self> {
        if !(1..=120000).contains(&options.timeout_ms) {
            return Err(Error::Invalid("invalid automatic check timeout".into()));
        }
        let shared = Arc::new(Shared {
            state: Mutex::new(State {
                scheduler: Scheduler::new(options.delay, options.timeout_ms),
                current: None,
            }),
            wake: Condvar::new(),
            started: Instant::now(),
        });
        let app = application.clone();
        let worker_shared = shared.clone();
        let worker = thread::Builder::new()
            .name("ken-contract-checks".into())
            .spawn(move || work(app, worker_shared))?;
        Ok(Self {
            application,
            shared,
            worker: Some(worker),
        })
    }
    pub fn enqueue(&self, session: &str, paths: &[String]) -> Result<()> {
        if self
            .shared
            .state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .scheduler
            .is_closed()
        {
            return Ok(());
        }
        let enabled = self.application.has_automatic_rules()?;
        let mut state = self.shared.state.lock().unwrap_or_else(|e| e.into_inner());
        state
            .scheduler
            .enqueue(session, paths, enabled, self.shared.started.elapsed());
        self.shared.wake.notify_one();
        Ok(())
    }
    pub fn drain(&self, session: &str) -> String {
        self.shared
            .state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .scheduler
            .drain(session)
    }
    pub fn close(&mut self) -> Result<()> {
        {
            let mut state = self.shared.state.lock().unwrap_or_else(|e| e.into_inner());
            state.scheduler.close();
            if let Some(current) = &state.current {
                current.cancellation.cancel();
            }
            self.shared.wake.notify_all();
        }
        if let Some(worker) = self.worker.take() {
            worker
                .join()
                .map_err(|_| Error::Worker("automatic check worker panicked".into()))?;
        }
        Ok(())
    }
}
impl Drop for SchedulerHost {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
fn work(application: ChecksApplication, shared: Arc<Shared>) {
    loop {
        let (batch, control) = {
            let mut state = shared.state.lock().unwrap_or_else(|e| e.into_inner());
            loop {
                if state.scheduler.is_closed() {
                    return;
                }
                let now = shared.started.elapsed();
                if let Some(batch) = state.scheduler.take_ready(now) {
                    let control = WorkerControl::default();
                    state.current = Some(control.clone());
                    break (batch, control);
                }
                state = if let Some(due) = state.scheduler.next_due() {
                    let timeout = due.saturating_sub(now);
                    shared
                        .wake
                        .wait_timeout(state, timeout)
                        .unwrap_or_else(|e| e.into_inner())
                        .0
                } else {
                    shared.wake.wait(state).unwrap_or_else(|e| e.into_inner())
                };
            }
        };
        let results = batch
            .jobs
            .iter()
            .map(|job| {
                if control.cancellation.is_cancelled() {
                    return Err(ken_contracts::checks::Error::Invalid("cancelled".into()));
                }
                application
                    .check_with_control(&job.request(), &control)
                    .map_err(|e| ken_contracts::checks::Error::Invalid(e.to_string()))
            })
            .collect::<Vec<ken_contracts::checks::Result<RawReport>>>();
        let mut state = shared.state.lock().unwrap_or_else(|e| e.into_inner());
        state.current = None;
        state
            .scheduler
            .complete_reports(&batch, &results, shared.started.elapsed());
        shared.wake.notify_all();
    }
}
