use crate::{Result, context, invalid, wire};
use regex::Regex;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    sync::LazyLock,
};
static PATH_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b[\w./\-]+\.[A-Za-z][A-Za-z0-9]{0,7}\b(?::\d+(?:-\d+)?)?").unwrap()
});
static IDENT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"`([^`\n]+)`|\b([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\b").unwrap()
});
static SNAKE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b").unwrap());
const SOURCE_EXTS: &str = "py pyi js jsx ts tsx mjs cjs go rs java rb php kt kts dart cs cpp cc cxx c h hpp swift scala m mm sh sql html css ps1 psm1 psd1 graphql gql gemspec rake vue svelte lua ex exs erl gradle";
const SYMBOL_STOP: &str = "run main connect close setup init __init__ __main__ execute get set load save open read write start stop call send post handle build";
const IDENT_STOP: &str = "the this that these those when where which while with from into note todo then than here there true false none null and for";
fn escape_like(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('%', "\\%")
        .replace('_', "\\_")
}
fn keep(token: &str) -> bool {
    let len = token.chars().count();
    let low = token.to_lowercase();
    (4..=80).contains(&len)
        && !SYMBOL_STOP.split_whitespace().any(|s| s == low)
        && !IDENT_STOP.split_whitespace().any(|s| s == low)
}
fn tokens(text: &str) -> Vec<(String, &'static str)> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for cap in IDENT_RE.captures_iter(text) {
        let raw = cap
            .get(1)
            .or_else(|| cap.get(2))
            .unwrap()
            .as_str()
            .trim()
            .trim_end_matches(['(', ')'])
            .trim();
        let mut candidates = vec![raw];
        if raw.contains('.') && !raw.contains(' ') {
            candidates.push(raw.rsplit('.').next().unwrap());
        }
        for token in candidates {
            if keep(token) && seen.insert(token.to_owned()) {
                out.push((token.to_owned(), "ident"));
            }
        }
    }
    for m in SNAKE_RE.find_iter(text) {
        let raw = m.as_str().trim().trim_end_matches(['(', ')']).trim();
        if keep(raw) && seen.insert(raw.to_owned()) {
            out.push((raw.to_owned(), "snake"));
        }
    }
    out
}
pub fn extract_refs(db: &Connection, text: &str) -> Result<Value> {
    let mut out = Vec::new();
    let mut seen = BTreeSet::new();
    for found in PATH_RE.find_iter(text) {
        let base = found.as_str().split(':').next().unwrap();
        let mut stmt =
            db.prepare("SELECT id,path FROM ci_files WHERE path=? OR path LIKE ? ESCAPE '\\'")?;
        let rows = stmt
            .query_map(params![base, format!("%/{}", escape_like(base))], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let exact = rows.iter().filter(|(_, p)| p == base).collect::<Vec<_>>();
        let chosen = if !exact.is_empty() {
            exact
        } else if rows.len() == 1 {
            rows.iter().collect()
        } else {
            Vec::new()
        };
        if !chosen.is_empty() {
            for (id, path) in chosen {
                if seen.insert(("file".to_owned(), path.clone())) {
                    out.push(json!({"ref_kind":"file","ref_key":path,"file_id":id,"symbol_id":null,"method":"path","resolved":1}));
                }
            }
        } else if rows.is_empty()
            && (base.contains('/')
                || SOURCE_EXTS.split_whitespace().any(|ext| {
                    Some(ext) == base.rsplit('.').next().map(|s| s.to_lowercase()).as_deref()
                }))
            && seen.insert(("file".to_owned(), base.to_owned()))
        {
            out.push(json!({"ref_kind":"file","ref_key":base,"file_id":null,"symbol_id":null,"method":"path","resolved":0}));
        }
    }
    for (token, method) in tokens(text) {
        let mut stmt=db.prepare("SELECT s.id,s.qualname,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.qualname=? OR s.name=?")?;
        let rows = stmt
            .query_map(params![token, token], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let exact = rows
            .iter()
            .filter(|(_, q, _)| q.as_deref() == Some(token.as_str()))
            .take(5)
            .collect::<Vec<_>>();
        let chosen = if !exact.is_empty() {
            exact
        } else if rows.len() == 1 && rows[0].1.as_deref().is_some_and(|q| !q.is_empty()) {
            rows.iter().collect()
        } else {
            Vec::new()
        };
        for (id, qual, path) in chosen {
            let Some(qual) = qual.as_ref().filter(|q| !q.is_empty()) else {
                continue;
            };
            let key = format!("{qual}\x1f{path}");
            if seen.insert(("symbol".to_owned(), key.clone())) {
                out.push(json!({"ref_kind":"symbol","ref_key":key,"file_id":null,"symbol_id":id,"method":method,"resolved":1}));
            }
        }
    }
    Ok(json!(out))
}
fn insert_refs(db: &Connection, id: i64, text: &str, now: i64) -> Result<()> {
    for r in extract_refs(db, text)?.as_array().unwrap() {
        db.execute("INSERT OR IGNORE INTO cr_finding_refs(finding_id,ref_kind,ref_key,file_id,symbol_id,method,resolved,updated_at) VALUES(?,?,?,?,?,?,?,?)",params![id,r["ref_kind"].as_str(),r["ref_key"].as_str(),r["file_id"].as_i64(),r["symbol_id"].as_i64(),r["method"].as_str(),r["resolved"].as_i64(),now])?;
    }
    Ok(())
}
pub(super) fn recompute_refs(db: &Connection, id: i64, text: &str, now: i64) -> Result<()> {
    db.execute(
        "DELETE FROM cr_finding_refs WHERE finding_id=? AND method!='anchor'",
        [id],
    )?;
    insert_refs(db, id, text, now)
}
pub fn ensure_graph(db: &Connection, now: i64, math: &dyn super::VectorMath) -> Result<()> {
    super::graph_tables(db)?;
    if !super::enabled(db) || super::meta(db, "findings_graph_version")?.as_deref() == Some("1") {
        return Ok(());
    }
    if db.is_autocommit() {
        wire::transaction(db, || rebuild(db, now, math).map(|_| ()))
    } else {
        rebuild(db, now, math).map(|_| ())
    }
}
pub fn rebuild(db: &Connection, now: i64, math: &dyn super::VectorMath) -> Result<Value> {
    db.execute("DELETE FROM cr_finding_refs", [])?;
    let mut stmt = db.prepare("SELECT id,topic,content FROM cr_findings ORDER BY id")?;
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    drop(stmt);
    for (id, topic, content) in rows {
        insert_refs(db, id, &format!("{topic}\n{content}"), now)?;
    }
    recompute_edges(db, now, math)?;
    super::set_meta(db, "findings_graph_version", "1")?;
    Ok(json!({"ok":true}))
}
struct Edge {
    a: i64,
    b: i64,
    kind: &'static str,
    weight: f64,
    evidence: Value,
}
fn edge(a: i64, b: i64, kind: &'static str, w: f64, evidence: Value) -> Edge {
    Edge {
        a: a.min(b),
        b: a.max(b),
        kind,
        weight: wire::round(w.clamp(0.0, 1.0), 4),
        evidence,
    }
}
fn pairs<T: Copy + Ord>(values: &BTreeSet<T>) -> Vec<(T, T)> {
    let values = values.iter().copied().collect::<Vec<_>>();
    let mut out = Vec::new();
    for (i, a) in values.iter().enumerate() {
        for b in &values[i + 1..] {
            out.push((*a, *b));
        }
    }
    out
}
fn shared_refs(db: &Connection, kind: &str, edge_type: &'static str) -> Result<Vec<Edge>> {
    let mut keys = BTreeMap::<String, BTreeSet<i64>>::new();
    let mut stmt = db.prepare(
        "SELECT finding_id,ref_key FROM cr_finding_refs WHERE ref_kind=? AND resolved=1",
    )?;
    let rows = stmt.query_map([kind], |r| {
        Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
    })?;
    for row in rows {
        let (id, key) = row?;
        keys.entry(key).or_default().insert(id);
    }
    let n = keys
        .values()
        .flatten()
        .copied()
        .collect::<BTreeSet<_>>()
        .len();
    if n < 2 {
        return Ok(Vec::new());
    }
    let idf = n >= 8;
    let mut shared = BTreeMap::<(i64, i64), Vec<(String, f64)>>::new();
    for (key, ids) in keys {
        let df = ids.len();
        if df < 2 || (idf && (df as f64) / (n as f64) > 0.5) {
            continue;
        }
        let weight = ((n as f64 + 1.0) / (df as f64 + 0.5)).ln();
        for pair in pairs(&ids) {
            shared.entry(pair).or_default().push((key.clone(), weight));
        }
    }
    Ok(shared.into_iter().map(|((a,b),mut keys)|{keys.sort_by(|a,b|a.0.cmp(&b.0));let weight=if idf{1.0-0.5f64.powf(keys.iter().map(|(_,w)|w).sum())}else{1.0-0.5f64.powi(keys.len() as i32)};edge(a,b,edge_type,weight,json!({"keys":keys.iter().take(8).map(|(key,_)|key).collect::<Vec<_>>(),"n":keys.len()}))}).collect())
}
fn surviving_tags(raw: &str) -> BTreeSet<String> {
    serde_json::from_str::<Value>(raw)
        .ok()
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .iter()
        .filter_map(Value::as_str)
        .map(|s| s.trim().to_lowercase())
        .filter(|s| {
            !s.is_empty()
                && !s.starts_with("kind:")
                && !s.starts_with("type:")
                && !["bug", "todo", "wip", "fixme", "note", "hack"].contains(&s.as_str())
        })
        .collect()
}
fn shared_tags(db: &Connection) -> Result<Vec<Edge>> {
    let mut tags = BTreeMap::new();
    let mut stmt = db.prepare("SELECT id,tags FROM cr_findings ORDER BY id")?;
    let rows = stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?;
    for row in rows {
        let (id, raw) = row?;
        let values = surviving_tags(&raw);
        if !values.is_empty() {
            tags.insert(id, values);
        }
    }
    let n = tags.len();
    if n < 2 {
        return Ok(Vec::new());
    }
    let mut keys = BTreeMap::<String, BTreeSet<i64>>::new();
    for (id, values) in &tags {
        for value in values {
            keys.entry(value.clone()).or_default().insert(*id);
        }
    }
    if n >= 8 {
        let hubs = keys
            .iter()
            .filter(|(_, ids)| ids.len() as f64 / n as f64 > 0.5)
            .map(|(key, _)| key.clone())
            .collect::<BTreeSet<_>>();
        for values in tags.values_mut() {
            values.retain(|v| !hubs.contains(v));
        }
        keys.retain(|key, _| !hubs.contains(key));
    }
    let mut shared = BTreeMap::<(i64, i64), BTreeSet<String>>::new();
    for (key, ids) in keys {
        for pair in pairs(&ids) {
            shared.entry(pair).or_default().insert(key.clone());
        }
    }
    Ok(shared
        .into_iter()
        .map(|((a, b), values)| {
            let union = tags[&a].union(&tags[&b]).count();
            edge(
                a,
                b,
                "shared_tag",
                if union == 0 {
                    0.0
                } else {
                    values.len() as f64 / union as f64
                },
                json!({"tags":values.into_iter().take(8).collect::<Vec<_>>()}),
            )
        })
        .collect())
}
fn semantic(db: &Connection, math: &dyn super::VectorMath) -> Result<Vec<Edge>> {
    let mut stmt =
        db.prepare("SELECT id,embedding FROM cr_findings WHERE embedding IS NOT NULL ORDER BY id")?;
    let rows = stmt
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, Vec<u8>>(1)?)))?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if rows.len() < 2 {
        return Ok(Vec::new());
    }
    if rows.len() > 2000 {
        super::set_meta(
            db,
            "findings_graph_note",
            &format!("semantic skipped: N={}>cap", rows.len()),
        )?;
        return Ok(Vec::new());
    }
    super::set_meta(db, "findings_graph_note", "")?;
    let mut vectors = Vec::new();
    let mut counts = Vec::<(usize, usize)>::new();
    for (id, blob) in rows {
        let v = super::store::decode(&blob).ok_or_else(|| invalid("invalid finding embedding"))?;
        let dim = v.len();
        if let Some((_, count)) = counts.iter_mut().find(|(d, _)| *d == dim) {
            *count += 1;
        } else {
            counts.push((dim, 1));
        }
        vectors.push((id, v));
    }
    let mut dim = 0;
    let mut largest = 0;
    for (d, n) in counts {
        if n > largest {
            dim = d;
            largest = n;
        }
    }
    vectors.retain(|(_, v)| v.len() == dim);
    if vectors.len() < 2 {
        return Ok(Vec::new());
    }
    for (_, v) in &mut vectors {
        let norm = math.row_norm(v)? + 1e-12f32;
        for x in v {
            *x /= norm;
        }
    }
    let matrix = vectors
        .iter()
        .flat_map(|(_, v)| v.iter().copied())
        .collect::<Vec<_>>();
    let similarities = math.symmetric_product(&matrix, vectors.len(), dim)?;
    if similarities.len() != vectors.len() * vectors.len() {
        return Err(invalid(
            "numerical strategy returned incompatible similarities",
        ));
    }
    let mut out = Vec::new();
    for i in 0..vectors.len() {
        for j in i + 1..vectors.len() {
            let c = similarities[i * vectors.len() + j] as f64;
            if c < 0.6 || !c.is_finite() {
                continue;
            }
            out.push(edge(
                vectors[i].0,
                vectors[j].0,
                "semantic",
                (c - 0.6) / 0.4,
                json!({"cosine":wire::round(c,3)}),
            ));
        }
    }
    Ok(out)
}
pub fn recompute_edges(db: &Connection, now: i64, math: &dyn super::VectorMath) -> Result<()> {
    db.execute("DELETE FROM cr_finding_edges", [])?;
    let mut edges = semantic(db, math)?;
    edges.extend(shared_refs(db, "file", "shared_file")?);
    edges.extend(shared_refs(db, "symbol", "shared_symbol")?);
    edges.extend(shared_tags(db)?);
    edges.sort_by(|a, b| (a.a, a.b, a.kind).cmp(&(b.a, b.b, b.kind)));
    for e in edges {
        db.execute("INSERT OR REPLACE INTO cr_finding_edges(src,dst,edge_type,directed,weight,evidence,updated_at) VALUES(?,?,?,0,?,?,?)",params![e.a,e.b,e.kind,e.weight,wire::json(&e.evidence),now])?;
    }
    Ok(())
}
fn topic(db: &Connection, id: i64) -> String {
    db.query_row("SELECT topic FROM cr_findings WHERE id=?", [id], |r| {
        r.get(0)
    })
    .unwrap_or_else(|_| format!("#{id}"))
}
/// A missing exact topic may be resolved by an already-computed query vector.
/// Passing None cannot silently trigger model loading or fabricate a match.
pub fn related(
    db: &Connection,
    requested: &str,
    limit: usize,
    min_weight: f64,
    query: Option<&[f32]>,
    math: &dyn super::VectorMath,
) -> Result<Value> {
    let requested = requested.trim();
    let mut resolved = super::store::exact_topic(db, requested)?;
    if resolved.is_none()
        && let Some(query) = query
        && let Some(hit) = super::recall(db, query, 1, Some(0.25), None, &[], math)?.first()
    {
        resolved = super::store::exact_topic(db, hit["topic"].as_str().unwrap_or(""))?;
    }
    let Some((id, resolved)) = resolved else {
        return Ok(
            json!({"ok":true,"topic":requested,"neighbors":[],"note":if requested.is_empty(){"empty topic"}else{"no matching finding"}}),
        );
    };
    let mut by_neighbor = BTreeMap::<i64, Vec<Value>>::new();
    let mut stmt = db.prepare(
        "SELECT src,dst,edge_type,weight,evidence FROM cr_finding_edges WHERE src=? OR dst=?",
    )?;
    let rows = stmt.query_map(params![id, id], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, i64>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, f64>(3)?,
            r.get::<_, String>(4)?,
        ))
    })?;
    for row in rows {
        let (a, b, kind, w, evidence) = row?;
        if w < min_weight {
            continue;
        }
        let evidence = serde_json::from_str::<Value>(&evidence)
            .ok()
            .filter(Value::is_object)
            .unwrap_or(json!({}));
        by_neighbor
            .entry(if a == id { b } else { a })
            .or_default()
            .push(json!({"type":kind,"weight":wire::round(w,3),"evidence":evidence}));
    }
    if by_neighbor.is_empty() {
        return Ok(
            json!({"ok":true,"topic":resolved,"neighbors":[],"note":"no related findings above min_weight"}),
        );
    }
    let mut neighbors = Vec::new();
    for (id, mut edges) in by_neighbor {
        edges.sort_by(|a, b| {
            let exact_a = a["type"] != "semantic";
            let exact_b = b["type"] != "semantic";
            exact_b.cmp(&exact_a).then_with(|| {
                b["weight"]
                    .as_f64()
                    .unwrap()
                    .total_cmp(&a["weight"].as_f64().unwrap())
            })
        });
        let best = edges
            .iter()
            .map(|e| e["weight"].as_f64().unwrap())
            .fold(0f64, f64::max);
        let exact = edges.iter().any(|e| e["type"] != "semantic");
        neighbors.push(
            json!({"topic":topic(db,id),"has_exact_link":exact,"best_weight":best,"edges":edges}),
        );
    }
    neighbors.sort_by(|a, b| {
        b["has_exact_link"]
            .as_bool()
            .cmp(&a["has_exact_link"].as_bool())
            .then_with(|| {
                b["best_weight"]
                    .as_f64()
                    .unwrap()
                    .total_cmp(&a["best_weight"].as_f64().unwrap())
            })
            .then_with(|| a["topic"].as_str().cmp(&b["topic"].as_str()))
    });
    neighbors.truncate(limit);
    Ok(
        json!({"ok":true,"topic":resolved,"edge_coverage":"shared_file/shared_symbol/shared_tag are exact; semantic is approximate","neighbors":neighbors}),
    )
}
pub fn for_file(
    db: &Connection,
    path: &str,
    expand: bool,
    limit: usize,
    root: Option<&Path>,
) -> Result<Value> {
    let mut target = path.replace('\\', "/");
    if let Some(root) = root
        && let Ok(relative) = Path::new(&target).strip_prefix(root)
    {
        target = relative.to_string_lossy().replace('\\', "/");
    }
    while target.starts_with("./") {
        target = target[2..].to_owned();
    }
    let mut stmt=db.prepare("SELECT DISTINCT f.id,f.topic,f.content,f.updated_at FROM cr_finding_refs r JOIN cr_findings f ON f.id=r.finding_id WHERE r.resolved=1 AND ((r.ref_kind='file' AND r.ref_key=?) OR (r.ref_kind='symbol' AND substr(r.ref_key,instr(r.ref_key,char(31))+1)=?)) ORDER BY f.updated_at DESC")?;
    let rows = stmt
        .query_map(params![target, target], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let direct = rows
        .iter()
        .take(limit)
        .map(|(_, topic, content)| {
            let preview = context::clip(content, 200);
            json!({"topic":topic,"content":preview})
        })
        .collect::<Vec<_>>();
    let mut result = json!({"ok":true,"path":target,"findings":direct});
    if direct.is_empty() {
        result["note"] = json!("no findings reference this file");
        return Ok(result);
    }
    if expand {
        let ids = rows.iter().map(|(id, _, _)| *id).collect::<BTreeSet<_>>();
        let mut found = BTreeMap::<i64, f64>::new();
        let mut stmt =
            db.prepare("SELECT src,dst,weight FROM cr_finding_edges WHERE weight>=0.4")?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, f64>(2)?,
            ))
        })?;
        for row in rows {
            let (a, b, w) = row?;
            if !ids.contains(&a) && !ids.contains(&b) {
                continue;
            }
            for endpoint in [a, b] {
                if !ids.contains(&endpoint) {
                    let weight = wire::round(w, 3);
                    found
                        .entry(endpoint)
                        .and_modify(|v| *v = v.max(weight))
                        .or_insert(weight);
                }
            }
        }
        let mut expanded = found
            .into_iter()
            .map(|(id, w)| json!({"topic":topic(db,id),"weight":w}))
            .collect::<Vec<_>>();
        expanded.sort_by(|a, b| {
            b["weight"]
                .as_f64()
                .unwrap()
                .total_cmp(&a["weight"].as_f64().unwrap())
                .then_with(|| a["topic"].as_str().cmp(&b["topic"].as_str()))
        });
        expanded.truncate(limit.max(1));
        result["related"] = json!(expanded);
    }
    Ok(result)
}
