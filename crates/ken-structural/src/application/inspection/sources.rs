//! Source discovery stays with contracts/core; syntax facts reuse the admitted
//! grammar owner and never establish callable targets by spelling.
use super::{Result, invalid};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_reader::SourceFileReader,
};
use ken_syntax::{GrammarCatalog, Language, SyntaxNode};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeSet, VecDeque},
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ImportAlias {
    pub name: String,
    pub asname: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ImportStatement {
    pub kind: String,
    pub module: String,
    pub line: usize,
    pub top_level: bool,
    pub aliases: Vec<ImportAlias>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SourceFacts {
    pub path: String,
    pub language: String,
    pub sha256: String,
    pub imports: Vec<ImportStatement>,
    pub spellings: BTreeSet<String>,
    pub issues: Vec<Value>,
}
pub trait InspectionSources {
    fn checkpoint(&self) -> Result<()> {
        Ok(())
    }
    fn capture(&mut self, root: &Path, scope: &str, budget: Duration) -> Result<Value>;
    fn facts(&mut self, root: &Path, path: &str, budget: Duration) -> Result<SourceFacts>;
}
pub struct NativeSources {
    catalog: Arc<GrammarCatalog>,
    cache: VecDeque<(PathBuf, String, SourceFacts)>,
}
impl NativeSources {
    pub fn new(catalog: Arc<GrammarCatalog>) -> Self {
        Self {
            catalog,
            cache: VecDeque::new(),
        }
    }
}
impl InspectionSources for NativeSources {
    fn capture(&mut self, root: &Path, scope: &str, budget: Duration) -> Result<Value> {
        ken_contracts::checks::capture_sources(root, scope, budget)
            .map_err(|e| invalid(e.to_string()))
    }
    fn facts(&mut self, root: &Path, path: &str, budget: Duration) -> Result<SourceFacts> {
        let started = Instant::now();
        if budget.is_zero() {
            return Err(invalid("import discovery time budget exhausted"));
        }
        let context = DiscoveryContext::from_process()?;
        let paths = ProjectPaths::at(root, &context)?;
        let absolute = paths.resolve_inside(Path::new(path), &context)?;
        let reader = SourceFileReader::new(&paths)?;
        let bytes = reader
            .open(&absolute)?
            .read_bounded(2000000)?
            .ok_or_else(|| invalid("import discovery file budget exhausted"))?;
        let hash = format!("{:x}", Sha256::digest(&bytes));
        if started.elapsed() >= budget {
            return Err(invalid("import discovery time budget exhausted"));
        }
        if let Some(position) = self
            .cache
            .iter()
            .position(|(p, h, _)| p == &absolute && h == &hash)
        {
            let item = self.cache.remove(position).unwrap();
            let result = item.2.clone();
            self.cache.push_back(item);
            return Ok(result);
        }
        let facts = source_facts(&self.catalog, path, &bytes)?;
        if started.elapsed() >= budget {
            return Err(invalid("import discovery time budget exhausted"));
        }
        if self.cache.len() >= 128 {
            self.cache.pop_front();
        }
        self.cache.push_back((absolute, hash, facts.clone()));
        Ok(facts)
    }
}
fn text(node: SyntaxNode<'_>, source: &[u8]) -> String {
    String::from_utf8_lossy(&source[node.start_byte()..node.end_byte()]).into_owned()
}
fn alias(node: SyntaxNode<'_>, source: &[u8]) -> ImportAlias {
    if node.kind() == "aliased_import" {
        let children = node.named_children();
        let name = node
            .field("name")
            .or_else(|| children.first().copied())
            .map(|n| text(n, source))
            .unwrap_or_default();
        let asname = node
            .field("alias")
            .or_else(|| children.get(1).copied())
            .map(|n| text(n, source));
        ImportAlias { name, asname }
    } else {
        ImportAlias {
            name: if node.kind() == "wildcard_import" {
                "*".into()
            } else {
                text(node, source)
            },
            asname: None,
        }
    }
}
fn import_node(node: SyntaxNode<'_>, root_id: usize, source: &[u8]) -> Option<ImportStatement> {
    if node.kind() == "import_statement" {
        return Some(ImportStatement {
            kind: "import".into(),
            module: String::new(),
            line: node.start_point()[0] + 1,
            top_level: node.parent().is_some_and(|p| p.id() == root_id),
            aliases: node
                .named_children()
                .into_iter()
                .filter(|n| matches!(n.kind(), "dotted_name" | "aliased_import"))
                .map(|n| alias(n, source))
                .collect(),
        });
    }
    if node.kind() != "import_from_statement" {
        return None;
    }
    let children = node.named_children();
    let module = node.field("module_name").or_else(|| {
        children
            .iter()
            .copied()
            .find(|n| matches!(n.kind(), "dotted_name" | "relative_import"))
    })?;
    Some(ImportStatement {
        kind: "from".into(),
        module: text(module, source),
        line: node.start_point()[0] + 1,
        top_level: node.parent().is_some_and(|p| p.id() == root_id),
        aliases: children
            .into_iter()
            .filter(|n| {
                n.id() != module.id()
                    && matches!(
                        n.kind(),
                        "dotted_name" | "aliased_import" | "wildcard_import"
                    )
            })
            .map(|n| alias(n, source))
            .collect(),
    })
}
fn name_is_expression(node: SyntaxNode<'_>) -> bool {
    let mut parent = node.parent();
    while let Some(p) = parent {
        if matches!(p.kind(), "import_statement" | "import_from_statement") {
            return false;
        }
        parent = p.parent();
    }
    let Some(parent) = node.parent() else {
        return false;
    };
    if matches!(
        parent.kind(),
        "function_definition" | "class_definition" | "keyword_argument"
    ) && parent.field("name").is_some_and(|n| n.id() == node.id())
    {
        return false;
    }
    if matches!(
        parent.kind(),
        "parameters" | "lambda_parameters" | "global_statement" | "nonlocal_statement"
    ) {
        return false;
    }
    if matches!(
        parent.kind(),
        "default_parameter" | "typed_default_parameter" | "typed_parameter"
    ) && parent
        .field("name")
        .or_else(|| parent.named_children().first().copied())
        .is_some_and(|n| n.id() == node.id())
    {
        return false;
    }
    true
}
pub fn source_facts(
    catalog: &Arc<GrammarCatalog>,
    path: &str,
    source: &[u8],
) -> Result<SourceFacts> {
    let mut result = SourceFacts {
        path: path.into(),
        language: String::new(),
        sha256: format!("{:x}", Sha256::digest(source)),
        imports: Vec::new(),
        spellings: BTreeSet::new(),
        issues: Vec::new(),
    };
    let registry = ken_syntax::ParserRegistry::with_shared_catalog(catalog.clone());
    let language = registry
        .detect(Path::new(path), Some(source))
        .map_err(|e| invalid(e.to_string()))?;
    let Some(language) = language else {
        return Err(invalid("unsupported import discovery"));
    };
    result.language = language.as_str().into();
    if language != Language::Python {
        let parsed = registry
            .parse(language, source, path)
            .map_err(|e| invalid(e.to_string()))?;
        result.imports = parsed
            .imports
            .into_iter()
            .map(|i| ImportStatement {
                kind: "import".into(),
                module: String::new(),
                line: i.line,
                top_level: false,
                aliases: vec![ImportAlias {
                    name: i.module,
                    asname: None,
                }],
            })
            .collect();
        return Ok(result);
    }
    std::str::from_utf8(source).map_err(|_| invalid("non-UTF8 Python import metadata"))?;
    let tree = catalog
        .syntax(Language::Python, source, path)
        .map_err(|e| invalid(e.to_string()))?;
    let root = tree.root();
    if root.has_error() {
        return Err(invalid("invalid Python source syntax"));
    }
    let mut queue = VecDeque::from([root]);
    while let Some(node) = queue.pop_front() {
        if let Some(import) = import_node(node, root.id(), source) {
            result.imports.push(import);
        }
        if node.kind() == "identifier" && name_is_expression(node) {
            result.spellings.insert(text(node, source));
        }
        if node.kind() == "concatenated_string" {
            let mut combined = String::new();
            let mut valid = true;
            for child in node.named_children() {
                if let Some(decoded) =
                    ken_syntax::decode_python_string_literal(&text(child, source))
                        .and_then(|p| p.to_utf8())
                {
                    combined.push_str(&decoded);
                } else {
                    valid = false;
                }
            }
            if valid {
                result.spellings.insert(combined);
                continue;
            }
        }
        if node.kind() == "string"
            && node
                .parent()
                .is_none_or(|p| p.kind() != "concatenated_string")
            && let Some(decoded) = ken_syntax::decode_python_string_literal(&text(node, source))
                .and_then(|p| p.to_utf8())
        {
            result.spellings.insert(decoded);
        }
        queue.extend(node.named_children());
    }
    Ok(result)
}
