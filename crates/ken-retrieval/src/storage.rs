//! Passage publication participates in the canonical file's transaction.
use crate::{
    EXTRACTOR_VERSION, EntityKey, Passage, PassageFields, PassagePolicy, Result, RetrievalError,
    Span, vocabulary::code_tokens,
};
use ken_store::WriteTransaction;
use rusqlite::{Connection, OptionalExtension, params, params_from_iter};
use serde::{Serialize, Serializer, ser::SerializeMap};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap};
struct ScalarFields<'a>(&'a [(&'static str, String); 5]);
impl Serialize for ScalarFields<'_> {
    fn serialize<S: Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        let mut map = s.serialize_map(Some(5))?;
        for (k, v) in self.0 {
            map.serialize_entry(k, v)?;
        }
        map.end()
    }
}
pub fn generation(conn: &Connection) -> Result<i64> {
    let value: Option<String> = conn
        .query_row(
            "SELECT value FROM meta WHERE key='retrieval_generation'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    value.map_or(Ok(0), |s| {
        s.parse()
            .map_err(|_| RetrievalError::Invalid("invalid retrieval generation".into()))
    })
}
pub fn replace_file_passages(
    tx: &WriteTransaction<'_>,
    file_id: i64,
    passages: &[Passage],
    source_hash: Option<&str>,
    policy: &PassagePolicy,
) -> Result<Vec<i64>> {
    let conn = tx.connection();
    let mut symbols = HashMap::new();
    let mut query = conn
        .prepare("SELECT id,kind,qualname,line_start,line_end FROM ci_symbols WHERE file_id=?1")?;
    for row in query.query_map([file_id], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, Option<String>>(2)?,
            r.get::<_, i64>(3)?,
            r.get::<_, i64>(4)?,
        ))
    })? {
        let (id, kind, name, start, end) = row?;
        symbols.insert((kind, name, start, end), id);
    }
    conn.execute("DELETE FROM ci_passages WHERE file_id=?1", [file_id])?;
    let mut ids = Vec::new();
    let mut insert_terms =
        conn.prepare("INSERT INTO ci_passage_terms(passage_id,field,term,tf)VALUES(?1,?2,?3,?4)")?;
    let mut insert_length =
        conn.prepare("INSERT INTO ci_passage_lengths(passage_id,field,length)VALUES(?1,?2,?3)")?;
    for p in passages {
        let symbol_id = if p.entity.qualname.is_some() {
            Some(
                *symbols
                    .get(&(
                        p.entity.kind.clone(),
                        p.entity.qualname.clone(),
                        p.entity_span.start_line as i64,
                        p.entity_span.end_line as i64,
                    ))
                    .ok_or_else(|| {
                        RetrievalError::Invalid(format!(
                            "passage has no canonical symbol: {}",
                            p.entity.qualname.as_deref().unwrap_or("")
                        ))
                    })?,
            )
        } else {
            None
        };
        let fields = p.fields.scalar()?;
        let fields_json = serde_json::to_string(&ScalarFields(&fields))?;
        conn.execute("INSERT INTO ci_passages(file_id,symbol_id,line_start,line_end,fields_json,role,split_reason,implementation_start_line)VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",params![file_id,symbol_id,p.span.start_line as i64,p.span.end_line as i64,fields_json,p.role,p.split_reason,p.implementation_start_line.map(|n|n as i64)])?;
        let id = conn.last_insert_rowid();
        ids.push(id);
        for (name, text) in fields {
            let mut counts: BTreeMap<String, i64> = BTreeMap::new();
            for token in code_tokens(&text) {
                *counts.entry(token).or_default() += 1;
            }
            insert_length.execute(params![id, name, counts.values().sum::<i64>()])?;
            for (term, count) in counts {
                insert_terms.execute(params![id, name, term, count])?;
            }
        }
    }
    let empty = format!("{:x}", Sha256::digest([]));
    let digest = source_hash
        .filter(|s| !s.is_empty())
        .or_else(|| passages.first().map(|p| p.source_hash.as_str()))
        .unwrap_or(&empty);
    if passages.iter().any(|p| p.source_hash != digest) {
        return Err(RetrievalError::Invalid(
            "mixed source generations in passage replacement".into(),
        ));
    }
    conn.execute("INSERT INTO ci_retrieval_files(file_id,source_hash,extractor_version,tokenizer_version,max_tokens)VALUES(?1,?2,?3,?4,?5)ON CONFLICT(file_id)DO UPDATE SET source_hash=excluded.source_hash,extractor_version=excluded.extractor_version,tokenizer_version=excluded.tokenizer_version,max_tokens=excluded.max_tokens",params![file_id,digest,EXTRACTOR_VERSION as i64,policy.tokenizer_version,policy.max_tokens as i64])?;
    Ok(ids)
}
pub fn source_extractor_current(conn: &Connection) -> Result<bool> {
    Ok(!conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM ci_retrieval_files WHERE extractor_version!=?1)",
        [EXTRACTOR_VERSION as i64],
        |r| r.get::<_, bool>(0),
    )?)
}
fn placeholders(n: usize) -> String {
    std::iter::repeat_n("?", n).collect::<Vec<_>>().join(",")
}
fn positive(n: i64) -> Result<usize> {
    usize::try_from(n).map_err(|_| RetrievalError::Invalid("negative source coordinate".into()))
}
pub fn load_passage_map(conn: &Connection, ids: Option<&[i64]>) -> Result<Vec<(i64, Passage)>> {
    if ids.is_some_and(|i| i.is_empty()) {
        return Ok(vec![]);
    }
    if !source_extractor_current(conn)? {
        return Err(RetrievalError::Version(
            "source extraction policy changed; prepare the search index again".into(),
        ));
    }
    let mut sql="SELECT p.id,p.file_id,p.symbol_id,p.line_start,p.line_end,p.fields_json,p.role,p.split_reason,p.implementation_start_line,f.path,f.language,r.source_hash FROM ci_passages p JOIN ci_files f ON f.id=p.file_id JOIN ci_retrieval_files r ON r.file_id=p.file_id ".to_string();
    if let Some(ids) = ids {
        sql += &format!("WHERE p.id IN ({}) ", placeholders(ids.len()));
    }
    sql += "ORDER BY p.file_id,p.line_start,p.id";
    struct Row {
        id: i64,
        file: i64,
        symbol: Option<i64>,
        start: i64,
        end: i64,
        fields: String,
        role: String,
        split: Option<String>,
        implementation: Option<i64>,
        path: String,
        language: Option<String>,
        hash: String,
    }
    let mut query = conn.prepare(&sql)?;
    let rows = query
        .query_map(params_from_iter(ids.unwrap_or(&[]).iter()), |r| {
            Ok(Row {
                id: r.get(0)?,
                file: r.get(1)?,
                symbol: r.get(2)?,
                start: r.get(3)?,
                end: r.get(4)?,
                fields: r.get(5)?,
                role: r.get(6)?,
                split: r.get(7)?,
                implementation: r.get(8)?,
                path: r.get(9)?,
                language: r.get(10)?,
                hash: r.get(11)?,
            })
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if rows.is_empty() {
        return Ok(vec![]);
    }
    let files: BTreeSet<_> = rows.iter().map(|r| r.file).collect();
    let mut symbols = HashMap::new();
    let mut ordinals = HashMap::new();
    let mut query=conn.prepare(&format!("SELECT s.id,s.file_id,s.kind,s.qualname,s.name,s.line_start,s.line_end,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.file_id IN ({}) ORDER BY s.file_id,s.line_start,s.id",placeholders(files.len())))?;
    let symbols_rows = query.query_map(params_from_iter(files.iter()), |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, i64>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, Option<String>>(3)?,
            r.get::<_, String>(4)?,
            r.get::<_, i64>(5)?,
            r.get::<_, i64>(6)?,
            r.get::<_, String>(7)?,
        ))
    })?;
    for row in symbols_rows {
        let (id, file, kind, qualname, name, start, end, path) = row?;
        if !files.contains(&file) {
            continue;
        }
        let ordinal = ordinals
            .entry((path.clone(), kind.clone(), qualname.clone()))
            .or_insert(0);
        let name = qualname.filter(|s| !s.is_empty()).unwrap_or(name);
        let owner = name.rsplit_once('.').map(|(s, _)| s.into());
        let entity = EntityKey {
            path,
            kind,
            qualname: Some(name),
            owner,
            definition_ordinal: *ordinal,
        };
        *ordinal += 1;
        symbols.insert(id, (entity, Span::new(positive(start)?, positive(end)?)?));
    }
    let mut out = Vec::new();
    for row in rows {
        let span = Span::new(positive(row.start)?, positive(row.end)?)?;
        let (entity, extent) = row
            .symbol
            .and_then(|id| symbols.get(&id))
            .cloned()
            .unwrap_or((
                EntityKey {
                    path: row.path,
                    kind: "module".into(),
                    qualname: None,
                    owner: None,
                    definition_ordinal: 0,
                },
                span,
            ));
        let fields: PassageFields = serde_json::from_str(&row.fields)?;
        out.push((
            row.id,
            Passage {
                entity,
                span,
                fields,
                source_hash: row.hash,
                entity_span: extent,
                language: row
                    .language
                    .filter(|s| !s.is_empty())
                    .unwrap_or_else(|| "text".into()),
                role: row.role,
                split_reason: row.split,
                signals: BTreeMap::new(),
                implementation_start_line: row.implementation.map(positive).transpose()?,
            },
        ));
    }
    Ok(out)
}
