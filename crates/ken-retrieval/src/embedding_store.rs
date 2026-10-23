//! Immutable SQLite artifacts keep prior WAL readers' source and vectors together.
use crate::{Result, RetrievalError, storage::generation};
use ken_store::WriteTransaction;
use rusqlite::{Connection, params, params_from_iter};
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, HashSet},
    sync::atomic::{AtomicU64, Ordering},
};
#[derive(Clone, Debug, PartialEq)]
pub struct VectorView {
    pub ids: Vec<i64>,
    pub matrix: Vec<Vec<f32>>,
    pub model_revision: String,
}
#[derive(Clone, Debug)]
pub struct EmbeddingInput {
    pub passage_id: i64,
    pub text: String,
    pub vector: Vec<f32>,
}
fn error(message: &str) -> RetrievalError {
    RetrievalError::Version(message.into())
}
fn digest(text: &str) -> String {
    format!("{:x}", Sha256::digest(text.as_bytes()))
}
fn decode(blob: &[u8], dimension: i64) -> Result<Vec<f32>> {
    if dimension < 0 || !blob.len().is_multiple_of(4) || blob.len() / 4 != dimension as usize {
        return Err(error(
            "invalid embedding bytes; reindex the retrieval profile",
        ));
    }
    let v: Vec<_> = blob
        .chunks_exact(4)
        .map(|b| f32::from_le_bytes(b.try_into().expect("four bytes")))
        .collect();
    if v.iter().any(|n| !n.is_finite()) {
        return Err(error(
            "invalid embedding bytes; reindex the retrieval profile",
        ));
    }
    Ok(v)
}
pub(crate) fn validated_norm(vector: &[f32], dimension: Option<usize>) -> Result<f32> {
    if vector.is_empty() || vector.iter().any(|n| !n.is_finite()) {
        return Err(RetrievalError::Invalid(
            "embedding must be a finite, nonempty vector".into(),
        ));
    }
    if dimension.is_some_and(|expected| expected != vector.len()) {
        return Err(RetrievalError::Invalid(
            "embedding dimensions differ from encoder".into(),
        ));
    }
    let norm = crate::dense_math::DenseMath::platform()?.norm(vector)?;
    if norm <= 0. || !norm.is_finite() {
        return Err(RetrievalError::Invalid(
            "embedding must have a positive finite norm".into(),
        ));
    }
    Ok(norm)
}
pub fn put_embeddings(
    tx: &WriteTransaction<'_>,
    view: &str,
    revision: &str,
    entries: &[EmbeddingInput],
) -> Result<()> {
    if !matches!(view, "identity" | "behavior") || revision.is_empty() {
        return Err(RetrievalError::Invalid(
            "view and immutable model revision required".into(),
        ));
    }
    let conn = tx.connection();
    let mut dimension = None;
    let mut prepared = Vec::new();
    let mut seen = HashSet::new();
    for entry in entries {
        if !seen.insert(entry.passage_id) {
            return Err(RetrievalError::Invalid(
                "duplicate passage embedding id".into(),
            ));
        }
        let vector = &entry.vector;
        let norm = validated_norm(vector, None)?;
        if dimension.is_some_and(|n| n != vector.len()) {
            return Err(RetrievalError::Invalid("mixed embedding dimensions".into()));
        }
        dimension = Some(vector.len());
        if !conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM ci_passages WHERE id=?1)",
            [entry.passage_id],
            |r| r.get::<_, bool>(0),
        )? {
            return Err(error(
                "source changed while encoding; reindex the retrieval profile",
            ));
        }
        let bytes: Vec<_> = vector
            .iter()
            .flat_map(|n| (n / norm).to_le_bytes())
            .collect();
        prepared.push((
            entry.passage_id,
            digest(&entry.text),
            vector.len() as i64,
            bytes,
        ));
    }
    let mut query=conn.prepare("SELECT DISTINCT dimension FROM ci_retrieval_embeddings WHERE view=?1 AND model_revision=?2")?;
    for row in query.query_map(params![view, revision], |r| r.get::<_, i64>(0))? {
        let prior = row?;
        if dimension.is_some_and(|n| n as i64 != prior) {
            return Err(error(
                "model dimension changed; reindex with an immutable revision",
            ));
        }
    }
    for (pid, hash, dimension, bytes) in &prepared {
        conn.execute("INSERT INTO ci_retrieval_embeddings(view,model_revision,text_hash,dimension,embedding)VALUES(?1,?2,?3,?4,?5)ON CONFLICT(view,model_revision,text_hash)DO NOTHING",params![view,revision,hash,dimension,bytes])?;
        let artifact:i64=conn.query_row("SELECT id FROM ci_retrieval_embeddings WHERE view=?1 AND model_revision=?2 AND text_hash=?3",params![view,revision,hash],|r|r.get(0))?;
        conn.execute("INSERT INTO ci_passage_vectors(passage_id,view,embedding_id)VALUES(?1,?2,?3)ON CONFLICT(passage_id,view)DO UPDATE SET embedding_id=excluded.embedding_id",params![pid,view,artifact])?;
    }
    if !prepared.is_empty() {
        conn.execute("INSERT INTO meta(key,value)VALUES('retrieval_generation','1')ON CONFLICT(key)DO UPDATE SET value=CAST(value AS INTEGER)+1",[])?;
    }
    Ok(())
}
pub fn load_vectors(conn: &Connection, view: &str, revision: &str) -> Result<VectorView> {
    let mut query=conn.prepare("SELECT v.passage_id,e.model_revision,e.dimension,e.embedding FROM ci_passage_vectors v JOIN ci_retrieval_embeddings e ON e.id=v.embedding_id WHERE v.view=?1 ORDER BY v.passage_id")?;
    let mut ids = Vec::new();
    let mut matrix = Vec::new();
    let mut dimension = None;
    for row in query.query_map([view], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, i64>(2)?,
            r.get::<_, Vec<u8>>(3)?,
        ))
    })? {
        let (id, actual, dim, bytes) = row?;
        if actual != revision {
            return Err(error(&format!(
                "{view} model revision mismatch; reindex the retrieval profile"
            )));
        }
        if dimension.is_some_and(|d| d != dim) {
            return Err(error(
                "mixed vector dimensions; reindex the retrieval profile",
            ));
        }
        dimension = Some(dim);
        ids.push(id);
        matrix.push(decode(&bytes, dim)?);
    }
    Ok(VectorView {
        ids,
        matrix,
        model_revision: revision.into(),
    })
}
fn placeholders(n: usize) -> String {
    std::iter::repeat_n("?", n).collect::<Vec<_>>().join(",")
}
pub fn cached_embeddings(
    conn: &Connection,
    view: &str,
    revision: &str,
    texts: &[String],
) -> Result<HashMap<String, Vec<f32>>> {
    let mut by_hash = HashMap::new();
    let mut hashes = Vec::new();
    for text in texts {
        let hash = digest(text);
        if !by_hash.contains_key(&hash) {
            hashes.push(hash.clone());
        }
        by_hash.insert(hash, text);
    }
    let mut out = HashMap::new();
    for batch in hashes.chunks(256) {
        let sql = format!(
            "SELECT text_hash,dimension,embedding FROM ci_retrieval_embeddings WHERE view=? AND model_revision=? AND text_hash IN ({})",
            placeholders(batch.len())
        );
        let mut query = conn.prepare(&sql)?;
        let mut parameters: Vec<&str> = vec![view, revision];
        parameters.extend(batch.iter().map(String::as_str));
        for row in query.query_map(params_from_iter(parameters), |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, Vec<u8>>(2)?,
            ))
        })? {
            let (hash, dim, bytes) = row?;
            let vector = decode(&bytes, dim)
                .map_err(|_| error("invalid cached artifact; rebuild retrieval embeddings"))?;
            validated_norm(&vector, None)
                .map_err(|_| error("invalid cached artifact; rebuild retrieval embeddings"))?;
            out.insert(by_hash[&hash].clone(), vector);
        }
    }
    Ok(out)
}
pub fn pending_texts(
    conn: &Connection,
    view: &str,
    revision: &str,
    texts: &[(i64, String)],
) -> Result<Vec<(i64, String)>> {
    let mut query=conn.prepare("SELECT v.passage_id,e.model_revision,e.text_hash FROM ci_passage_vectors v JOIN ci_retrieval_embeddings e ON e.id=v.embedding_id WHERE v.view=?1")?;
    let rows = query
        .query_map([view], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let current: HashMap<_, _> = rows
        .into_iter()
        .map(|(id, revision, hash)| (id, (revision, hash)))
        .collect();
    Ok(texts
        .iter()
        .filter(|(id, text)| current.get(id) != Some(&(revision.into(), digest(text))))
        .cloned()
        .collect())
}
pub fn reclaim_retired(tx: &WriteTransaction<'_>, retired: Option<&[i64]>) -> Result<usize> {
    let sql = "DELETE FROM ci_retrieval_embeddings WHERE NOT EXISTS(SELECT 1 FROM ci_passage_vectors v WHERE v.embedding_id=ci_retrieval_embeddings.id)";
    let Some(retired) = retired else {
        return Ok(tx.connection().execute(sql, [])?);
    };
    let mut count = 0;
    for batch in retired.chunks(256) {
        count += tx.connection().execute(
            &format!("{sql} AND id IN ({})", placeholders(batch.len())),
            params_from_iter(batch.iter()),
        )?;
    }
    Ok(count)
}
pub struct RetrievalSnapshot<'a> {
    conn: &'a Connection,
    name: String,
    pub generation: i64,
    active: bool,
}
impl RetrievalSnapshot<'_> {
    pub fn finish(mut self) -> Result<()> {
        self.conn
            .execute_batch(&format!("RELEASE SAVEPOINT {}", self.name))?;
        self.active = false;
        Ok(())
    }
}
impl Drop for RetrievalSnapshot<'_> {
    fn drop(&mut self) {
        if self.active {
            let _ = self
                .conn
                .execute_batch(&format!("RELEASE SAVEPOINT {}", self.name));
        }
    }
}
pub fn retrieval_snapshot(conn: &Connection) -> Result<RetrievalSnapshot<'_>> {
    static SERIAL: AtomicU64 = AtomicU64::new(0);
    let name = format!("retrieval_{}", SERIAL.fetch_add(1, Ordering::Relaxed));
    conn.execute_batch(&format!("SAVEPOINT {name}"))?;
    let mut snapshot = RetrievalSnapshot {
        conn,
        name,
        generation: 0,
        active: true,
    };
    snapshot.generation = generation(conn)?;
    Ok(snapshot)
}
