//! Publish one canonical file and its dependents as one IMMEDIATE transaction.
pub use crate::legacy::LegacyStores;
use crate::{DocumentTarget, IndexError, PreparedFile, Result, legacy, postings};
use ken_retrieval::{PassagePolicy, storage::replace_file_passages};
use ken_store::{ProjectDatabase, VectorSpace};
use rusqlite::{Connection, params};
use std::collections::BTreeSet;
pub struct WriterOptions<'a> {
    pub stores: Option<&'a LegacyStores>,
    pub stopwords: &'a BTreeSet<String>,
    pub policy: &'a PassagePolicy,
    pub now_ms: &'a dyn Fn() -> i64,
    pub parser_version: i64,
}
pub struct IndexWriter;
impl IndexWriter {
    pub fn publish(
        db: &mut ProjectDatabase,
        file: &PreparedFile,
        options: &WriterOptions<'_>,
    ) -> Result<i64> {
        if file
            .vectors
            .values()
            .any(|v| v.is_empty() || v.iter().any(|n| !n.is_finite()))
        {
            return Err(IndexError::Invalid(
                "document vectors must be finite and nonempty".into(),
            ));
        }
        let mut tx = db.immediate()?;
        let s = &file.source;
        let count = file.parsed.as_ref().map_or(0, |p| p.symbols.len());
        let embedding = legacy::blob(file, &DocumentTarget::File, options.stores);
        tx.connection().execute("INSERT INTO ci_files(path,language,content_hash,parser_version,symbol_count,mtime,indexed_at,embedding)VALUES(?1,?2,?3,?4,?5,?6,?7,?8)ON CONFLICT(path)DO UPDATE SET language=excluded.language,content_hash=excluded.content_hash,parser_version=excluded.parser_version,symbol_count=excluded.symbol_count,mtime=excluded.mtime,indexed_at=excluded.indexed_at,embedding=excluded.embedding",params![s.path,s.language,s.content_hash.as_slice(),options.parser_version,count as i64,s.mtime_ns,(options.now_ms)(),embedding])?;
        let file_id =
            tx.connection()
                .query_row("SELECT id FROM ci_files WHERE path=?1", [&s.path], |r| {
                    r.get::<_, i64>(0)
                })?;
        postings::write_file(tx.connection(), file_id, &s.path, options.stopwords)?;
        tx.connection()
            .execute("DELETE FROM ci_symbols WHERE file_id=?1", [file_id])?;
        tx.connection()
            .execute("DELETE FROM ci_imports WHERE from_file_id=?1", [file_id])?;
        tx.connection()
            .execute("DELETE FROM ci_intent_sources WHERE file_id=?1", [file_id])?;
        legacy::file_vector(&mut tx, options.stores, file_id, file)?;
        if let Some(parsed) = &file.parsed {
            let symbol_vectors: Vec<_> = (0..parsed.symbols.len())
                .map(|i| {
                    file.vectors
                        .get(&DocumentTarget::Symbol(i))
                        .map(Vec::as_slice)
                })
                .collect();
            let slots = legacy::vectors(
                &mut tx,
                options.stores,
                VectorSpace::Symbols,
                &symbol_vectors,
            )?;
            let mut intent_vectors = Vec::new();
            if parsed.docstring.as_ref().is_some_and(|s| !s.is_empty()) {
                intent_vectors.push(
                    file.vectors
                        .get(&DocumentTarget::ModuleDoc)
                        .map(Vec::as_slice),
                );
            }
            for (i, s) in parsed.symbols.iter().enumerate() {
                if s.docstring.as_ref().is_some_and(|s| !s.is_empty()) {
                    intent_vectors.push(
                        file.vectors
                            .get(&DocumentTarget::SymbolDoc(i))
                            .map(Vec::as_slice),
                    );
                }
            }
            let intent_slots = legacy::vectors(
                &mut tx,
                options.stores,
                VectorSpace::IntentSources,
                &intent_vectors,
            )?;
            let mut intent_slots = intent_slots.into_iter();
            if let Some(doc) = parsed.docstring.as_deref().filter(|s| !s.is_empty()) {
                insert_intent(
                    tx.connection(),
                    Intent {
                        file: file_id,
                        symbol: None,
                        kind: "module_docstring",
                        text: doc,
                        embedding: legacy::blob(file, &DocumentTarget::ModuleDoc, options.stores),
                        slot: intent_slots.next().expect("one slot per intent"),
                        weight: 1.,
                    },
                    options.now_ms,
                )?;
            }
            let mut insert=tx.connection().prepare("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,docstring,embedding,vec_slot)VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)")?;
            for (i, s) in parsed.symbols.iter().enumerate() {
                insert.execute(params![
                    file_id,
                    s.kind,
                    s.name,
                    s.qualname,
                    s.line_start as i64,
                    s.line_end as i64,
                    s.docstring,
                    legacy::blob(file, &DocumentTarget::Symbol(i), options.stores),
                    slots[i]
                ])?;
                let id = tx.connection().last_insert_rowid();
                postings::write_symbol(
                    tx.connection(),
                    id,
                    &s.kind,
                    Some(&s.qualname),
                    &s.name,
                    options.stopwords,
                )?;
                if let Some(doc) = s.docstring.as_deref().filter(|s| !s.is_empty()) {
                    insert_intent(
                        tx.connection(),
                        Intent {
                            file: file_id,
                            symbol: Some(id),
                            kind: "symbol_docstring",
                            text: doc,
                            embedding: legacy::blob(
                                file,
                                &DocumentTarget::SymbolDoc(i),
                                options.stores,
                            ),
                            slot: intent_slots.next().expect("one slot per intent"),
                            weight: 1.,
                        },
                        options.now_ms,
                    )?;
                }
            }
            let mut insert = tx
                .connection()
                .prepare("INSERT INTO ci_imports(from_file_id,to_module,line)VALUES(?1,?2,?3)")?;
            for import in &parsed.imports {
                insert.execute(params![file_id, import.module, import.line as i64])?;
            }
        } else {
            let vectors: Vec<_> = (0..file.intent_texts.len())
                .map(|i| {
                    file.vectors
                        .get(&DocumentTarget::PlainIntent(i))
                        .map(Vec::as_slice)
                })
                .collect();
            let slots = legacy::vectors(
                &mut tx,
                options.stores,
                VectorSpace::IntentSources,
                &vectors,
            )?;
            for (i, text) in file.intent_texts.iter().enumerate() {
                insert_intent(
                    tx.connection(),
                    Intent {
                        file: file_id,
                        symbol: None,
                        kind: "plain_text",
                        text,
                        embedding: legacy::blob(
                            file,
                            &DocumentTarget::PlainIntent(i),
                            options.stores,
                        ),
                        slot: slots[i],
                        weight: 0.55,
                    },
                    options.now_ms,
                )?;
            }
        }
        replace_file_passages(
            &tx,
            file_id,
            &file.passages,
            Some(&file.source_sha256),
            options.policy,
        )?;
        tx.commit()?;
        Ok(file_id)
    }
}
struct Intent<'a> {
    file: i64,
    symbol: Option<i64>,
    kind: &'a str,
    text: &'a str,
    embedding: Option<Vec<u8>>,
    slot: Option<i64>,
    weight: f64,
}
fn insert_intent(conn: &Connection, value: Intent<'_>, clock: &dyn Fn() -> i64) -> Result<()> {
    conn.execute("INSERT INTO ci_intent_sources(file_id,symbol_id,source_kind,text,embedding,vec_slot,weight,updated_at)VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",params![value.file,value.symbol,value.kind,value.text,value.embedding,value.slot,value.weight,clock()])?;
    Ok(())
}
pub fn delete_file(conn: &Connection, path: &str) -> Result<bool> {
    Ok(conn.execute("DELETE FROM ci_files WHERE path=?1", [path])? > 0)
}
pub fn delete_path(conn: &Connection, path: &str) -> Result<usize> {
    let path = path.trim_end_matches('/');
    let prefix = format!("{path}/");
    Ok(conn.execute(
        "DELETE FROM ci_files WHERE path=?1 OR substr(path,1,?2)=?3",
        params![path, prefix.chars().count() as i64, prefix],
    )?)
}
