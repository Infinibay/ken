//! Legacy row identity, literal fusion and output shapes; arithmetic is shared.
use super::CompatibilityModels;
use ken_retrieval::{
    Result, RetrievalError,
    vector_math::{NativeVectorMath, QueryNorm},
    vector_store::live_store_scores,
};
use ken_store::{VectorSpace, VectorStore};
use ken_text::PythonText;
use rusqlite::{Connection, Row, params_from_iter};
use serde::Serialize;
use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, Serialize)]
pub struct OutlineSymbol {
    pub kind: String,
    pub name: String,
    pub line: i64,
}
#[derive(Clone, Debug, Serialize)]
pub struct LegacyFileHit {
    pub path: String,
    pub language: String,
    pub score: f64,
    #[serde(rename = "match", skip_serializing_if = "Option::is_none")]
    pub literal_match: Option<&'static str>,
    pub symbols: Vec<OutlineSymbol>,
}
#[derive(Clone, Debug, Serialize)]
pub struct LegacySymbolHit {
    pub qualname: Option<String>,
    pub kind: String,
    pub file: String,
    pub line: i64,
    pub line_end: i64,
    pub docstring: Option<String>,
    pub score: Option<f64>,
    #[serde(rename = "match", skip_serializing_if = "Option::is_none")]
    pub literal_match: Option<&'static str>,
}
#[derive(Clone, Debug, Serialize)]
#[serde(untagged)]
pub enum LegacyResponse {
    Files(Vec<LegacyFileHit>),
    Symbols(Vec<LegacySymbolHit>),
}
impl LegacyResponse {
    pub fn render(&self) -> String {
        let mut lines = Vec::new();
        match self {
            Self::Files(hits) => {
                for hit in hits {
                    lines.push(format!(
                        "{:.3}  {}  ({})",
                        hit.score, hit.path, hit.language
                    ));
                    if !hit.symbols.is_empty() {
                        lines.push(format!(
                            "       {}",
                            hit.symbols
                                .iter()
                                .take(5)
                                .map(|s| format!("{} {}:{}", s.kind, s.name, s.line))
                                .collect::<Vec<_>>()
                                .join(", ")
                        ));
                    }
                }
            }
            Self::Symbols(hits) => {
                for hit in hits {
                    let score = hit
                        .score
                        .map(|v| format!("{v:.3}"))
                        .unwrap_or_else(|| "n/a".into());
                    lines.push(
                        format!(
                            "{score}  {}:{}  {} {}",
                            hit.file,
                            hit.line,
                            hit.kind,
                            hit.qualname.as_deref().unwrap_or("")
                        )
                        .trim_end_matches(ken_text::unicode::whitespace)
                        .to_owned(),
                    );
                    if let Some(doc) = hit
                        .docstring
                        .as_deref()
                        .map(|s| s.trim_matches(ken_text::unicode::whitespace))
                        .filter(|s| !s.is_empty())
                    {
                        lines.push(format!("       {doc}"));
                    }
                }
            }
        }
        lines.join("\n")
    }
}
#[derive(Clone)]
struct FileRow {
    id: i64,
    path: String,
    language: Option<String>,
}
#[derive(Clone)]
struct SymbolRow {
    kind: String,
    name: Option<String>,
    qualname: Option<String>,
    start: i64,
    end: i64,
    docstring: Option<String>,
    path: String,
}
#[derive(Clone)]
enum LegacyRow {
    File(FileRow),
    Symbol(SymbolRow),
}
impl LegacyRow {
    fn path(&self) -> &str {
        match self {
            Self::File(f) => &f.path,
            Self::Symbol(s) => &s.path,
        }
    }
    fn line(&self) -> i64 {
        match self {
            Self::File(_) => 0,
            Self::Symbol(s) => s.start,
        }
    }
    fn names(&self) -> Vec<&str> {
        match self {
            Self::File(f) => {
                let name = Path::new(&f.path)
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("");
                let stem = match name.rfind('.') {
                    Some(i) if i > 0 && i + 1 < name.len() => &name[..i],
                    _ => name,
                };
                vec![stem, name, &f.path]
            }
            Self::Symbol(s) => vec![
                s.name.as_deref().unwrap_or(""),
                s.qualname.as_deref().unwrap_or(""),
            ],
        }
    }
}
struct StoredRow {
    row: LegacyRow,
    blob: Option<Vec<u8>>,
    slot: Option<i64>,
}
struct Scored {
    row: LegacyRow,
    score: f64,
}
fn invalid(message: impl Into<String>) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
fn file_row(row: &Row<'_>) -> rusqlite::Result<StoredRow> {
    Ok(StoredRow {
        row: LegacyRow::File(FileRow {
            id: row.get(0)?,
            path: row.get(1)?,
            language: row.get(2)?,
        }),
        blob: row.get(3)?,
        slot: row.get(4)?,
    })
}
fn symbol_row(row: &Row<'_>) -> rusqlite::Result<StoredRow> {
    Ok(StoredRow {
        row: LegacyRow::Symbol(SymbolRow {
            kind: row.get(0)?,
            name: row.get(1)?,
            qualname: row.get(2)?,
            start: row.get(3)?,
            end: row.get(4)?,
            docstring: row.get(5)?,
            path: row.get(6)?,
        }),
        blob: row.get(7)?,
        slot: row.get(8)?,
    })
}
fn selected_rows(conn: &Connection, scope: &str, slots: Option<&[i64]>) -> Result<Vec<StoredRow>> {
    let suffix = match slots {
        Some(values) => format!(
            " IN ({})",
            std::iter::repeat_n("?", values.len())
                .collect::<Vec<_>>()
                .join(",")
        ),
        None => " IS NOT NULL".into(),
    };
    let (sql, reader): (String, fn(&Row<'_>) -> rusqlite::Result<StoredRow>) = if scope == "files" {
        (
            format!(
                "SELECT id,path,language,embedding,vec_slot FROM ci_files WHERE {}{suffix}",
                if slots.is_some() {
                    "vec_slot"
                } else {
                    "embedding"
                }
            ),
            file_row,
        )
    } else {
        (
            format!(
                "SELECT s.kind,s.name,s.qualname,s.line_start,s.line_end,s.docstring,f.path,s.embedding,s.vec_slot FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.{}{suffix}",
                if slots.is_some() {
                    "vec_slot"
                } else {
                    "embedding"
                }
            ),
            symbol_row,
        )
    };
    let mut statement = conn.prepare(&sql)?;
    Ok(statement
        .query_map(params_from_iter(slots.unwrap_or(&[])), reader)?
        .collect::<rusqlite::Result<_>>()?)
}
/// Store location comes from the connection. Optional caller root only filters paths.
fn database_root(conn: &Connection) -> Option<PathBuf> {
    let mut statement = conn.prepare("PRAGMA database_list").ok()?;
    let rows = statement
        .query_map([], |r| Ok((r.get::<_, String>(1)?, r.get::<_, String>(2)?)))
        .ok()?;
    for row in rows {
        let (name, path) = row.ok()?;
        if name == "main" && !path.is_empty() {
            let path = Path::new(&path);
            let directory = path.parent()?;
            return if directory.file_name().is_some_and(|s| s == ".ken") {
                directory.parent().map(Path::to_owned)
            } else {
                Some(directory.into())
            };
        }
    }
    None
}
fn live(row: &LegacyRow, root: Option<&Path>) -> bool {
    root.is_none_or(|root| root.join(row.path()).exists())
}
fn finite_vector(bytes: &[u8]) -> Result<()> {
    if !bytes.len().is_multiple_of(4) {
        return Err(invalid(
            "embedding buffer size must be a multiple of float32 size",
        ));
    }
    if bytes
        .chunks_exact(4)
        .any(|b| !f32::from_le_bytes(b.try_into().expect("float32 chunk")).is_finite())
    {
        return Err(invalid("legacy search requires finite embedding vectors"));
    }
    Ok(())
}
fn finite_scores(scores: &[f32]) -> Result<()> {
    if scores.iter().any(|v| !v.is_finite()) {
        return Err(invalid("legacy search requires finite cosine scores"));
    }
    Ok(())
}
fn scored_rows(
    conn: &Connection,
    scope: &str,
    root: Option<&Path>,
    store_root: Option<&Path>,
    query: &[f32],
    math: &NativeVectorMath,
) -> Result<Vec<Scored>> {
    let space = if scope == "files" {
        VectorSpace::Files
    } else {
        VectorSpace::Symbols
    };
    if let Some(found) = live_store_scores(conn, store_root, space, query, math)? {
        finite_scores(&found.scores)?;
        let count = found.scores.len();
        if count == 0 {
            return Ok(Vec::new());
        }
        let k = count.min(512);
        let partition = math.argpartition_f32(&found.scores, count - k)?;
        let selected = &partition[count - k..];
        // The original sorts ascending then reverses, including its tie order.
        // The shared primitive argsorts negative keys; double-negation recovers
        // ascending ordering without replacing it with a stable Rust sort.
        let negative = selected
            .iter()
            .map(|&i| -found.scores[i])
            .collect::<Vec<_>>();
        let mut order = math.argsort_descending_f32(&negative)?;
        order.reverse();
        let top = order.into_iter().map(|i| selected[i]).collect::<Vec<_>>();
        let slots = top.iter().map(|&i| found.slots[i]).collect::<Vec<_>>();
        let mut by_slot = BTreeMap::new();
        for chunk in slots.chunks(500) {
            for stored in selected_rows(conn, scope, Some(chunk))? {
                if let Some(slot) = stored.slot {
                    by_slot.insert(slot, stored.row);
                }
            }
        }
        return Ok(top
            .into_iter()
            .filter_map(|index| {
                let row = by_slot.get(&found.slots[index])?;
                live(row, root).then(|| Scored {
                    row: row.clone(),
                    score: f64::from(found.scores[index]),
                })
            })
            .collect());
    }
    let rows = selected_rows(conn, scope, None)?
        .into_iter()
        .filter(|r| live(&r.row, root))
        .collect::<Vec<_>>();
    for row in &rows {
        if let Some(blob) = &row.blob {
            finite_vector(blob)?;
        }
    }
    let blobs = rows.iter().map(|r| r.blob.as_deref()).collect::<Vec<_>>();
    let scores = math.rank_against(query, &blobs, true)?;
    finite_scores(&scores.scores)?;
    let mut output = scores
        .kept
        .into_iter()
        .zip(scores.scores)
        .map(|(i, score)| Scored {
            row: rows[i].row.clone(),
            score: f64::from(score),
        })
        .collect::<Vec<_>>();
    output.sort_by(|a, b| b.score.partial_cmp(&a.score).expect("finite legacy scores"));
    Ok(output)
}
fn identifier(query: &PythonText) -> Option<String> {
    let query = query.clone().trimmed().to_utf8()?;
    let mut chars = query.chars();
    if !chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        || !chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.'))
    {
        return None;
    }
    Some(query)
}
fn include_exact(
    conn: &Connection,
    mut scored: Vec<Scored>,
    ident: Option<&str>,
    root: Option<&Path>,
    store_root: Option<&Path>,
    query: &[f32],
    math: &NativeVectorMath,
) -> Result<Vec<Scored>> {
    let Some(ident) = ident else {
        return Ok(scored);
    };
    let mut statement=conn.prepare("SELECT s.kind,s.name,s.qualname,s.line_start,s.line_end,s.docstring,f.path,s.embedding,s.vec_slot FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.name=?1 COLLATE NOCASE OR s.qualname=?1 COLLATE NOCASE ORDER BY f.path,s.line_start")?;
    let rows = statement
        .query_map([ident], symbol_row)?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let known: HashSet<_> = scored
        .iter()
        .filter_map(|r| match &r.row {
            LegacyRow::Symbol(s) => Some((s.path.clone(), s.start, s.qualname.clone())),
            _ => None,
        })
        .collect();
    let mut store = None;
    for row in rows {
        let LegacyRow::Symbol(symbol) = &row.row else {
            unreachable!()
        };
        if !live(&row.row, root)
            || known.contains(&(symbol.path.clone(), symbol.start, symbol.qualname.clone()))
        {
            continue;
        }
        let vector = if let Some(blob) = row.blob.as_deref().filter(|v| !v.is_empty()) {
            finite_vector(blob)?;
            Some(
                blob.chunks_exact(4)
                    .map(|b| f32::from_le_bytes(b.try_into().expect("four-byte chunk")))
                    .collect::<Vec<_>>(),
            )
        } else if let (Some(slot), Some(root)) = (row.slot, root.or(store_root)) {
            if store.is_none() {
                store = VectorStore::open(
                    &root.join(".ken/vectors"),
                    VectorSpace::Symbols,
                    query.len(),
                    None,
                )
                .ok();
            }
            store
                .as_ref()
                .and_then(|s| s.read(&[slot]).ok())
                .and_then(|mut rows| rows.pop())
        } else {
            None
        };
        let score = if let Some(vector) = vector.filter(|v| v.len() == query.len()) {
            if vector.iter().any(|v| !v.is_finite()) {
                return Err(invalid("legacy search requires finite embedding vectors"));
            }
            let scores = math.cosine_against(query, &vector, 1, query.len())?;
            finite_scores(&scores)?;
            f64::from(scores[0])
        } else {
            f64::NEG_INFINITY
        };
        scored.push(Scored {
            row: row.row,
            score,
        });
    }
    scored.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .expect("finite cosine or unavailable sentinel")
            .then(a.row.path().cmp(b.row.path()))
            .then(a.row.line().cmp(&b.row.line()))
    });
    Ok(scored)
}
fn name_tokens(text: &str) -> BTreeSet<String> {
    let mut spaced = String::new();
    let mut previous = None;
    for c in text.chars() {
        if c.is_ascii_uppercase()
            && previous.is_some_and(|p: char| p.is_ascii_lowercase() || p.is_ascii_digit())
        {
            spaced.push(' ');
        }
        spaced.push(c);
        previous = Some(c);
    }
    spaced
        .to_lowercase()
        .split(|c: char| !c.is_ascii_lowercase() && !c.is_ascii_digit())
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect()
}
fn literal_tier(ident: &str, row: &LegacyRow) -> u8 {
    let lowered = ident.to_ascii_lowercase();
    let tokens = name_tokens(ident);
    let mut best = 0;
    for name in row.names() {
        let low = name.to_lowercase();
        if low == lowered {
            return 3;
        }
        if low.ends_with(&format!(".{lowered}")) {
            best = best.max(2);
        } else if !tokens.is_empty() && tokens.is_subset(&name_tokens(name)) {
            best = best.max(1);
        }
    }
    best
}
fn fused(scored: Vec<Scored>, ident: Option<&str>, limit: isize) -> Vec<(Scored, u8)> {
    let limit = usize::try_from(limit.max(1)).unwrap_or(usize::MAX);
    let Some(ident) = ident else {
        return scored.into_iter().take(limit).map(|r| (r, 0)).collect();
    };
    let tiers = scored
        .iter()
        .map(|r| literal_tier(ident, &r.row))
        .collect::<Vec<_>>();
    let exact = (0..scored.len())
        .filter(|&i| tiers[i] == 3)
        .collect::<Vec<_>>();
    let mut rest = (0..scored.len())
        .filter(|&i| tiers[i] != 3)
        .map(|i| (i, 1. / (60. + i as f64 + 1.)))
        .collect::<BTreeMap<_, _>>();
    let mut partial = (0..scored.len())
        .filter(|&i| tiers[i] > 0 && tiers[i] < 3)
        .collect::<Vec<_>>();
    partial.sort_by_key(|&i| (std::cmp::Reverse(tiers[i]), i));
    for (rank, i) in partial.into_iter().enumerate() {
        *rest.get_mut(&i).expect("partial is not exact") += 1. / (60. + rank as f64 + 1.);
    }
    let mut rest = rest.into_iter().collect::<Vec<_>>();
    rest.sort_by(|(i, a), (j, b)| b.total_cmp(a).then(i.cmp(j)));
    let order = exact
        .into_iter()
        .chain(rest.into_iter().map(|(i, _)| i))
        .take(limit)
        .collect::<Vec<_>>();
    let mut rows = scored.into_iter().map(Some).collect::<Vec<_>>();
    order
        .into_iter()
        .map(|i| (rows[i].take().expect("unique fused index"), tiers[i]))
        .collect()
}
fn label(tier: u8) -> Option<&'static str> {
    match tier {
        3 => Some("exact"),
        2 => Some("qualified"),
        1 => Some("tokens"),
        _ => None,
    }
}
fn rounded(score: f64) -> f64 {
    format!("{score:.3}")
        .parse()
        .expect("finite decimal cosine")
}
fn file_hits(conn: &Connection, ranked: Vec<(Scored, u8)>) -> Result<LegacyResponse> {
    let mut hits = Vec::new();
    let mut outline = conn.prepare(
        "SELECT kind,name,line_start FROM ci_symbols WHERE file_id=? ORDER BY line_start LIMIT 8",
    )?;
    for (scored, tier) in ranked {
        let LegacyRow::File(row) = scored.row else {
            unreachable!()
        };
        let symbols = outline
            .query_map([row.id], |r| {
                Ok(OutlineSymbol {
                    kind: r.get(0)?,
                    name: r.get(1)?,
                    line: r.get(2)?,
                })
            })?
            .collect::<rusqlite::Result<_>>()?;
        hits.push(LegacyFileHit {
            path: row.path,
            language: row
                .language
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| "text".into()),
            score: rounded(scored.score),
            literal_match: label(tier),
            symbols,
        });
    }
    Ok(LegacyResponse::Files(hits))
}
pub(super) fn search(
    models: &dyn CompatibilityModels,
    conn: &Connection,
    root: Option<&Path>,
    query: &PythonText,
    scope: &str,
    limit: isize,
) -> Result<LegacyResponse> {
    if !matches!(scope, "files" | "symbols") {
        return Err(invalid("legacy responses require scope=files or symbols"));
    }
    let query_vector = models.legacy_query(conn, query)?;
    if query_vector.iter().any(|v| !v.is_finite()) {
        return Err(invalid("legacy search requires finite query vectors"));
    }
    let math = NativeVectorMath::platform()?;
    let normalized = math.normalize_query(&query_vector, QueryNorm::AddEpsilon(1e-12))?;
    let store_root = database_root(conn);
    let scored = scored_rows(conn, scope, root, store_root.as_deref(), &normalized, &math)?;
    let ident = identifier(query);
    let scored = if scope == "symbols" {
        include_exact(
            conn,
            scored,
            ident.as_deref(),
            root,
            store_root.as_deref(),
            &normalized,
            &math,
        )?
    } else {
        scored
    };
    let ranked = fused(scored, ident.as_deref(), limit);
    if scope == "files" {
        file_hits(conn, ranked)
    } else {
        Ok(LegacyResponse::Symbols(
            ranked
                .into_iter()
                .map(|(scored, tier)| {
                    let LegacyRow::Symbol(row) = scored.row else {
                        unreachable!()
                    };
                    LegacySymbolHit {
                        qualname: row.qualname,
                        kind: row.kind,
                        file: row.path,
                        line: row.start,
                        line_end: row.end,
                        docstring: row.docstring,
                        score: scored.score.is_finite().then(|| rounded(scored.score)),
                        literal_match: label(tier),
                    }
                })
                .collect(),
        ))
    }
}
