use crate::{Result, records, wire};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use std::path::Path;
const KINDS: [&str; 4] = [
    "finding",
    "persistent_rule",
    "experimental_finding",
    "hypothesis",
];
pub fn ensure_schema(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);CREATE TABLE IF NOT EXISTS cr_findings(id INTEGER PRIMARY KEY AUTOINCREMENT,topic TEXT NOT NULL,content TEXT NOT NULL,tags TEXT NOT NULL DEFAULT '[]',embedding BLOB,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS idx_cr_findings_topic ON cr_findings(topic);CREATE UNIQUE INDEX IF NOT EXISTS uniq_cr_findings_topic ON cr_findings(topic);")?;
    super::graph_tables(db)?;
    records::ensure_schema(db)
}
/// The native model service supplies the document embedding; None preserves the
/// Python fallback where embedding failure must not lose the user's conclusion.
#[allow(clippy::too_many_arguments)]
pub fn remember(
    db: &Connection,
    input: &Value,
    embedding: Option<&[f32]>,
    now: i64,
    root: Option<&Path>,
    checks: &[records::CheckObservation],
    math: &dyn super::VectorMath,
) -> Result<Value> {
    let mut encode = |_: &str, _: &str| embedding.map(<[f32]>::to_vec);
    remember_with_embedding(db, input, &mut encode, now, root, checks, math)
}
/// Admit the entire finding/justification before optional model work starts.
/// The callback shares the existing persistence pipeline and is invoked once.
#[allow(clippy::too_many_arguments)]
pub fn remember_with_embedding(
    db: &Connection,
    input: &Value,
    encode: &mut dyn FnMut(&str, &str) -> Option<Vec<f32>>,
    now: i64,
    root: Option<&Path>,
    checks: &[records::CheckObservation],
    math: &dyn super::VectorMath,
) -> Result<Value> {
    let topic = input["topic"].as_str().unwrap_or("").trim();
    let content = input["content"].as_str().unwrap_or("").trim();
    if topic.is_empty() || content.is_empty() {
        return Ok(json!({"ok":false,"error":"topic and content must be non-empty"}));
    }
    let inferred = records::project_root(db);
    let root = root.or(inferred.as_deref());
    let prepared = match input.get("justification").filter(|j| !j.is_null()) {
        Some(data) => match records::prepare(data, root, checks) {
            Ok(v) => Some(v),
            Err(e) => return Ok(json!({"ok":false,"error":e.to_string()})),
        },
        None => None,
    };
    let mut tags = input["tags"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect::<Vec<_>>();
    if let Some(kind) = input.get("kind").filter(|v| !v.is_null()) {
        let kind = kind.as_str().unwrap_or("").trim();
        if !KINDS.contains(&kind) {
            return Ok(
                json!({"ok":false,"error":"kind must be one of: experimental_finding, finding, hypothesis, persistent_rule"}),
            );
        }
        tags.retain(|t| !t.starts_with("kind:") && !t.starts_with("type:"));
        tags.push(format!("kind:{kind}"));
    }
    let embedding = encode(topic, content);
    let blob = embedding.as_deref().map(|values| {
        values
            .iter()
            .flat_map(|v| v.to_le_bytes())
            .collect::<Vec<_>>()
    });
    let enabled = super::ensure_graph(db, now, math).is_ok() && super::enabled(db);
    records::ensure_schema(db)?;
    let result = wire::transaction(db, || {
        db.execute("INSERT INTO cr_findings(topic,content,tags,embedding,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(topic) DO UPDATE SET content=excluded.content,tags=excluded.tags,embedding=excluded.embedding,updated_at=excluded.updated_at",params![topic,content,serde_json::to_string(&tags)?,blob,now,now])?;
        let id = db.query_row("SELECT id FROM cr_findings WHERE topic=?", [topic], |r| {
            r.get::<_, i64>(0)
        })?;
        records::save(db, id, prepared.as_ref())?;
        if enabled {
            super::guarded(db, || {
                super::graph::recompute_refs(db, id, &format!("{topic}\n{content}"), now)?;
                super::recompute_edges(db, now, math)
            });
        }
        let anchors = input
            .get("anchors")
            .filter(|a| a.as_object().is_some_and(|m| !m.is_empty()));
        let stored = anchors.map(|a| super::set_anchors(db, id, a, now).unwrap_or(0));
        let mut out = json!({"ok":true,"topic":topic});
        if let Some(count) = stored {
            out["anchors"] = json!(count);
        }
        Ok(out)
    });
    match result {
        Ok(out) => Ok(out),
        Err(e) => Ok(json!({"ok":false,"error":format!("remember failed: {e}")})),
    }
}
pub fn forget(
    db: &Connection,
    topic: &str,
    now: i64,
    math: &dyn super::VectorMath,
) -> Result<Value> {
    let topic = topic.trim();
    if topic.is_empty() {
        return Ok(json!({"ok":false,"error":"topic must be non-empty"}));
    }
    let enabled = super::ensure_graph(db, now, math).is_ok() && super::enabled(db);
    match wire::transaction(db, || {
        let deleted = db.execute("DELETE FROM cr_findings WHERE topic=?", [topic])?;
        if enabled && deleted > 0 {
            super::guarded(db, || super::recompute_edges(db, now, math));
        }
        Ok(json!({"ok":deleted>0,"topic":topic,"deleted":deleted}))
    }) {
        Ok(out) => Ok(out),
        Err(e) => Ok(json!({"ok":false,"error":format!("forget failed: {e}")})),
    }
}
pub fn classify_tags(tags: &[String]) -> (&'static str, &'static str) {
    let normalized = tags
        .iter()
        .map(|t| t.trim().to_lowercase())
        .collect::<Vec<_>>();
    for prefix in ["kind:", "type:"] {
        for tag in &normalized {
            if let Some(k) = tag.strip_prefix(prefix)
                && let Some(found) = KINDS.iter().find(|t| **t == k)
            {
                return (found, "explicit");
            }
        }
    }
    if normalized.iter().any(|t| t == "ken-rule") {
        ("persistent_rule", "legacy_tag")
    } else if normalized
        .iter()
        .any(|t| t == "negative-result" || t == "bugfix")
    {
        ("experimental_finding", "legacy_tag")
    } else if normalized
        .iter()
        .any(|t| t == "hypothesis" || t == "research")
    {
        ("hypothesis", "legacy_tag")
    } else {
        ("finding", "default")
    }
}
fn iso(ms: i64) -> String {
    let days = ms.div_euclid(86400000);
    let secs = ms.rem_euclid(86400000) / 1000;
    let millis = ms.rem_euclid(1000);
    let z = days + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let mut y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    if month <= 2 {
        y += 1;
    }
    let base = format!(
        "{y:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}",
        secs / 3600,
        (secs % 3600) / 60,
        secs % 60
    );
    if millis == 0 {
        format!("{base}Z")
    } else {
        format!("{base}.{millis:03}000Z")
    }
}
fn row_value(
    topic: String,
    content: String,
    tags_raw: String,
    created: i64,
    updated: i64,
) -> Result<Value> {
    let tags: Vec<String> = serde_json::from_str(&tags_raw)?;
    let (kind, source) = classify_tags(&tags);
    Ok(
        json!({"topic":topic,"content":content,"tags":tags,"type":kind,"type_source":source,"created_at":iso(created),"updated_at":iso(updated)}),
    )
}
pub fn list(
    db: &Connection,
    limit: usize,
    tag: Option<&str>,
    root: Option<&Path>,
    checks: &[records::CheckObservation],
) -> Result<Vec<Value>> {
    let mut stmt=db.prepare("SELECT topic,content,tags,created_at,updated_at FROM cr_findings ORDER BY updated_at DESC,topic LIMIT ?")?;
    let rows = stmt.query_map([limit.max(1) as i64], |r| {
        Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?))
    })?;
    let wanted = tag.map(str::trim).filter(|t| !t.is_empty());
    let mut hits = Vec::new();
    for row in rows {
        let (topic, content, tags, created, updated) = row?;
        let hit = row_value(topic, content, tags, created, updated)?;
        if wanted.is_some_and(|t| !hit["tags"].as_array().unwrap().iter().any(|tag| tag == t)) {
            continue;
        }
        hits.push(hit);
    }
    records::enrich(db, &hits, root, checks)
}
pub(super) fn decode(blob: &[u8]) -> Option<Vec<f32>> {
    if !blob.len().is_multiple_of(4) {
        return None;
    }
    Some(
        blob.chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
            .collect(),
    )
}

pub fn recall(
    db: &Connection,
    query: &[f32],
    limit: usize,
    min_score: Option<f64>,
    root: Option<&Path>,
    checks: &[records::CheckObservation],
    math: &dyn super::VectorMath,
) -> Result<Vec<Value>> {
    let min_score = min_score.unwrap_or(0.0).max(0.0);
    let mut stmt=db.prepare("SELECT topic,content,tags,embedding,created_at,updated_at FROM cr_findings WHERE embedding IS NOT NULL")?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, Vec<u8>>(3)?,
            r.get::<_, i64>(4)?,
            r.get::<_, i64>(5)?,
        ))
    })?;
    let mut stored_dims = std::collections::BTreeSet::new();
    let mut kept = Vec::new();
    let mut matrix = Vec::new();
    let mut norms = Vec::new();
    for row in rows {
        let (topic, content, tags, blob, created, updated) = row?;
        let vector = decode(&blob)
            .ok_or_else(|| crate::invalid("buffer size must be a multiple of element size"))?;
        stored_dims.insert(vector.len());
        if vector.len() != query.len() {
            continue;
        }
        norms.push(math.row_norm(&vector)? + 1e-12f32);
        matrix.extend(vector);
        kept.push((topic, content, tags, created, updated));
    }
    if kept.is_empty() {
        if !stored_dims.is_empty() {
            return Err(crate::invalid(format!(
                "stored embeddings are {:?}-dimensional but the live embedder produces {} — the index was built with a different model; run `ken reembed`",
                stored_dims.into_iter().collect::<Vec<_>>(),
                query.len()
            )));
        }
        return Ok(Vec::new());
    }
    let norm = math.query_norm(query)? + 1e-12f32;
    let query = query.iter().map(|x| x / norm).collect::<Vec<_>>();
    let scores = math.scores(&matrix, kept.len(), &query)?;
    if scores.len() != kept.len() {
        return Err(crate::invalid(
            "numerical strategy returned incompatible scores",
        ));
    }
    let mut ranked = Vec::new();
    for ((topic, content, tags, created, updated), (score, norm)) in
        kept.into_iter().zip(scores.into_iter().zip(norms))
    {
        let score = (score / norm) as f64;
        if score >= min_score {
            let mut value = row_value(topic, content, tags, created, updated)?;
            value["score"] = json!(wire::round(score, 3));
            value["score_kind"] = json!("cosine_similarity");
            value["min_score"] = json!(min_score);
            ranked.push((score, value));
        }
    }
    ranked.sort_by(|a, b| b.0.total_cmp(&a.0));
    let hits = ranked
        .into_iter()
        .take(limit.max(1))
        .map(|(_, h)| h)
        .collect::<Vec<_>>();
    records::enrich(db, &hits, root, checks)
}
pub fn format_recall_hits(hits: &[Value]) -> String {
    let mut lines = Vec::new();
    for hit in hits {
        let tags = hit["tags"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>();
        let suffix = if tags.is_empty() {
            String::new()
        } else {
            format!(" [{}]", tags.join(" "))
        };
        let mut meta = Vec::new();
        if let Some(kind) = hit["type"].as_str().filter(|s| !s.is_empty()) {
            meta.push(kind.to_owned());
        }
        if let Some(updated) = hit["updated_at"].as_str().filter(|s| !s.is_empty()) {
            meta.push(format!("updated {updated}"));
        }
        if let Some(state) = hit["validity"]["state"].as_str() {
            meta.push(format!("dependencies: {state}"));
        }
        let meta = if meta.is_empty() {
            String::new()
        } else {
            format!(" ({})", meta.join("; "))
        };
        lines.push(format!(
            "{:.3}  {}{suffix}{meta}",
            hit["score"].as_f64().unwrap_or(0.0),
            hit["topic"].as_str().unwrap_or("")
        ));
        lines.push(format!("       {}", hit["content"].as_str().unwrap_or("")));
    }
    lines.join("\n")
}
pub(super) fn exact_topic(db: &Connection, topic: &str) -> Result<Option<(i64, String)>> {
    Ok(db
        .query_row(
            "SELECT id,topic FROM cr_findings WHERE topic=?",
            [topic],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?)
}
