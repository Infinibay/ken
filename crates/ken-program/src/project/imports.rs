//! Explicit source import identities and ambiguity, independent of filesystem lookup.
use super::*;
pub(super) fn parent(path: &str) -> String {
    let mut parts = path
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect::<Vec<_>>();
    parts.pop();
    let root = if path.starts_with("//") && !path.starts_with("///") {
        "//"
    } else if path.starts_with('/') {
        "/"
    } else {
        ""
    };
    let value = format!("{root}{}", parts.join("/"));
    if value.is_empty() { ".".into() } else { value }
}
fn dirname(path: &str) -> String {
    path.rsplit_once('/')
        .map(|(head, _)| {
            if head.is_empty() && path.starts_with('/') {
                "/".into()
            } else {
                head.trim_end_matches('/').into()
            }
        })
        .unwrap_or_default()
}
fn join(base: &str, part: &str) -> String {
    if part.starts_with('/') {
        part.into()
    } else if base.is_empty() || base.ends_with('/') {
        format!("{base}{part}")
    } else {
        format!("{base}/{part}")
    }
}
fn normal(path: &str) -> String {
    let absolute = path.starts_with('/');
    let root = if path.starts_with("//") && !path.starts_with("///") {
        "//"
    } else if absolute {
        "/"
    } else {
        ""
    };
    let mut parts = Vec::new();
    for part in path.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if parts.last().is_some_and(|p| *p != "..") {
                    parts.pop();
                } else if !absolute {
                    parts.push("..");
                }
            }
            _ => parts.push(part),
        }
    }
    let result = format!("{root}{}", parts.join("/"));
    if result.is_empty() {
        ".".into()
    } else {
        result
    }
}
#[derive(Default)]
pub(super) struct Imports {
    pub members: BTreeMap<(String, String), (String, String)>,
    pub modules: BTreeMap<(String, String), BTreeSet<String>>,
    pub ambiguous: BTreeSet<(String, String)>,
    pub options: BTreeMap<(String, String), BTreeSet<(String, String)>>,
    pub java_packages: BTreeMap<String, String>,
    pub go_packages: BTreeMap<String, (String, String)>,
    pub java_imports: BTreeMap<(String, String), BTreeSet<String>>,
    paths: BTreeSet<String>,
    common: String,
    mixed_paths: bool,
}
impl Imports {
    fn module_path(&self, origin: &str, module: &str, language: &str) -> Option<String> {
        let candidates = if language == "python" {
            let dots = module.len() - module.trim_start_matches('.').len();
            let tail = module[dots..].replace('.', "/");
            let stems = if dots > 0 {
                let mut base = parent(origin);
                for _ in 0..dots - 1 {
                    base = dirname(&base);
                }
                vec![normal(&join(&base, &tail))]
            } else {
                vec![
                    tail.clone(),
                    format!("src/{tail}"),
                    join(&parent(origin), &tail),
                ]
            };
            stems
                .into_iter()
                .flat_map(|s| [format!("{s}.py"), format!("{s}/__init__.py")])
                .collect::<Vec<_>>()
        } else {
            if !module.starts_with('.') {
                return None;
            }
            let candidate = normal(&join(&parent(origin), module));
            vec![
                candidate.clone(),
                format!("{candidate}.ts"),
                format!("{candidate}.tsx"),
                format!("{candidate}.js"),
                format!("{candidate}.jsx"),
                format!("{candidate}/index.ts"),
                format!("{candidate}/index.js"),
            ]
        };
        let existing = candidates
            .into_iter()
            .filter(|p| self.paths.contains(p))
            .collect::<BTreeSet<_>>();
        (existing.len() == 1).then(|| existing.into_iter().next().unwrap())
    }
    fn rust_module(&self, origin: &str, module: &str) -> Result<Option<String>> {
        let mut segments = module
            .split("::")
            .filter(|s| !s.is_empty() && *s != "self")
            .collect::<Vec<_>>();
        if segments.is_empty() {
            return Ok(None);
        }
        let directory = parent(origin);
        let mut base = directory.clone();
        if segments[0] == "crate" {
            segments.remove(0);
            if segments.is_empty() {
                return Ok(None);
            }
            if self.mixed_paths {
                return Err(ProgramError::Invalid(
                    "cannot mix absolute and relative project paths",
                ));
            }
            base = if self.paths.contains(&self.common) {
                parent(&self.common)
            } else {
                self.common.clone()
            };
        } else if segments[0] == "super" {
            base = dirname(&directory);
            segments.remove(0);
        }
        let roots = if base != directory {
            vec![base, directory]
        } else {
            vec![base]
        };
        let candidates = roots
            .into_iter()
            .flat_map(|root| {
                let stem = segments.iter().fold(root, |stem, part| join(&stem, part));
                [format!("{stem}.rs"), join(&stem, "mod.rs")]
            })
            .filter(|p| self.paths.contains(p))
            .collect::<BTreeSet<_>>();
        Ok((candidates.len() == 1).then(|| candidates.into_iter().next().unwrap()))
    }
    pub fn build(graph: &StructuralIr, units: &[(String, String)]) -> Result<Self> {
        let mut index = Self {
            paths: units.iter().map(|(path, _)| path.clone()).collect(),
            ..Self::default()
        };
        let absolute = index
            .paths
            .iter()
            .map(|p| p.starts_with('/'))
            .collect::<BTreeSet<_>>();
        index.mixed_paths = absolute.len() > 1;
        let mut common: Option<Vec<&str>> = None;
        for path in &index.paths {
            let parts = path
                .split('/')
                .filter(|s| !s.is_empty() && *s != ".")
                .collect::<Vec<_>>();
            if let Some(common) = &mut common {
                let n = common
                    .iter()
                    .zip(&parts)
                    .take_while(|(a, b)| a == b)
                    .count();
                common.truncate(n);
            } else {
                common = Some(parts);
            }
        }
        index.common = common.unwrap_or_default().join("/");
        if absolute.contains(&true) {
            index.common.insert(0, '/');
        }
        let entities = graph
            .entities
            .iter()
            .map(|(id, e)| (id.as_str(), e))
            .collect::<BTreeMap<_, _>>();
        for (path, language) in units {
            if matches!(language.as_str(), "java" | "go") {
                let module = format!("{path}::module");
                let entity = entities
                    .get(module.as_str())
                    .ok_or(ProgramError::Invalid("missing project module entity"))?;
                let package = entity
                    .attrs
                    .get("package")
                    .map(|v| serde_json::from_str::<String>(v.get()))
                    .transpose()?
                    .unwrap_or_default();
                if language == "java" {
                    index.java_packages.insert(path.clone(), package);
                } else {
                    index
                        .go_packages
                        .insert(path.clone(), (parent(path), package));
                }
            }
        }
        let declarations = graph
            .entities
            .iter()
            .filter(|(_, e)| {
                e.id.rsplit_once('/')
                    .is_some_and(|(p, _)| p == format!("{}::module", e.path))
                    && matches!(e.kind.as_str(), "CALLABLE" | "CLASS" | "STORAGE")
            })
            .map(|(_, e)| (e.path.clone(), e.name.clone()))
            .collect::<BTreeSet<_>>();
        let mut exported = BTreeMap::new();
        for f in graph.facts.iter().filter(|f| f.relation == "EXPORT_SYNTAX") {
            let path = f.subject.strip_suffix("::module").unwrap_or(&f.subject);
            if let Some(m) = regex(r"export\s+(?:async\s+)?(?:class|interface|function\*?)\s+(\w+)")
                .captures(&f.object)
            {
                exported.insert((path.to_owned(), m[1].to_owned()), m[1].to_owned());
            }
            if let Some(m) = full(r"export\s*\{([^}]+)\}\s*;?", &f.object) {
                for item in m[1].split(',') {
                    let names = regex(r"\s+as\s+")
                        .split(trim(item))
                        .map(str::to_owned)
                        .collect::<Vec<_>>();
                    if !names[0].is_empty() {
                        exported.insert(
                            (path.to_owned(), names.last().unwrap().clone()),
                            names[0].clone(),
                        );
                    }
                }
            }
        }
        let mut origins = BTreeMap::<(String, String), BTreeSet<Vec<String>>>::new();
        for f in graph.facts.iter().filter(|f| f.relation == "IMPORT_SYNTAX") {
            let origin = f.subject.strip_suffix("::module").unwrap_or(&f.subject);
            let language = fact_attr(f, "language");
            let language = language
                .as_str()
                .ok_or(ProgramError::Invalid("missing import language"))?;
            let spelling = &f.object;
            match language {
                "java" => {
                    if let Some(m) = full(r"import\s+([\w.]+)\s*;", spelling) {
                        let original = m[1].to_owned();
                        index
                            .java_imports
                            .entry((origin.into(), original.rsplit('.').next().unwrap().into()))
                            .or_default()
                            .insert(original);
                    }
                }
                "python" => {
                    if let Some(tail) = spelling.strip_prefix("import ") {
                        for item in tail.split(',') {
                            let names = regex(r"\s+as\s+")
                                .split(trim(item))
                                .map(str::to_owned)
                                .collect::<Vec<_>>();
                            let target = index.module_path(origin, &names[0], language);
                            let local = if names.len() == 2 {
                                names.last().unwrap().clone()
                            } else {
                                names[0].split('.').next().unwrap().into()
                            };
                            origins
                                .entry((origin.into(), local))
                                .or_default()
                                .insert(vec![
                                    "module".into(),
                                    target.clone().unwrap_or_else(|| format!("?{}", names[0])),
                                ]);
                            if let Some(target) =
                                target.filter(|_| names.len() == 2 || !names[0].contains('.'))
                            {
                                index
                                    .modules
                                    .entry((origin.into(), names.last().unwrap().clone()))
                                    .or_default()
                                    .insert(target);
                            }
                        }
                    }
                    if let Some(m) = full(r"(?s)from\s+([\w.]+)\s+import\s+(.+)", spelling) {
                        let target = index.module_path(origin, &m[1], language);
                        for item in m[2].trim_matches(['(', ')', ' ', '\n']).split(',') {
                            let names = regex(r"\s+as\s+")
                                .split(trim(item))
                                .map(str::to_owned)
                                .collect::<Vec<_>>();
                            let separator = if m[1].ends_with('.') { "" } else { "." };
                            let child = index.module_path(
                                origin,
                                &format!("{}{separator}{}", &m[1], names[0]),
                                language,
                            );
                            if let Some(child) = child.filter(|_| {
                                target.as_ref().is_none_or(|target| {
                                    !declarations.contains(&(target.clone(), names[0].clone()))
                                })
                            }) {
                                index
                                    .modules
                                    .entry((origin.into(), names.last().unwrap().clone()))
                                    .or_default()
                                    .insert(child.clone());
                                origins
                                    .entry((origin.into(), names.last().unwrap().clone()))
                                    .or_default()
                                    .insert(vec!["module".into(), child]);
                            } else if !names[0].is_empty() && names[0] != "*" {
                                origins
                                    .entry((origin.into(), names.last().unwrap().clone()))
                                    .or_default()
                                    .insert(vec![
                                        "member".into(),
                                        target.clone().unwrap_or_else(|| format!("?{}", &m[1])),
                                        names[0].clone(),
                                    ]);
                            }
                        }
                        if let Some(target) = target {
                            for item in m[2].trim_matches(['(', ')', ' ', '\n']).split(',') {
                                let names = regex(r"\s+as\s+")
                                    .split(trim(item))
                                    .map(str::to_owned)
                                    .collect::<Vec<_>>();
                                if names[0].is_empty() || names[0] == "*" {
                                    continue;
                                }
                                let key = (origin.into(), names.last().unwrap().clone());
                                let value = (target.clone(), names[0].clone());
                                index
                                    .options
                                    .entry(key.clone())
                                    .or_default()
                                    .insert(value.clone());
                                if index.members.get(&key).is_some_and(|old| old != &value) {
                                    index.ambiguous.insert(key.clone());
                                    index.members.remove(&key);
                                } else if !index.ambiguous.contains(&key) {
                                    index.members.insert(key, value);
                                }
                            }
                        }
                    }
                }
                "rust" => {
                    let spelling = trim(spelling);
                    if !spelling.starts_with("use ") || !spelling.ends_with(';') {
                        continue;
                    }
                    let body = trim(&spelling[4..spelling.len() - 1]);
                    let (prefix, tail) = body.rsplit_once("::").unwrap_or(("", body));
                    let items = if tail.starts_with('{') {
                        tail.trim_matches(['{', '}'])
                            .split(',')
                            .map(trim)
                            .collect::<Vec<_>>()
                    } else {
                        vec![tail]
                    };
                    for item in items {
                        if item.is_empty() {
                            continue;
                        }
                        let names = regex(r"\s+as\s+")
                            .split(item)
                            .map(str::to_owned)
                            .collect::<Vec<_>>();
                        let (mut original, mut local) =
                            (names[0].clone(), names.last().unwrap().clone());
                        if original == "self" {
                            original = prefix.rsplit("::").next().unwrap().into();
                            local = original.clone();
                        }
                        if let Some(target) = index.rust_module(origin, prefix)? {
                            index
                                .members
                                .insert((origin.into(), local), (target, original));
                        }
                    }
                }
                "javascript" | "typescript" => {
                    if let Some(m) = regex(r#"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]"#)
                        .captures(spelling)
                        && let Some(target) = index.module_path(origin, &m[2], language)
                    {
                        for item in m[1].split(',') {
                            let item = trim(item).strip_prefix("type ").unwrap_or(trim(item));
                            let names = regex(r"\s+as\s+")
                                .split(item)
                                .map(str::to_owned)
                                .collect::<Vec<_>>();
                            if let Some(original) =
                                exported.get(&(target.clone(), names[0].clone()))
                            {
                                index.members.insert(
                                    (origin.into(), names.last().unwrap().clone()),
                                    (target.clone(), original.clone()),
                                );
                            }
                        }
                    }
                }
                _ => {}
            }
        }
        for (key, origins) in origins {
            if origins.len() > 1 {
                index.ambiguous.insert(key);
            }
        }
        for key in &index.ambiguous {
            index.members.remove(key);
        }
        Ok(index)
    }
}
