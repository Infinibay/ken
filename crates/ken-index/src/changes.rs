//! Content and extraction stamps decide whether work is necessary, without loading models.
use crate::Result;
use blake2::{
    Blake2bVar,
    digest::{Update, VariableOutput},
};
use ken_retrieval::{EXTRACTOR_VERSION, PassagePolicy};
use rusqlite::{Connection, OptionalExtension};
pub fn content_hash(bytes: &[u8]) -> [u8; 32] {
    let mut hash = Blake2bVar::new(32).expect("valid BLAKE2b digest length");
    hash.update(bytes);
    let mut out = [0; 32];
    hash.finalize_variable(&mut out)
        .expect("matching digest buffer");
    out
}
pub fn is_unchanged(
    conn: &Connection,
    path: &str,
    hash: &[u8; 32],
    need_embedding: bool,
    parser_version: i64,
    policy: &PassagePolicy,
) -> Result<bool> {
    let row=conn.query_row("SELECT content_hash,parser_version,(embedding IS NOT NULL OR vec_slot IS NOT NULL) FROM ci_files WHERE path=?1",[path],|r|Ok((r.get::<_,Vec<u8>>(0)?,r.get::<_,Option<i64>>(1)?,r.get::<_,bool>(2)?))).optional()?;
    let Some((prior, version, embedded)) = row else {
        return Ok(false);
    };
    if prior != hash || version != Some(parser_version) || (need_embedding && !embedded) {
        return Ok(false);
    }
    let row=conn.query_row("SELECT r.extractor_version,r.tokenizer_version,r.max_tokens FROM ci_retrieval_files r JOIN ci_files f ON f.id=r.file_id WHERE f.path=?1",[path],|r|Ok((r.get::<_,i64>(0)?,r.get::<_,String>(1)?,r.get::<_,i64>(2)?))).optional()?;
    Ok(row
        == Some((
            EXTRACTOR_VERSION as i64,
            policy.tokenizer_version.clone(),
            policy.max_tokens as i64,
        )))
}
