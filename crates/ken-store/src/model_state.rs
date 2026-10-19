use crate::database::{get_meta, set_meta};
use rusqlite::Connection;

const MODEL_KEY: &str = "embed_model";
const DOCUMENT_SPACE_KEY: &str = "embed_doc_space";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredModelState {
    pub recorded_model: Option<String>,
    pub file_vectors_present: bool,
}

pub(crate) fn read(conn: &Connection) -> rusqlite::Result<StoredModelState> {
    Ok(StoredModelState {
        recorded_model: get_meta(conn, MODEL_KEY)?,
        file_vectors_present: conn.query_row("SELECT EXISTS(SELECT 1 FROM ci_files WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL)",[],|r|r.get(0))?,
    })
}

pub(crate) fn pin_if_fresh(
    conn: &Connection,
    model: &str,
    document_space: u32,
) -> rusqlite::Result<bool> {
    let state = read(conn)?;
    if state.recorded_model.is_some() || state.file_vectors_present {
        return Ok(false);
    }
    set_meta(conn, MODEL_KEY, model)?;
    set_meta(conn, DOCUMENT_SPACE_KEY, &document_space.to_string())?;
    Ok(true)
}
