//! Reembedding policy stages all five spaces, then publishes one guarded generation.
use crate::{Error, MaintenanceApplication, Result};
use base64::{Engine, engine::general_purpose::STANDARD};
use ken_retrieval::{DocumentEncoder, query_encoder::QueryEncoder};
use ken_store::{MaintenanceEvent, StoreError, VectorRebuild, VectorSpace};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
pub const PROBE_TEXT: &str = "Hola mundo — ken embedding probe / prueba de codificación";
const IN_PROGRESS: &str = "reembed_in_progress";
const OWNER: &str = "__ken_reembed_owner";
#[derive(Clone, Debug)]
pub struct ReembedOptions {
    pub batch_size: usize,
    pub now_ms: i64,
}
impl Default for ReembedOptions {
    fn default() -> Self {
        Self {
            batch_size: 256,
            now_ms: crate::now_ms(),
        }
    }
}
#[derive(Debug)]
pub enum ReembedEvent {
    Begin,
    Encoded { space: &'static str, count: usize },
    ReadyToPublish,
    Storage(MaintenanceEvent),
}
#[derive(Debug, Serialize)]
pub struct ReembedReport {
    pub files: usize,
    pub symbols: usize,
    pub intent: usize,
    pub prompts: usize,
    pub findings: usize,
    pub model: String,
    pub dim: Option<usize>,
}
#[derive(Debug, Serialize)]
pub struct StoredEmbeddingInfo {
    pub model: Option<String>,
    pub dim: Option<i64>,
}
#[derive(Debug, Serialize)]
pub struct ProbeReport {
    pub stored_model: Option<String>,
    pub stored_dim: Option<i64>,
    pub live_model: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub live_dim: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub probe_cosine: Option<f64>,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}
#[derive(Debug, Serialize, Deserialize, PartialEq)]
struct Row {
    id: i64,
    text: String,
}
#[derive(Debug, PartialEq)]
struct Sources {
    symbols: Vec<Row>,
    files: Vec<Row>,
    intent: Vec<Row>,
    prompts: Vec<Row>,
    findings: Vec<Row>,
    metadata: BTreeMap<String, Option<String>>,
}
fn meta(conn: &Connection, key: &str) -> rusqlite::Result<Option<String>> {
    Ok(conn
        .query_row("SELECT value FROM meta WHERE key=?", [key], |r| {
            r.get::<_, Option<String>>(0)
        })
        .optional()?
        .flatten())
}
fn rows(conn: &Connection, sql: &str) -> Result<Vec<Row>> {
    Ok(conn
        .prepare(sql)?
        .query_map([], |r| {
            Ok(Row {
                id: r.get(0)?,
                text: r.get(1)?,
            })
        })?
        .collect::<rusqlite::Result<_>>()?)
}
fn sources(conn: &Connection) -> Result<Sources> {
    let mut symbols = Vec::new();
    let mut statement=conn.prepare("SELECT id,kind,name,docstring FROM ci_symbols WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL ORDER BY id")?;
    for row in statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, Option<String>>(3)?,
        ))
    })? {
        let (id, kind, name, doc) = row?;
        symbols.push(Row {
            id,
            text: ken_index::embedding_text::symbol_text(&kind, &name, doc.as_deref()),
        });
    }
    let mut files = Vec::new();
    let mut statement = conn.prepare("SELECT id,path,language FROM ci_files ORDER BY id")?;
    for row in statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, Option<String>>(2)?,
        ))
    })? {
        let (id, path, language) = row?;
        let mut top = conn
            .prepare("SELECT name FROM ci_symbols WHERE file_id=? ORDER BY line_start LIMIT 8")?;
        let names = top
            .query_map([id], |r| r.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let names = names.iter().map(String::as_str).collect::<Vec<_>>();
        files.push(Row {
            id,
            text: ken_index::embedding_text::file_text(language.as_deref(), &path, &names),
        });
    }
    let mut intent = Vec::new();
    let mut statement=conn.prepare("SELECT id,source_kind,text FROM ci_intent_sources WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL ORDER BY id")?;
    for row in statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
        ))
    })? {
        let (id, kind, text) = row?;
        intent.push(Row {
            id,
            text: ken_index::embedding_text::intent_text(&kind, &text),
        });
    }
    let prompts = rows(
        conn,
        "SELECT id,content FROM cr_contexts WHERE embedding IS NOT NULL ORDER BY id",
    )?;
    let mut findings = Vec::new();
    let mut statement = conn.prepare(
        "SELECT id,topic,content FROM cr_findings WHERE embedding IS NOT NULL ORDER BY id",
    )?;
    for row in statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
        ))
    })? {
        let (id, topic, content) = row?;
        findings.push(Row {
            id,
            text: format!(
                "{topic}\n\n{}",
                content.chars().take(1024).collect::<String>()
            ),
        });
    }
    let mut metadata = BTreeMap::new();
    for key in [
        "embed_model",
        "embed_dim",
        "embed_doc_space",
        "embed_probe_text",
        "embed_probe_vec",
        "embed_reencoded_at",
    ] {
        metadata.insert(key.into(), meta(conn, key)?);
    }
    Ok(Sources {
        symbols,
        files,
        intent,
        prompts,
        findings,
        metadata,
    })
}
fn validate(vectors: &[Vec<f32>], count: usize, dim: usize) -> Result<()> {
    if vectors.len() != count
        || dim == 0
        || vectors
            .iter()
            .any(|vector| vector.len() != dim || vector.iter().any(|n| !n.is_finite()))
    {
        return Err(Error::Invalid(
            "encoder vectors must be finite and match declared dimension and row count".into(),
        ));
    }
    Ok(())
}
fn blob(vector: &[f32]) -> Vec<u8> {
    vector.iter().flat_map(|n| n.to_le_bytes()).collect()
}
impl MaintenanceApplication {
    pub fn stored_embedding_info(&self) -> Result<StoredEmbeddingInfo> {
        Ok(StoredEmbeddingInfo {
            model: self.store.database().get_meta("embed_model")?,
            dim: self
                .store
                .database()
                .get_meta("embed_dim")?
                .and_then(|value| value.parse().ok()),
        })
    }
    pub fn interrupted_reembed(&self) -> Result<Option<String>> {
        Ok(self.store.database().get_meta(IN_PROGRESS)?)
    }
    pub fn embedding_mismatch(&self, model: &str) -> Result<Option<String>> {
        Ok(self.stored_embedding_info()?.model.filter(|stored|stored!=model).map(|stored|format!("database was encoded with '{stored}' but the active model is '{model}' — run `ken reembed` to re-encode")))
    }
    pub fn reembed(
        &mut self,
        model: &str,
        documents: &dyn DocumentEncoder,
        queries: &dyn QueryEncoder,
        options: &ReembedOptions,
        progress: &mut impl FnMut(ReembedEvent),
    ) -> Result<ReembedReport> {
        if options.batch_size == 0 || model.is_empty() {
            return Err(Error::Invalid(
                "positive batch size and nonempty model required".into(),
            ));
        }
        let dim = documents.dim()?;
        if dim == 0 {
            return Err(Error::Invalid("positive encoder dimension required".into()));
        }
        let conn = self.store.database().connection();
        let read = conn.unchecked_transaction()?;
        let captured = sources(&read)?;
        read.commit()?;
        let spool_file = tempfile::NamedTempFile::new_in(
            self.paths.db().parent().expect("project database parent"),
        )?;
        let owner = spool_file
            .path()
            .file_name()
            .expect("temporary basename")
            .to_string_lossy()
            .into_owned();
        {
            let tx = self.store.database_mut().immediate()?;
            tx.connection().execute("INSERT INTO meta(key,value)VALUES(?1,?2)ON CONFLICT(key)DO UPDATE SET value=excluded.value",params![IN_PROGRESS,options.now_ms.to_string()])?;
            tx.connection().execute("INSERT INTO meta(key,value)VALUES(?1,?2)ON CONFLICT(key)DO UPDATE SET value=excluded.value",params![OWNER,owner])?;
            tx.commit()?;
        }
        progress(ReembedEvent::Begin);
        let mut replacement = VectorRebuild::begin(&self.store, dim, Some(model))?;
        let spool = Connection::open(spool_file.path())?;
        spool.execute_batch("CREATE TABLE encoded(table_name TEXT,id INTEGER,vector BLOB,PRIMARY KEY(table_name,id))")?;
        let mut encoded_any = false;
        for (space, name, items) in [
            (VectorSpace::Symbols, "symbols", &captured.symbols),
            (VectorSpace::Files, "files", &captured.files),
            (VectorSpace::IntentSources, "intent", &captured.intent),
        ] {
            let mut count = 0;
            for chunk in items.chunks(options.batch_size) {
                let texts = chunk
                    .iter()
                    .map(|row| row.text.as_str())
                    .collect::<Vec<_>>();
                let vectors = documents.embed_passages(&texts)?;
                validate(&vectors, chunk.len(), dim)?;
                replacement.write(
                    space,
                    &chunk.iter().map(|row| row.id).collect::<Vec<_>>(),
                    &vectors,
                )?;
                encoded_any = true;
                count += chunk.len();
                progress(ReembedEvent::Encoded { space: name, count });
            }
        }
        for (name, table, items, query_side) in [
            ("prompts", "cr_contexts", &captured.prompts, true),
            ("findings", "cr_findings", &captured.findings, false),
        ] {
            let mut count = 0;
            for chunk in items.chunks(options.batch_size) {
                let vectors = if query_side {
                    chunk
                        .iter()
                        .map(|row| queries.embed_query(&row.text.as_str().into()))
                        .collect::<ken_retrieval::Result<Vec<_>>>()?
                } else {
                    documents.embed_passages(
                        &chunk
                            .iter()
                            .map(|row| row.text.as_str())
                            .collect::<Vec<_>>(),
                    )?
                };
                validate(&vectors, chunk.len(), dim)?;
                let tx = spool.unchecked_transaction()?;
                for (row, vector) in chunk.iter().zip(vectors) {
                    tx.execute(
                        "INSERT INTO encoded VALUES(?1,?2,?3)",
                        params![table, row.id, blob(&vector)],
                    )?;
                }
                tx.commit()?;
                encoded_any = true;
                count += chunk.len();
                progress(ReembedEvent::Encoded { space: name, count });
            }
        }
        let probe = queries.embed_query(&PROBE_TEXT.into())?;
        validate(std::slice::from_ref(&probe), 1, dim)?;
        let probe = STANDARD.encode(blob(&probe));
        progress(ReembedEvent::ReadyToPublish);
        let database = self.paths.db();
        let report_dim = encoded_any.then_some(dim);
        replacement.commit(&mut self.store,|tx|{
            let run=(||->Result<()>{let conn=tx.connection();if meta(conn,OWNER)?.as_deref()!=Some(owner.as_str())||sources(conn)?!=captured{return Err(Error::Invalid("source or model metadata changed while reencoding; retry reembed".into()));}
                let mut statement=spool.prepare("SELECT table_name,id,vector FROM encoded ORDER BY table_name,id")?;let mut rows=statement.query([])?;while let Some(row)=rows.next()?{let table:String=row.get(0)?;let id:i64=row.get(1)?;let vector:Vec<u8>=row.get(2)?;conn.execute(&format!("UPDATE {table} SET embedding=?1 WHERE id=?2"),params![vector,id])?;}
                for(key,value)in[("embed_model",model.to_owned()),("embed_doc_space","2".into()),("embed_probe_text",PROBE_TEXT.into()),("embed_probe_vec",probe),("embed_reencoded_at",options.now_ms.to_string())]{conn.execute("INSERT INTO meta(key,value)VALUES(?1,?2)ON CONFLICT(key)DO UPDATE SET value=excluded.value",params![key,value])?;}
                if let Some(dim)=report_dim{conn.execute("INSERT INTO meta(key,value)VALUES('embed_dim',?1)ON CONFLICT(key)DO UPDATE SET value=excluded.value",[dim.to_string()])?;}
                conn.execute("DELETE FROM meta WHERE key IN(?1,?2)",params![IN_PROGRESS,OWNER])?;Ok(())})();run.map_err(|error|StoreError::Recovery{path:database.clone(),reason:error.to_string()})
        },&mut |event|progress(ReembedEvent::Storage(event)))?;
        Ok(ReembedReport {
            files: captured.files.len(),
            symbols: captured.symbols.len(),
            intent: captured.intent.len(),
            prompts: captured.prompts.len(),
            findings: captured.findings.len(),
            model: model.into(),
            dim: report_dim,
        })
    }
    pub fn validate_embeddings(
        &self,
        model: &str,
        queries: &dyn QueryEncoder,
    ) -> Result<ProbeReport> {
        let info = self.stored_embedding_info()?;
        let mut report = ProbeReport {
            stored_model: info.model,
            stored_dim: info.dim,
            live_model: model.into(),
            live_dim: None,
            probe_cosine: None,
            ok: false,
            reason: None,
        };
        let Some(raw) = self.store.database().get_meta("embed_probe_vec")? else {
            report.reason = Some("no probe stored — run `ken reembed`".into());
            return Ok(report);
        };
        let raw = STANDARD
            .decode(raw)
            .map_err(|_| Error::Invalid("stored embedding probe is not base64".into()))?;
        if raw.is_empty() || raw.len() % 4 != 0 {
            return Err(Error::Invalid(
                "stored embedding probe must contain float32 values".into(),
            ));
        }
        let stored = raw
            .chunks_exact(4)
            .map(|bytes| f32::from_le_bytes(bytes.try_into().expect("four bytes")))
            .collect::<Vec<_>>();
        let text = self
            .store
            .database()
            .get_meta("embed_probe_text")?
            .filter(|text| !text.is_empty())
            .unwrap_or_else(|| PROBE_TEXT.into());
        let live = queries.embed_query(&text.as_str().into())?;
        report.live_dim = Some(live.len());
        if stored.len() != live.len() {
            report.reason = Some(format!(
                "dimension changed {} -> {}; every stored vector is unusable — run `ken reembed`",
                stored.len(),
                live.len()
            ));
            return Ok(report);
        }
        validate(std::slice::from_ref(&live), 1, stored.len())?;
        if stored.iter().any(|n| !n.is_finite()) {
            return Err(Error::Invalid(
                "stored embedding probe is not finite".into(),
            ));
        }
        let math = ken_retrieval::vector_math::NativeVectorMath::platform()?;
        let dot = math.scores(&stored, 1, stored.len(), &live)?[0];
        let cosine = dot / (math.query_norm(&stored)? * math.query_norm(&live)? + 1e-12f32);
        if !cosine.is_finite() {
            return Err(Error::Invalid(
                "embedding probe arithmetic is not finite".into(),
            ));
        }
        let cosine = f64::from(cosine);
        report.probe_cosine = Some(crate::round(cosine, 6));
        if cosine < 0.9995 {
            report.reason = Some(format!(
                "probe cosine {cosine:.4} < 0.9995 — the live embedder no longer matches the stored vector space; run `ken reembed`"
            ));
        } else {
            report.ok = true;
        }
        Ok(report)
    }
}
