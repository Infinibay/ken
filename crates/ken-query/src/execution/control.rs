use super::{ExecutionError, Result};
use serde::{Deserialize, Serialize};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
#[derive(Clone, Debug, Default)]
pub struct Cancellation(Arc<AtomicBool>);
impl Cancellation {
    pub fn cancel(&self) {
        self.0.store(true, Ordering::Relaxed);
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Relaxed)
    }
}
#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceMode {
    #[default]
    Strict,
    Possible,
}
#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Planning {
    AuthorOrder,
    #[default]
    Selective,
}
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct QueryBudget {
    pub max_rows: Option<u64>,
    pub max_states: Option<u64>,
    pub max_matches: Option<u64>,
    pub timeout_ms: Option<u64>,
}
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ExecutionOptions {
    #[serde(flatten)]
    pub budget: QueryBudget,
    pub evidence_mode: EvidenceMode,
    pub planning: Planning,
    #[serde(skip)]
    pub cancellation: Cancellation,
}
/// Cheap clonable polling state for storage progress handlers; no query counters.
#[derive(Clone, Default)]
pub struct Interruption {
    pub(crate) cancellation: Cancellation,
    pub(crate) deadline: Option<Instant>,
}
impl Interruption {
    pub fn reason(&self) -> Option<&'static str> {
        if self.cancellation.is_cancelled() {
            Some("cancelled")
        } else if self.deadline.is_some_and(|d| Instant::now() >= d) {
            Some("timeout_ms")
        } else {
            None
        }
    }
    pub fn interrupted(&self) -> bool {
        self.reason().is_some()
    }
    pub fn check(&self) -> Result<()> {
        self.reason()
            .map_or(Ok(()), |r| Err(ExecutionError::Exhausted(r)))
    }
}
/// A single invocation. Consuming it prevents accidentally reusing budgets/cache.
pub struct Execution {
    pub(crate) options: ExecutionOptions,
    pub(crate) started: Instant,
    pub(crate) interruption: Interruption,
}
impl Execution {
    pub fn new(options: ExecutionOptions) -> Result<Self> {
        for (name, limit) in [
            ("max_rows", options.budget.max_rows),
            ("max_states", options.budget.max_states),
            ("max_matches", options.budget.max_matches),
            ("timeout_ms", options.budget.timeout_ms),
        ] {
            if limit == Some(0) {
                return Err(ExecutionError::Invalid(format!(
                    "query budget {name} must be positive, or None for no limit"
                )));
            }
        }
        let started = Instant::now();
        let deadline = options
            .budget
            .timeout_ms
            .map(|ms| {
                started
                    .checked_add(Duration::from_millis(ms))
                    .ok_or_else(|| ExecutionError::Invalid("query timeout is out of range".into()))
            })
            .transpose()?;
        let interruption = Interruption {
            cancellation: options.cancellation.clone(),
            deadline,
        };
        Ok(Self {
            options,
            started,
            interruption,
        })
    }
    pub fn interruption(&self) -> Interruption {
        self.interruption.clone()
    }
}
