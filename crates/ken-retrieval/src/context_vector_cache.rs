//! Persistent source-only vectors keyed by exact text and immutable model policy.
use crate::{Result, RetrievalError, dense_math::DenseMath};
use rusqlite::{Connection, OptionalExtension, params};
use sha2::{Digest, Sha256};
use std::{fs, path::Path, time::Duration};
pub(crate) const CONTEXT_DIMENSION: usize = 768;
pub(crate) fn invalid(message: impl Into<String>) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
pub(crate) fn valid_vector(value: &[f32]) -> Result<()> {
    if value.len() != CONTEXT_DIMENSION || value.iter().any(|v| !v.is_finite()) {
        return Err(invalid("context cache requires a normalized finite vector"));
    }
    let norm = DenseMath::platform()?.norm(value)?;
    if !norm.is_finite() || (norm - 1.).abs() > 2e-5 {
        return Err(invalid("context cache requires a normalized finite vector"));
    }
    Ok(())
}
pub struct ContextVectorCache {
    connection: Connection,
    model: String,
}
impl ContextVectorCache {
    pub fn open(directory: &Path, model_key: &str) -> Result<Self> {
        fs::create_dir_all(directory)
            .map_err(|e| invalid(format!("context cache directory: {e}")))?;
        let connection = Connection::open(directory.join("vectors.db"))?;
        connection.busy_timeout(Duration::from_secs(60))?;
        connection.execute("CREATE TABLE IF NOT EXISTS vectors(model TEXT, hash TEXT, text TEXT, vector BLOB, PRIMARY KEY(model,hash))",[])?;
        Ok(Self {
            connection,
            model: model_key.into(),
        })
    }
    pub fn get(&self, text: &str) -> Result<Option<Vec<f32>>> {
        let hash = format!("{:x}", Sha256::digest(text.as_bytes()));
        let row = self
            .connection
            .query_row(
                "SELECT text,vector FROM vectors WHERE model=?1 AND hash=?2",
                params![self.model, hash],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?)),
            )
            .optional()?;
        let Some((stored, blob)) = row else {
            return Ok(None);
        };
        if stored != text {
            return Err(invalid("context cache text identity mismatch"));
        }
        if !blob.len().is_multiple_of(4) {
            return Err(invalid("buffer size must be a multiple of element size"));
        }
        let vector = blob
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes(b.try_into().expect("four bytes")))
            .collect::<Vec<_>>();
        valid_vector(&vector)?;
        Ok(Some(vector))
    }
    pub fn put_many(&mut self, items: &[(String, Vec<f32>)]) -> Result<()> {
        let tx = self.connection.transaction()?;
        for (text, vector) in items {
            valid_vector(vector)?;
            let hash = format!("{:x}", Sha256::digest(text.as_bytes()));
            let bytes = vector
                .iter()
                .flat_map(|v| v.to_le_bytes())
                .collect::<Vec<_>>();
            tx.execute(
                "INSERT OR IGNORE INTO vectors VALUES (?1,?2,?3,?4)",
                params![self.model, hash, text, bytes],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
    pub fn count(&self) -> Result<usize> {
        let n = self.connection.query_row(
            "SELECT COUNT(*) FROM vectors WHERE model=?1",
            [&self.model],
            |r| r.get::<_, i64>(0),
        )?;
        usize::try_from(n).map_err(|_| invalid("context cache count exceeds native range"))
    }
}
