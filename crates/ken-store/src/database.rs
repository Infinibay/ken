use crate::{StoreError, StoreResult, StoredModelState, WriteTransaction, model_state, schema};
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior};
use std::{
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Debug)]
pub struct ProjectDatabase {
    connection: Connection,
    path: PathBuf,
}

impl ProjectDatabase {
    pub fn open(path: &Path) -> StoreResult<Self> {
        let open = || -> rusqlite::Result<Connection> {
            // A filesystem path is not an SQLite URI. Unix OsStr bytes survive.
            let conn = Connection::open_with_flags(
                path,
                OpenFlags::SQLITE_OPEN_READ_WRITE
                    | OpenFlags::SQLITE_OPEN_CREATE
                    | OpenFlags::SQLITE_OPEN_NO_MUTEX,
            )?;
            conn.pragma_update(None, "journal_mode", "WAL")?;
            conn.pragma_update(None, "synchronous", "NORMAL")?;
            conn.pragma_update(None, "foreign_keys", true)?;
            conn.busy_timeout(Duration::from_millis(5000))?;
            Ok(conn)
        };
        Ok(Self {
            connection: open().map_err(|e| StoreError::sqlite(path, e))?,
            path: path.into(),
        })
    }

    pub fn initialize(&mut self) -> StoreResult<()> {
        schema::initialize(&mut self.connection).map_err(|e| StoreError::sqlite(&self.path, e))
    }

    pub fn connection(&self) -> &Connection {
        &self.connection
    }

    pub fn get_meta(&self, key: &str) -> StoreResult<Option<String>> {
        get_meta(&self.connection, key).map_err(|e| StoreError::sqlite(&self.path, e))
    }

    pub fn set_meta(&self, key: &str, value: &str) -> StoreResult<()> {
        set_meta(&self.connection, key, value).map_err(|e| StoreError::sqlite(&self.path, e))
    }

    pub fn model_state(&self) -> StoreResult<StoredModelState> {
        model_state::read(&self.connection).map_err(|e| StoreError::sqlite(&self.path, e))
    }

    pub fn immediate(&mut self) -> StoreResult<WriteTransaction<'_>> {
        let path = self.path.clone();
        let inner = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|e| StoreError::sqlite(&path, e))?;
        Ok(WriteTransaction::new(inner, path))
    }
}

pub(crate) fn get_meta(conn: &Connection, key: &str) -> rusqlite::Result<Option<String>> {
    conn.query_row("SELECT value FROM meta WHERE key=?1", [key], |r| {
        r.get::<_, Option<String>>(0)
    })
    .optional()
    .map(Option::flatten)
}

pub(crate) fn set_meta(conn: &Connection, key: &str, value: &str) -> rusqlite::Result<()> {
    conn.execute("INSERT INTO meta(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        [key,value]).map(|_|())
}
