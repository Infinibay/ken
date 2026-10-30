//! One absolute budget includes admission, identity work and publication.
use super::{QueryEngine, Result, execution};
use std::time::{Duration, Instant};
pub(super) struct Operation {
    start: Instant,
    total: Duration,
}
impl Operation {
    pub fn new(start: Instant, total: Duration) -> Self {
        Self { start, total }
    }
    pub fn check(&self, engine: &dyn QueryEngine) -> Result<()> {
        engine.checkpoint()?;
        execution::remaining(self.start, self.total)?;
        Ok(())
    }
    pub fn remaining(&self, engine: &dyn QueryEngine) -> Result<Duration> {
        self.check(engine)?;
        execution::remaining(self.start, self.total)
    }
    pub fn identity(&self, engine: &dyn QueryEngine) -> Result<String> {
        self.check(engine)?;
        engine.identity_checked(&mut || self.check(engine))
    }
}
