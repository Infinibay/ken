use super::*;
use std::collections::{BTreeMap, BTreeSet, HashSet, VecDeque};
impl IndexNavigation {
    pub(super) fn imports(&self, id: i64) -> Result<Vec<Document>> {
        let mut query=self.conn.prepare("SELECT i.to_module,i.line,f.path FROM ci_imports i LEFT JOIN ci_files f ON f.id=i.to_file_id WHERE i.from_file_id=? ORDER BY i.line,i.to_module")?;
        Ok(query.query_map([id],|r|{let path:Option<String>=r.get(2)?;Ok(doc!("module":r.get::<_,String>(0)?,"path":path.clone(),"line":r.get::<_,i64>(1)?,"internal":path.is_some()))})?.collect::<rusqlite::Result<_>>()?)
    }
    pub(super) fn importers(&self, id: i64) -> Result<Vec<Document>> {
        let mut query=self.conn.prepare("SELECT src.path,src.language,i.to_module,i.line FROM ci_imports i JOIN ci_files src ON src.id=i.from_file_id WHERE i.to_file_id=? ORDER BY src.path,i.line")?;
        Ok(query.query_map([id],|r|{let language:Option<String>=r.get(1)?;Ok(doc!("path":r.get::<_,String>(0)?,"language":language.filter(|v|!v.is_empty()).unwrap_or_else(||"text".into()),"module":r.get::<_,String>(2)?,"line":r.get::<_,i64>(3)?))})?.collect::<rusqlite::Result<_>>()?)
    }
    pub fn module_graph(&self, path: &str, depth: i64, limit: i64) -> Result<Document> {
        let Some(root) = self.file(path)? else {
            return Ok(self.missing(path));
        };
        let depth = depth.max(0);
        let limit = limit.max(1) as usize;
        let mut seen = HashSet::from([root.id]);
        let mut queue = VecDeque::from([(root.id, 0)]);
        let mut edges = BTreeSet::new();
        let mut capped = false;
        let mut query=self.conn.prepare("SELECT from_file_id,to_file_id,line FROM ci_imports WHERE to_file_id IS NOT NULL AND(from_file_id=?1 OR to_file_id=?1) ORDER BY from_file_id,to_file_id,line")?;
        while let Some((id, distance)) = queue.pop_front() {
            if distance >= depth {
                continue;
            }
            let touching = query
                .query_map([id], |r| {
                    Ok((
                        r.get::<_, i64>(0)?,
                        r.get::<_, i64>(1)?,
                        r.get::<_, i64>(2)?,
                    ))
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            for (src, dst, line) in touching {
                edges.insert((src, dst, line));
                for next in [src, dst] {
                    if seen.contains(&next) {
                        continue;
                    }
                    if seen.len() >= limit {
                        capped = true;
                        continue;
                    }
                    seen.insert(next);
                    queue.push_back((next, distance + 1));
                }
            }
        }
        let ids = seen.iter().copied().collect::<Vec<_>>();
        let mut nodes = Vec::with_capacity(ids.len());
        // Stay below SQLite's portable bind limit, including for large graphs.
        for chunk in ids.chunks(900) {
            let placeholders = std::iter::repeat_n("?", chunk.len())
                .collect::<Vec<_>>()
                .join(",");
            let mut query=self.conn.prepare(&format!("SELECT id,path,language,symbol_count,indexed_at FROM ci_files WHERE id IN({placeholders})"))?;
            nodes.extend(
                query
                    .query_map(rusqlite::params_from_iter(chunk), FileRecord::row)?
                    .collect::<rusqlite::Result<Vec<_>>>()?,
            );
        }
        nodes.sort_by(|a, b| a.path.cmp(&b.path));
        let paths: BTreeMap<_, _> = nodes.iter().map(|f| (f.id, f.path.clone())).collect();
        let mut kept = edges
            .iter()
            .filter_map(|(s, d, l)| Some((paths.get(s)?.clone(), paths.get(d)?.clone(), *l)))
            .collect::<Vec<_>>();
        kept.sort();
        let omitted = edges.len() - kept.len();
        let mut result = doc!("ok":true,"root":root.path,"depth":depth,"nodes":nodes.iter().map(|f|doc!("path":f.path.clone(),"language":f.language(),"symbol_count":f.symbols)).collect::<Vec<_>>(),"edges":kept.into_iter().map(|(s,d,l)|doc!("kind":"import","from":s,"to":d,"line":l)).collect::<Vec<_>>());
        if capped || omitted > 0 {
            result.insert("truncated",doc!("node_limit":limit,"edges_omitted":omitted,"note":"raise `limit` to see the rest of the neighbourhood"));
        }
        Ok(result)
    }
    fn tests_for(&self, file: &FileRecord, limit: i64) -> Result<Vec<Document>> {
        let stem = Path::new(&file.path)
            .file_stem()
            .and_then(|v| v.to_str())
            .unwrap_or("");
        let lower = stem.to_lowercase();
        let conventional = [
            format!("test_{lower}"),
            format!("{lower}_test"),
            format!("{lower}_spec"),
            format!("{lower}.test"),
            format!("{lower}.spec"),
            format!("{lower}test"),
            format!("{lower}tests"),
            format!("{lower}spec"),
        ];
        let tokens = if STRUCTURAL.contains(&lower.as_str()) {
            BTreeSet::new()
        } else {
            name_tokens(stem)
        };
        let mut candidates: BTreeMap<String, (i64, Vec<&str>)> = BTreeMap::new();
        for importer in self.importers(file.id)? {
            let path = importer.get("path").string().unwrap();
            if looks_like_test(path) {
                let entry = candidates.entry(path.into()).or_default();
                entry.0 += 1;
                entry.1.push("imports target");
            }
        }
        let mut query=self.conn.prepare("SELECT path FROM ci_files WHERE path LIKE '%test%' OR path LIKE '%spec%' ORDER BY path")?;
        let paths = query
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        for path in paths {
            if !looks_like_test(&path) {
                continue;
            }
            let base = Path::new(&path)
                .file_stem()
                .and_then(|v| v.to_str())
                .unwrap_or("");
            let evidence = if conventional.contains(&base.to_lowercase()) {
                Some((3, "named for target"))
            } else if !tokens.is_empty() && tokens.is_subset(&name_tokens(base)) {
                Some((2, "name match"))
            } else {
                None
            };
            if let Some((score, reason)) = evidence {
                let entry = candidates.entry(path).or_default();
                entry.0 += score;
                entry.1.push(reason);
            }
        }
        let mut ranked = candidates.into_iter().collect::<Vec<_>>();
        ranked.sort_by(|(a, (s, _)), (b, (t, _))| t.cmp(s).then(a.cmp(b)));
        ranked.truncate(prefix(ranked.len(), limit));
        Ok(ranked.into_iter().map(|(path,(score,reasons))|doc!("path":path,"reason":reasons.join("; "),"score":score as f64)).collect())
    }
    pub fn find_tests(&self, path: &str, limit: i64) -> Result<Document> {
        let Some(file) = self.file(path)? else {
            return Ok(self.missing(path));
        };
        Ok(doc!("ok":true,"path":file.path.clone(),"tests":self.tests_for(&file,limit.max(1))?))
    }
    pub fn file_neighbors(&self, path: &str, limit: i64) -> Result<Document> {
        let Some(file) = self.file(path)? else {
            return Ok(self.missing(path));
        };
        let mut imports = self.imports(file.id)?;
        let mut importers = self.importers(file.id)?;
        let mut tests = self.tests_for(&file, limit)?;
        let mut seen = HashSet::new();
        let mut neighbors = Vec::new();
        for item in imports.iter().chain(&importers).chain(&tests) {
            if let Some(path) = item.get("path").string().filter(|p| !p.is_empty())
                && seen.insert(path.to_owned())
            {
                neighbors.push(path.to_owned());
            }
        }
        imports.truncate(prefix(imports.len(), limit));
        importers.truncate(prefix(importers.len(), limit));
        tests.truncate(prefix(tests.len(), limit));
        neighbors.truncate(prefix(neighbors.len(), limit));
        Ok(
            doc!("ok":true,"path":file.path,"imports":imports,"imported_by":importers,"tests":tests,"neighbors":neighbors),
        )
    }
}
const STRUCTURAL: &[&str] = &[
    "__init__", "__main__", "index", "main", "mod", "app", "lib", "setup", "types", "utils",
    "helpers", "common", "base", "core", "conftest",
];
fn name_tokens(name: &str) -> BTreeSet<String> {
    let mut spaced = String::new();
    let mut previous = None;
    for c in name.chars() {
        if previous.is_some_and(|p: char| p.is_ascii_lowercase() || p.is_ascii_digit())
            && c.is_ascii_uppercase()
        {
            spaced.push(' ');
        }
        spaced.push(c);
        previous = Some(c);
    }
    spaced
        .to_lowercase()
        .split(|c: char| !c.is_ascii_lowercase() && !c.is_ascii_digit())
        .filter(|s| {
            !s.is_empty() && !["test", "tests", "spec", "specs", "it", "should"].contains(s)
        })
        .map(str::to_owned)
        .collect()
}
fn looks_like_test(path: &str) -> bool {
    let p = Path::new(path);
    if p.components().any(|part| {
        ["test", "tests", "spec", "__tests__"]
            .contains(&part.as_os_str().to_string_lossy().to_lowercase().as_str())
    }) {
        return true;
    }
    let raw = p.file_name().and_then(|v| v.to_str()).unwrap_or("");
    let lower = raw.to_lowercase();
    const SUFFIXES: &[&str] = &[
        "_test.py",
        "_test.go",
        "_test.rs",
        "_test.ts",
        "_test.js",
        "_test.dart",
        "_spec.rb",
        "_spec.js",
        "_spec.ts",
        ".test.ts",
        ".test.tsx",
        ".test.js",
        ".test.jsx",
        ".test.mjs",
        ".spec.ts",
        ".spec.tsx",
        ".spec.js",
        ".spec.jsx",
        ".spec.mjs",
    ];
    if lower.starts_with("test_") || SUFFIXES.iter().any(|s| lower.ends_with(s)) {
        return true;
    }
    let extension = p
        .extension()
        .and_then(|v| v.to_str())
        .unwrap_or("")
        .to_lowercase();
    ["java", "cs", "kt", "kts"].contains(&extension.as_str())
        && p.file_stem().and_then(|v| v.to_str()).is_some_and(|s| {
            ["Test", "Tests", "Spec", "Specs"]
                .iter()
                .any(|suffix| s.ends_with(suffix))
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use ken_store::ProjectDatabase;
    #[test]
    fn bounded_graph_does_not_scan_unrelated_files() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::create_dir(directory.path().join(".ken")).unwrap();
        let paths = ProjectPaths::at(
            directory.path(),
            &DiscoveryContext {
                cwd: directory.path().into(),
                home: None,
                forced_root: None,
            },
        )
        .unwrap();
        let mut db = ProjectDatabase::open(&paths.db()).unwrap();
        db.initialize().unwrap();
        db.connection().execute_batch("INSERT INTO ci_files(path,content_hash,mtime,indexed_at)VALUES('root.py',X'00',0,0);
            WITH RECURSIVE files(n)AS(SELECT 1 UNION ALL SELECT n+1 FROM files WHERE n<5000)
            INSERT INTO ci_files(path,content_hash,mtime,indexed_at)SELECT 'unrelated/'||n||'.py',X'00',0,0 FROM files;").unwrap();
        drop(db);
        let nav = IndexNavigation::open(&paths).unwrap();
        // Deterministic SQLite instruction budget, independent of wall-clock speed.
        nav.conn.progress_handler(1000, Some(|| true)).unwrap();
        let graph = nav.module_graph("root.py", 0, 1).unwrap();
        assert_eq!(graph.get("nodes").array().len(), 1);
        assert_eq!(
            graph.get("nodes").array()[0].get("path").string(),
            Some("root.py")
        );
    }
}
