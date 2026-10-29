//! Read-only views of indexed code. Navigation never constructs search models.
use crate::Result;
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    tool_output::Document,
};
use rusqlite::{Connection, OpenFlags, OptionalExtension, Row};
use serde::Deserialize;
use std::{path::Path, time::Duration};

macro_rules! doc {
    ($($key:literal : $value:expr),* $(,)?) => {
        Document::object(vec![$(($key, Document::from($value))),*])
    };
}
mod architecture;
mod changes;
mod codeflow;
pub use codeflow::CallGraphRequest;
mod files;
mod graph;
mod profile;
mod relations;

/// One read-only index snapshot. Open a new instance for each public tool call.
pub struct IndexNavigation {
    conn: Connection,
    paths: ProjectPaths,
}
struct FileRecord {
    id: i64,
    path: String,
    language: Option<String>,
    symbols: i64,
    indexed: i64,
}
impl FileRecord {
    fn row(row: &Row<'_>) -> rusqlite::Result<Self> {
        Ok(Self {
            id: row.get(0)?,
            path: row.get(1)?,
            language: row.get(2)?,
            symbols: row.get(3)?,
            indexed: row.get(4)?,
        })
    }
    fn language(&self) -> &str {
        self.language
            .as_deref()
            .filter(|s| !s.is_empty())
            .unwrap_or("text")
    }
}
#[derive(Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ReadRequest {
    pub path: String,
    pub include: Option<Vec<String>>,
    pub qualname: String,
    pub start_line: i64,
    pub end_line: i64,
    pub max_chars: i64,
}
impl IndexNavigation {
    pub fn open(paths: &ProjectPaths) -> Result<Self> {
        let conn = Connection::open_with_flags(
            paths.db(),
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        conn.busy_timeout(Duration::from_secs(5))?;
        conn.execute_batch("BEGIN DEFERRED")?;
        Ok(Self {
            conn,
            paths: paths.clone(),
        })
    }
    fn context(&self) -> DiscoveryContext {
        DiscoveryContext {
            cwd: self.paths.root().into(),
            home: std::env::var_os("HOME").map(Into::into),
            forced_root: None,
        }
    }
    fn confined(&self, path: &str) -> Result<String> {
        let resolved = self
            .paths
            .resolve_inside(Path::new(path), &self.context())
            .map_err(|e| ken_retrieval::RetrievalError::Invalid(e.to_string()))?;
        Ok(resolved
            .strip_prefix(self.paths.root())
            .expect("confined source")
            .to_string_lossy()
            .into_owned())
    }
    fn normalize(&self, path: &str) -> String {
        if Path::new(path).is_absolute()
            && let Ok(relative) = self.confined(path)
        {
            return relative;
        }
        let parts: Vec<_> = Path::new(path)
            .components()
            .filter(|p| !matches!(p, std::path::Component::CurDir))
            .map(|p| p.as_os_str().to_string_lossy())
            .collect();
        if parts.is_empty() {
            ".".into()
        } else if Path::new(path).is_absolute() {
            Path::new(path).to_string_lossy().into_owned()
        } else {
            parts.join("/")
        }
    }
    fn file(&self, path: &str) -> Result<Option<FileRecord>> {
        Ok(self
            .conn
            .query_row(
                "SELECT id,path,language,symbol_count,indexed_at FROM ci_files WHERE path=?",
                [self.normalize(path)],
                FileRecord::row,
            )
            .optional()?)
    }
    fn missing(&self, path: &str) -> Document {
        doc!("ok":false,"error":"file not indexed","path":self.normalize(path))
    }
    pub fn read(&self, request: &ReadRequest) -> Result<Document> {
        let path = self.confined(&request.path)?;
        let default = vec!["symbols".to_owned()];
        let include = request
            .include
            .as_ref()
            .filter(|v| !v.is_empty())
            .unwrap_or(&default);
        let allowed = ["symbols", "imports", "docstrings", "source", "profile"];
        let mut unknown: Vec<_> = include
            .iter()
            .filter(|v| !allowed.contains(&v.as_str()))
            .cloned()
            .collect();
        unknown.sort();
        unknown.dedup();
        if !unknown.is_empty() {
            let quoted = unknown
                .iter()
                .map(|s| format!("'{}'", s.replace('\\', "\\\\").replace('\'', "\\'")))
                .collect::<Vec<_>>()
                .join(", ");
            return Ok(
                doc!("ok":false,"error":format!("unknown include values: [{quoted}]"),"include":allowed.iter().map(|v|v.to_string()).collect::<Vec<_>>()),
            );
        }
        let want = |v: &str| include.iter().any(|item| item == v);
        let mut result = doc!("ok":true,"path":path.clone());
        let detail = !request.qualname.is_empty() && (want("symbols") || want("docstrings"));
        if detail {
            result.insert(
                "symbol",
                self.symbol_detail(&path, &request.qualname, want("source"))?,
            );
        } else if want("symbols") || want("imports") {
            result.insert(
                "outline",
                self.file_outline(&path, want("symbols"), want("imports"), want("docstrings"))?,
            );
        } else if want("docstrings") {
            result.insert("symbols", self.file_symbols(&path, true)?);
        }
        if want("source") && !detail {
            let symbols = if request.qualname.is_empty() {
                Vec::new()
            } else {
                vec![request.qualname.clone()]
            };
            result.insert(
                "source",
                self.file_snippets(
                    &path,
                    &symbols,
                    (request.start_line != 0).then_some(request.start_line),
                    (request.end_line != 0).then_some(request.end_line),
                    if request.max_chars == 0 {
                        12000
                    } else {
                        request.max_chars
                    },
                )?,
            );
        }
        if want("profile") {
            result.insert("profile", self.profile(&path, "file", 12)?);
        }
        Ok(result)
    }
    pub fn related(
        &self,
        target: &str,
        relation: &str,
        depth: i64,
        limit: i64,
    ) -> Result<Document> {
        let path = self.confined(target)?;
        match relation {
            "neighbors" => self.file_neighbors(&path, limit),
            "imports" => self.module_graph(&path, depth, limit),
            _ => Err(ken_retrieval::RetrievalError::Invalid(format!(
                "native ken_related does not support relation={relation}"
            ))
            .into()),
        }
    }
    pub fn test_search(&self, path: &str, limit: i64) -> Result<Document> {
        self.find_tests(&self.confined(path)?, limit)
    }
}
fn prefix(len: usize, limit: i64) -> usize {
    if limit < 0 {
        len.saturating_sub(limit.unsigned_abs().try_into().unwrap_or(usize::MAX))
    } else {
        len.min(limit.try_into().unwrap_or(usize::MAX))
    }
}
fn symbols(row: &Row<'_>, docs: bool) -> rusqlite::Result<Document> {
    let mut item = doc!("kind":row.get::<_,String>(0)?,"name":row.get::<_,String>(1)?,"qualname":row.get::<_,Option<String>>(2)?,"line":row.get::<_,i64>(3)?,"line_end":row.get::<_,i64>(4)?);
    if docs {
        item.insert("docstring", row.get::<_, Option<String>>(5)?);
    }
    Ok(item)
}
