//! Precision-tiered binding of live syntax signals to indexed definitions.
use super::{IndexNavigation, Result};
use ken_core::{source_reader::SourceFileReader, tool_output::Document};
use ken_retrieval::source_snapshot::SourceError;
use ken_syntax::{
    GrammarCatalog,
    signals::{self, StructuralSignals},
};
use serde::Deserialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct CallGraphRequest {
    pub qualname: String,
    pub path: Option<String>,
    pub direction: String,
    pub min_confidence: Document,
    pub limit: i64,
}
impl Default for CallGraphRequest {
    fn default() -> Self {
        Self {
            qualname: String::new(),
            path: None,
            direction: "both".into(),
            min_confidence: "T2".into(),
            limit: 50,
        }
    }
}
struct Definition {
    id: i64,
    name: String,
    qualname: Option<String>,
    kind: String,
    start: i64,
    end: i64,
    file_id: i64,
    path: String,
    language: String,
}
struct LiveCodeflow<'a> {
    catalog: &'a GrammarCatalog,
    reader: SourceFileReader,
    files: Vec<(i64, String, String)>,
    defs: Vec<Definition>,
    names: BTreeMap<String, Vec<usize>>,
    imports: BTreeMap<i64, BTreeSet<i64>>,
    enclosing: BTreeMap<String, Vec<(String, i64, i64)>>,
}
impl<'a> LiveCodeflow<'a> {
    fn new(nav: &'a IndexNavigation, catalog: &'a GrammarCatalog) -> Result<Self> {
        let files = nav
            .conn
            .prepare("SELECT id,path,language FROM ci_files WHERE language IS NOT NULL")?
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
            .collect::<rusqlite::Result<_>>()?;
        let defs=nav.conn.prepare("SELECT s.id,s.name,s.qualname,s.kind,s.line_start,s.line_end,s.file_id,f.path,f.language FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE f.language IS NOT NULL")?
            .query_map([],|r|Ok(Definition{id:r.get(0)?,name:r.get(1)?,qualname:r.get(2)?,kind:r.get(3)?,start:r.get(4)?,end:r.get(5)?,file_id:r.get(6)?,path:r.get(7)?,language:r.get(8)?}))?.collect::<rusqlite::Result<Vec<_>>>()?;
        let mut names = BTreeMap::<String, Vec<usize>>::new();
        for (i, d) in defs.iter().enumerate() {
            names.entry(d.name.clone()).or_default().push(i);
        }
        let mut imports = BTreeMap::<i64, BTreeSet<i64>>::new();
        let mut query = nav.conn.prepare(
            "SELECT from_file_id,to_file_id FROM ci_imports WHERE to_file_id IS NOT NULL",
        )?;
        for row in query.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?)))? {
            let (a, b) = row?;
            imports.entry(a).or_default().insert(b);
        }
        let mut enclosing = BTreeMap::<String, Vec<(String, i64, i64)>>::new();
        let mut query=nav.conn.prepare("SELECT s.name,s.qualname,s.line_start,s.line_end,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE f.language IS NOT NULL")?;
        for row in query.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, String>(4)?,
            ))
        })? {
            let (name, qual, start, end, path) = row?;
            enclosing.entry(path).or_default().push((
                qual.filter(|s| !s.is_empty()).unwrap_or(name),
                start,
                end,
            ));
        }
        Ok(Self {
            catalog,
            reader: SourceFileReader::new(&nav.paths).map_err(SourceError::from)?,
            files,
            defs,
            names,
            imports,
            enclosing,
        })
    }
    fn source(&self, path: &str) -> Vec<u8> {
        self.reader
            .open(Path::new(path))
            .and_then(|s| s.read())
            .unwrap_or_default()
    }
    fn signals(&self, language: &str, source: &[u8]) -> Result<StructuralSignals> {
        signals::extract(self.catalog, language, source)
            .map_err(|e| ken_retrieval::RetrievalError::Invalid(e.to_string()).into())
    }
    fn resolve(&self, name: &str, file: i64) -> Option<(&Definition, &'static str)> {
        let candidates = self.names.get(name)?;
        let same = candidates
            .iter()
            .filter(|&&i| self.defs[i].file_id == file)
            .copied()
            .collect::<Vec<_>>();
        if same.len() == 1 {
            return Some((&self.defs[same[0]], "T1"));
        }
        if candidates.len() == 1 {
            return Some((&self.defs[candidates[0]], "T1"));
        }
        let imported = candidates
            .iter()
            .filter(|&&i| {
                self.imports
                    .get(&file)
                    .is_some_and(|s| s.contains(&self.defs[i].file_id))
            })
            .copied()
            .collect::<Vec<_>>();
        (imported.len() == 1).then(|| (&self.defs[imported[0]], "T2"))
    }
    fn enclosing(&self, path: &str, line: usize) -> String {
        let mut best = None::<(&str, i64)>;
        for (qual, start, end) in self.enclosing.get(path).into_iter().flatten() {
            if *start <= line as i64
                && line as i64 <= *end
                && best.is_none_or(|(_, span)| end - start < span)
            {
                best = Some((qual, end - start));
            }
        }
        best.map_or("<module>", |(qual, _)| qual).into()
    }
    fn callgraph(&self, request: &CallGraphRequest) -> Result<Document> {
        let path = request.path.as_ref().map(|p| {
            Path::new(p)
                .components()
                .map(|p| p.as_os_str().to_string_lossy())
                .collect::<Vec<_>>()
                .join("/")
                .trim_start_matches(['.', '/'])
                .to_owned()
        });
        let target = self
            .names
            .get(request.qualname.rsplit('.').next().unwrap())
            .into_iter()
            .flatten()
            .map(|&i| &self.defs[i])
            .find(|d| {
                (d.qualname.as_deref() == Some(&request.qualname) || d.name == request.qualname)
                    && path.as_ref().is_none_or(|p| p == &d.path)
            });
        let Some(target) = target else {
            return Ok(
                doc!("ok":false,"error":"symbol not found","qualname":request.qualname.clone()),
            );
        };
        if signals::language(&target.language).is_none() {
            return Ok(
                doc!("ok":false,"error":format!("language not parseable: {}",target.language),"qualname":request.qualname.clone()),
            );
        }
        let mut out = doc!("ok":true,"qualname":target.qualname.clone(),"file":target.path.clone(),"language":target.language.clone(),"min_confidence":request.min_confidence.clone());
        let tier_ok = |tier: &str| tier == "T1" || request.min_confidence.string() != Some("T1");
        if matches!(request.direction.as_str(), "callees" | "both") {
            let mut edges = Vec::new();
            let mut unresolved = Vec::new();
            let mut seen = BTreeSet::new();
            for call in self
                .signals(&target.language, &self.source(&target.path))?
                .calls
            {
                if (call.line as i64) < target.start || call.line as i64 > target.end {
                    continue;
                }
                let Some((candidate, tier)) = self.resolve(&call.name, target.file_id) else {
                    unresolved.push(doc!("name":call.name,"line":call.line));
                    continue;
                };
                if !tier_ok(tier) || !seen.insert((candidate.id, call.line)) {
                    continue;
                }
                edges.push(doc!("to_qualname":candidate.qualname.clone(),"file":candidate.path.clone(),"line":call.line,"confidence_tier":tier));
            }
            edges.truncate(request.limit.max(1) as usize);
            unresolved.truncate(super::prefix(unresolved.len(), request.limit));
            out.insert("callees", edges);
            out.insert("unresolved_callsites", unresolved);
        }
        if matches!(request.direction.as_str(), "callers" | "both") {
            let mut callers = Vec::new();
            for (file, path, language) in &self.files {
                let source = self.source(path);
                if !target.name.is_empty()
                    && !source
                        .windows(target.name.len())
                        .any(|s| s == target.name.as_bytes())
                {
                    continue;
                }
                for call in self.signals(language, &source)?.calls {
                    if call.name != target.name {
                        continue;
                    }
                    if let Some((candidate, tier)) = self.resolve(&call.name, *file)
                        && candidate.id == target.id
                        && tier_ok(tier)
                    {
                        callers.push(doc!("from_qualname":self.enclosing(path,call.line),"file":path.clone(),"line":call.line,"confidence_tier":tier));
                    }
                }
            }
            callers.truncate(request.limit.max(1) as usize);
            out.insert("callers", callers);
        }
        Ok(out)
    }
    fn wiring(&self, query: &str, kind: &str, limit: i64) -> Result<Document> {
        let mut rows = Vec::new();
        let query = query.to_lowercase();
        for (_, path, language) in &self.files {
            for wire in self.signals(language, &self.source(path))?.wiring {
                if (!kind.is_empty() && kind != wire.kind)
                    || (!query.is_empty()
                        && !format!("{} {}", wire.trigger, wire.decorator)
                            .to_lowercase()
                            .contains(&query))
                {
                    continue;
                }
                rows.push(doc!("kind":wire.kind,"trigger":wire.trigger,"decorator":wire.decorator,"handler_qualname":self.enclosing(path,wire.line),"file":path.clone(),"line":wire.line));
            }
        }
        rows.sort_by(|a, b| {
            a.get("kind")
                .string()
                .cmp(&b.get("kind").string())
                .then_with(|| a.get("file").string().cmp(&b.get("file").string()))
                .then_with(|| a.get("line").integer().cmp(&b.get("line").integer()))
        });
        let count = rows.len();
        rows.truncate(limit.max(1) as usize);
        Ok(doc!("ok":true,"count":count,"wiring":rows))
    }
    fn hierarchy(&self, qualname: &str, direction: &str, with_overrides: bool) -> Result<Document> {
        let mut classes = BTreeSet::new();
        let mut methods = BTreeMap::<String, BTreeSet<String>>::new();
        for def in &self.defs {
            if ["class", "interface", "trait", "struct", "enum"].contains(&def.kind.as_str()) {
                classes.insert(def.name.clone());
            } else if def.kind == "method"
                && let Some(qual) = def.qualname.as_ref().filter(|q| !q.is_empty())
            {
                methods
                    .entry(
                        qual.rsplit_once('.')
                            .map_or(qual.as_str(), |(cls, _)| cls)
                            .into(),
                    )
                    .or_default()
                    .insert(def.name.clone());
            }
        }
        // Insertion order belongs to the first occurrence; later duplicate class
        // names replace only the bases, matching the original Python dictionary.
        let mut children = Vec::<(String, Vec<String>)>::new();
        for (_, path, language) in &self.files {
            for class in self.signals(language, &self.source(path))?.bases {
                if let Some((_, bases)) = children.iter_mut().find(|(name, _)| *name == class.name)
                {
                    *bases = class.bases;
                } else {
                    children.push((class.name, class.bases));
                }
            }
        }
        let target = qualname.rsplit('.').next().unwrap();
        if !classes.contains(target) {
            return Ok(doc!("ok":false,"error":"class/type not found","qualname":qualname));
        }
        let mut adjacency = BTreeMap::<String, Vec<String>>::new();
        if direction == "super" {
            for (child, bases) in children {
                adjacency.insert(child, bases);
            }
        } else {
            for (child, bases) in children {
                for base in bases {
                    adjacency.entry(base).or_default().push(child.clone());
                }
            }
        }
        let mut frontier = adjacency.get(target).cloned().unwrap_or_default();
        let mut seen = BTreeSet::new();
        let mut result = Vec::new();
        while let Some(next) = frontier.pop() {
            if seen.insert(next.clone()) {
                result.push(next.clone());
                frontier.extend(adjacency.get(&next).into_iter().flatten().cloned());
            }
        }
        let mut sorted = result.clone();
        sorted.sort();
        let mut out = doc!("ok":true,"qualname":qualname,"direction":direction);
        out.insert(
            if direction == "super" {
                "ancestors"
            } else {
                "descendants"
            },
            sorted,
        );
        if with_overrides && direction == "sub" {
            let overrides = result
                .into_iter()
                .filter_map(|sub| {
                    let shared = methods
                        .get(&sub)?
                        .intersection(methods.get(target)?)
                        .cloned()
                        .collect::<Vec<_>>();
                    (!shared.is_empty())
                        .then(|| doc!("class":sub,"overrides":shared,"confidence":"best-effort"))
                })
                .collect::<Vec<_>>();
            out.insert("overrides", overrides);
        }
        Ok(out)
    }
}
impl IndexNavigation {
    pub fn callgraph(
        &self,
        catalog: &GrammarCatalog,
        request: &CallGraphRequest,
    ) -> Result<Document> {
        LiveCodeflow::new(self, catalog)?.callgraph(request)
    }
    pub fn wiring(
        &self,
        catalog: &GrammarCatalog,
        query: &str,
        kind: &str,
        limit: i64,
    ) -> Result<Document> {
        LiveCodeflow::new(self, catalog)?.wiring(query, kind, limit)
    }
    pub fn type_hierarchy(
        &self,
        catalog: &GrammarCatalog,
        qualname: &str,
        direction: &str,
        with_overrides: bool,
    ) -> Result<Document> {
        LiveCodeflow::new(self, catalog)?.hierarchy(qualname, direction, with_overrides)
    }
}
