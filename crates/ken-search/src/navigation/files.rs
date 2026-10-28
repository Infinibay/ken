use super::*;
use ken_core::source_reader::SourceFileReader;
use ken_text::unicode::splitlines;
use rusqlite::params;

impl IndexNavigation {
    pub fn file_symbols(&self, path: &str, docs: bool) -> Result<Document> {
        let Some(file) = self.file(path)? else {
            return Ok(self.missing(path));
        };
        if !self.paths.root().join(&file.path).exists() {
            return Ok(doc!("ok":false,"error":"file missing on disk","path":file.path));
        }
        let mut query=self.conn.prepare("SELECT kind,name,qualname,line_start,line_end,docstring FROM ci_symbols WHERE file_id=? ORDER BY line_start,line_end,name")?;
        let rows = query
            .query_map([file.id], |r| symbols(r, docs))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(doc!("ok":true,"path":file.path.clone(),"language":file.language(),"symbols":rows))
    }
    pub fn file_outline(
        &self,
        path: &str,
        want_symbols: bool,
        want_imports: bool,
        docs: bool,
    ) -> Result<Document> {
        let Some(file) = self.file(path)? else {
            return Ok(self.missing(path));
        };
        let mut result = doc!("ok":true,"path":file.path.clone(),"language":file.language(),"symbol_count":file.symbols,"indexed_at":file.indexed);
        if docs {
            let doc:Option<String>=self.conn.query_row("SELECT text FROM ci_intent_sources WHERE file_id=? AND symbol_id IS NULL AND source_kind='module_docstring' LIMIT 1",[file.id],|r|r.get(0)).optional()?;
            result.insert("docstring", doc);
        }
        if want_symbols {
            result.insert(
                "symbols",
                self.file_symbols(&file.path, docs)?
                    .get("symbols")
                    .array()
                    .to_vec(),
            );
        }
        if want_imports {
            result.insert("imports", self.imports(file.id)?);
            result.insert("imported_by", self.importers(file.id)?);
        }
        Ok(result)
    }
    pub fn symbol_detail(&self, path: &str, qualname: &str, snippet: bool) -> Result<Document> {
        let Some(file) = self.file(path)? else {
            return Ok(self.missing(path));
        };
        let symbol=self.conn.query_row("SELECT kind,name,qualname,line_start,line_end,docstring FROM ci_symbols WHERE file_id=?1 AND(qualname=?2 OR name=?2) ORDER BY CASE WHEN qualname=?2 THEN 0 ELSE 1 END,line_start LIMIT 1",params![file.id,qualname],|r|symbols(r,true)).optional()?;
        let Some(symbol) = symbol else {
            return Ok(
                doc!("ok":false,"error":"symbol not indexed","path":file.path,"qualname":qualname),
            );
        };
        let text = if snippet {
            Some(self.line_range(
                &file.path,
                symbol.get("line").integer().unwrap(),
                symbol.get("line_end").integer().unwrap(),
            ))
        } else {
            None
        };
        let mut result =
            doc!("ok":true,"path":file.path.clone(),"language":file.language(),"symbol":symbol);
        if let Some(text) = text {
            result.insert("snippet", text);
        }
        Ok(result)
    }
    fn line_range(&self, path: &str, start: i64, end: i64) -> String {
        let read = || -> std::io::Result<Vec<u8>> {
            SourceFileReader::new(&self.paths)?
                .open(Path::new(path))?
                .read()
        };
        let Ok(bytes) = read() else {
            return String::new();
        };
        let text = String::from_utf8_lossy(&bytes);
        let lines = splitlines(&text);
        let begin = start.saturating_sub(1).max(0) as usize;
        let end = end.max(start.saturating_sub(1)).max(0) as usize;
        lines
            .iter()
            .skip(begin)
            .take(end.saturating_sub(begin))
            .enumerate()
            .map(|(i, line)| format!("{}: {line}", start.saturating_add(i as i64)))
            .collect::<Vec<_>>()
            .join("\n")
    }
    pub fn file_snippets(
        &self,
        path: &str,
        names: &[String],
        start: Option<i64>,
        end: Option<i64>,
        max_chars: i64,
    ) -> Result<Document> {
        let Some(file) = self.file(path)? else {
            return Ok(self.missing(path));
        };
        let mut ranges = Vec::new();
        if !names.is_empty() || start.is_none() {
            let mut query=self.conn.prepare("SELECT name,qualname,line_start,line_end FROM ci_symbols WHERE file_id=? ORDER BY line_start,line_end,name")?;
            let rows = query
                .query_map([file.id], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, i64>(2)?,
                        r.get::<_, i64>(3)?,
                    ))
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            for (name, qualname, start, end) in rows {
                if names.is_empty() {
                    if ranges.len() == 8 {
                        break;
                    }
                } else if !names.contains(&name)
                    && qualname.as_ref().is_none_or(|q| !names.contains(q))
                {
                    continue;
                }
                ranges.push((
                    qualname.filter(|s| !s.is_empty()).unwrap_or(name),
                    start,
                    end,
                ));
            }
        } else if let Some(start) = start {
            let start = start.max(1);
            let end = end.filter(|n| *n != 0).unwrap_or(start).max(start);
            ranges.push((format!("{}:{start}-{end}", file.path), start, end));
        }
        let mut remaining = max_chars.max(1) as usize;
        let mut snippets = Vec::new();
        for (label, start, end) in ranges {
            if remaining == 0 {
                break;
            }
            let text = self.line_range(&file.path, start, end);
            let text: String = text.chars().take(remaining).collect();
            remaining -= text.chars().count();
            snippets.push(doc!("label":label,"line":start,"line_end":end,"code":text));
        }
        Ok(doc!("ok":true,"path":file.path,"snippets":snippets))
    }
    pub fn project_overview(&self, depth: i64, limit: i64) -> Result<Document> {
        let mut query = self
            .conn
            .prepare("SELECT id,path,language,symbol_count,indexed_at FROM ci_files")?;
        let mut files = query
            .query_map([], FileRecord::row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let mut languages: Vec<(String, usize)> = Vec::new();
        let mut directories: Vec<(String, usize)> = Vec::new();
        fn count(v: &mut Vec<(String, usize)>, key: String) {
            if let Some((_, count)) = v.iter_mut().find(|(k, _)| k == &key) {
                *count += 1;
            } else {
                v.push((key, 1));
            }
        }
        for file in &files {
            count(&mut languages, file.language().into());
            let parts: Vec<_> = Path::new(&file.path)
                .components()
                .map(|p| p.as_os_str().to_string_lossy())
                .collect();
            if parts.len() > 1 {
                count(
                    &mut directories,
                    parts[..parts.len() - 1]
                        .iter()
                        .take(depth.max(1) as usize)
                        .map(|s| s.as_ref())
                        .collect::<Vec<_>>()
                        .join("/"),
                );
            }
        }
        languages.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
        directories.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
        let entries: Vec<String> = files
            .iter()
            .filter(|f| {
                Path::new(&f.path)
                    .file_name()
                    .and_then(|s| s.to_str())
                    .is_some_and(|s| {
                        [
                            "main.py",
                            "__main__.py",
                            "cli.py",
                            "server.py",
                            "app.py",
                            "index.ts",
                            "index.js",
                        ]
                        .contains(&s)
                    })
            })
            .take(limit.max(1) as usize)
            .map(|f| f.path.clone())
            .collect();
        files.sort_by(|a, b| b.symbols.cmp(&a.symbols).then_with(|| b.path.cmp(&a.path)));
        Ok(
            doc!("ok":true,"files":files.len(),"languages":Document::object(languages.into_iter().map(|(k,n)|(k,n.into()))),"top_dirs":directories.into_iter().take(limit.max(0)as usize).map(|(path,count)|doc!("path":path,"files":count)).collect::<Vec<_>>(),"entrypoints":entries,"largest_symbol_files":files.iter().take(limit.max(1)as usize).map(|f|doc!("path":f.path.clone(),"symbols":f.symbols)).collect::<Vec<_>>()),
        )
    }
}
