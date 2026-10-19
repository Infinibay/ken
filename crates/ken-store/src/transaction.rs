use crate::{StoreError, StoreResult, StoredModelState, model_state};
use rusqlite::{Connection, OpenFlags, Transaction};
use std::path::PathBuf;

#[derive(Debug)]
pub struct WriteTransaction<'a> {
    inner: Transaction<'a>,
    path: PathBuf,
}

impl<'a> WriteTransaction<'a> {
    pub(crate) fn new(inner: Transaction<'a>, path: PathBuf) -> Self {
        Self { inner, path }
    }
    pub fn connection(&self) -> &Connection {
        &self.inner
    }

    /// The IMMEDIATE writer lock prevents other commits while this independent
    /// reader sees owners that this transaction could restore on rollback.
    pub(crate) fn committed_connection(&self) -> StoreResult<Connection> {
        Connection::open_with_flags(
            &self.path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(|e| StoreError::sqlite(&self.path, e))
    }

    pub fn model_state(&self) -> StoreResult<StoredModelState> {
        model_state::read(&self.inner).map_err(|e| StoreError::sqlite(&self.path, e))
    }

    pub fn pin_model_if_fresh(&mut self, model: &str, document_space: u32) -> StoreResult<bool> {
        // Failed publication must not leave half a pin even if the caller handles
        // the error and commits other work in the outer transaction.
        let savepoint = self
            .inner
            .savepoint()
            .map_err(|e| StoreError::sqlite(&self.path, e))?;
        let changed = model_state::pin_if_fresh(&savepoint, model, document_space)
            .map_err(|e| StoreError::sqlite(&self.path, e))?;
        savepoint
            .commit()
            .map_err(|e| StoreError::sqlite(&self.path, e))?;
        Ok(changed)
    }

    pub fn commit(self) -> StoreResult<()> {
        self.inner
            .commit()
            .map_err(|e| StoreError::sqlite(&self.path, e))
    }
}
