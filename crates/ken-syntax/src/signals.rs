//! Live structural signals using the original grammar registries and traversal.
use crate::{GrammarCatalog, Language, ParseError, SyntaxNode};
use ken_text::unicode::whitespace;
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct CallSite {
    pub name: String,
    pub line: usize,
}
#[derive(Clone, Debug, Serialize)]
pub struct ClassBases {
    pub name: String,
    pub bases: Vec<String>,
    pub line: usize,
}
#[derive(Clone, Debug, Serialize)]
pub struct WireSite {
    pub kind: String,
    pub trigger: String,
    pub decorator: String,
    pub line: usize,
}
#[derive(Default, Serialize)]
pub struct StructuralSignals {
    pub calls: Vec<CallSite>,
    pub bases: Vec<ClassBases>,
    pub wiring: Vec<WireSite>,
}

pub fn language(label: &str) -> Option<Language> {
    serde_json::from_value(serde_json::Value::String(label.into())).ok()
}
fn text(node: Option<SyntaxNode<'_>>, source: &[u8]) -> String {
    node.map(|n| String::from_utf8_lossy(&source[n.start_byte()..n.end_byte()]).into_owned())
        .unwrap_or_default()
}
fn rightmost(node: Option<SyntaxNode<'_>>, source: &[u8]) -> Option<String> {
    let mut stack = node.into_iter().collect::<Vec<_>>();
    let mut best = None::<(usize, String)>;
    while let Some(n) = stack.pop() {
        let children = n.children();
        if children.is_empty() {
            if (n.kind().ends_with("identifier")
                || matches!(n.kind(), "type_identifier" | "field_identifier"))
                && best
                    .as_ref()
                    .is_none_or(|(start, _)| n.start_byte() > *start)
            {
                best = Some((n.start_byte(), text(Some(n), source)));
            }
        } else {
            stack.extend(children);
        }
    }
    best.map(|(_, name)| name)
}
fn first_string(node: Option<SyntaxNode<'_>>, source: &[u8]) -> Option<String> {
    let mut stack = node.into_iter().collect::<Vec<_>>();
    let mut best = None::<(usize, String)>;
    while let Some(n) = stack.pop() {
        if matches!(
            n.kind(),
            "string" | "string_literal" | "interpreted_string_literal" | "raw_string_literal"
        ) {
            let value = literal(&text(Some(n), source), true);
            if !value.is_empty()
                && best
                    .as_ref()
                    .is_none_or(|(start, _)| n.start_byte() < *start)
            {
                best = Some((n.start_byte(), value));
            }
        }
        stack.extend(n.children());
    }
    best.map(|(_, value)| value)
}
fn trim(s: &str) -> &str {
    s.trim_matches(whitespace)
}
fn literal(s: &str, backtick: bool) -> String {
    trim(trim(s).trim_matches(|c| c == '\'' || c == '"' || (backtick && c == '`'))).into()
}
fn call_kind(kind: &str, lang: Language) -> bool {
    match lang {
        Language::Python => kind == "call",
        Language::JavaScript | Language::TypeScript => {
            matches!(kind, "call_expression" | "new_expression")
        }
        Language::Rust => matches!(kind, "call_expression" | "macro_invocation"),
        Language::Go | Language::C => kind == "call_expression",
        Language::Java => matches!(kind, "method_invocation" | "object_creation_expression"),
        _ => ["call_expression", "call", "method_invocation", "invocation"]
            .iter()
            .any(|hint| kind.contains(hint)),
    }
}
fn dart_call(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    if node.kind() != "selector" || !node.children().iter().any(|c| c.kind() == "argument_part") {
        return None;
    }
    let mut previous = None;
    for child in node.parent()?.children() {
        if child.start_byte() == node.start_byte()
            && child.end_byte() == node.end_byte()
            && child.kind() == node.kind()
        {
            break;
        }
        if child.is_named()
            && let Some(name) = rightmost(Some(child), source)
        {
            previous = Some(name);
        }
    }
    previous
}
fn bases(node: SyntaxNode<'_>, source: &[u8], name: &str) -> Vec<String> {
    let mut containers = ["superclasses", "superclass", "super_interfaces"]
        .into_iter()
        .filter_map(|f| node.field(f))
        .collect::<Vec<_>>();
    containers.extend(node.children().into_iter().filter(|c| {
        matches!(
            c.kind(),
            "class_heritage"
                | "extends_clause"
                | "implements_clause"
                | "superclass"
                | "super_interfaces"
        )
    }));
    let mut found = Vec::new();
    for container in containers {
        let mut stack = vec![container];
        while let Some(n) = stack.pop() {
            if matches!(
                n.kind(),
                "identifier"
                    | "type_identifier"
                    | "scoped_type_identifier"
                    | "constructor_type"
                    | "generic_type"
            ) {
                let raw = text(Some(n), source);
                let base = trim(
                    raw.split('<')
                        .next()
                        .unwrap()
                        .rsplit('.')
                        .next()
                        .unwrap()
                        .rsplit("::")
                        .next()
                        .unwrap(),
                );
                if !base.is_empty() && base != name && !found.iter().any(|s| s == base) {
                    found.push(base.into());
                    continue;
                }
            }
            stack.extend(n.children());
        }
    }
    found
}
fn is_definition(n: SyntaxNode<'_>) -> bool {
    n.kind() != "decorated_definition"
        && (n.kind().ends_with("definition")
            || n.kind().ends_with("declaration")
            || matches!(n.kind(), "method_signature" | "function_item"))
}
fn target_line(node: SyntaxNode<'_>) -> usize {
    let Some(parent) = node.parent() else {
        return node.start_point()[0] + 1;
    };
    let candidates = parent
        .children()
        .into_iter()
        .filter(|n| is_definition(*n))
        .collect::<Vec<_>>();
    let target = candidates
        .iter()
        .find(|n| n.start_byte() >= node.start_byte())
        .or(candidates.first())
        .copied()
        .or_else(|| {
            parent
                .parent()
                .and_then(|p| p.children().into_iter().find(|n| is_definition(*n)))
        });
    target.map_or(node.start_point()[0] + 1, |n| {
        n.field("name").unwrap_or(n).start_point()[0] + 1
    })
}
fn decorator(node: SyntaxNode<'_>, source: &[u8]) -> WireSite {
    let mut name = node
        .children()
        .into_iter()
        .find(|n| {
            matches!(
                n.kind(),
                "call"
                    | "call_expression"
                    | "attribute"
                    | "member_expression"
                    | "identifier"
                    | "scoped_identifier"
            )
        })
        .or_else(|| node.field("name"))
        .or_else(|| {
            node.children()
                .into_iter()
                .find(|n| n.kind().ends_with("identifier"))
        });
    if let Some(n) = name
        && matches!(n.kind(), "call" | "call_expression")
    {
        name = n.field("function").or(Some(n));
    }
    let raw = name.map_or_else(
        || text(Some(node), source).trim_start_matches('@').into(),
        |n| text(Some(n), source),
    );
    let dotted = trim(
        raw.rsplit_once('(')
            .map_or(raw.as_str(), |(prefix, _)| prefix),
    );
    let attr = trim(dotted.rsplit('.').next().unwrap());
    let lower = attr.to_lowercase();
    let route = [
        "route",
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "websocket",
        "getmapping",
        "postmapping",
        "requestmapping",
        "putmapping",
        "deletemapping",
        "patchmapping",
        "query",
        "mutation",
        "subscription",
    ]
    .contains(&lower.as_str());
    let cli = ["command", "group", "add_parser", "add_subparsers"].contains(&lower.as_str());
    let literal = first_string(Some(node), source);
    WireSite {
        kind: if route {
            "route"
        } else if cli {
            "cli"
        } else {
            "decorator"
        }
        .into(),
        trigger: literal.unwrap_or_else(|| {
            if route || cli || attr.is_empty() {
                dotted
            } else {
                attr
            }
            .into()
        }),
        decorator: if route || cli || attr.is_empty() {
            dotted
        } else {
            attr
        }
        .into(),
        line: target_line(node),
    }
}
fn env_object(s: &str) -> bool {
    ["process.env", "import.meta.env"]
        .iter()
        .any(|o| s == *o || s.ends_with(&format!(".{o}")))
}
fn env(node: SyntaxNode<'_>, source: &[u8]) -> Option<WireSite> {
    let (dotted, key) = match node.kind() {
        "call" => {
            let dotted = text(node.field("function"), source);
            if !["getenv", "environ", "get"].contains(&dotted.rsplit('.').next().unwrap())
                || (!dotted.contains("environ") && !dotted.contains("getenv"))
            {
                return None;
            }
            (dotted, first_string(node.field("arguments"), source)?)
        }
        "subscript" => {
            let dotted = text(node.field("value"), source);
            let sub = node.field("subscript")?;
            if dotted.rsplit('.').next() != Some("environ") || sub.kind() != "string" {
                return None;
            }
            (dotted, literal(&text(Some(sub), source), false))
        }
        "member_expression" | "subscript_expression" => {
            let dotted = text(node.field("object"), source);
            if !env_object(&dotted) {
                return None;
            }
            let index = node.field(if node.kind() == "member_expression" {
                "property"
            } else {
                "index"
            })?;
            if node.kind() == "subscript_expression" && index.kind() != "string" {
                return None;
            }
            let raw = text(Some(index), source);
            (
                dotted,
                if node.kind() == "member_expression" {
                    trim(&raw).into()
                } else {
                    literal(&raw, true)
                },
            )
        }
        _ => return None,
    };
    (!key.is_empty()).then(|| WireSite {
        kind: "env".into(),
        trigger: key,
        decorator: dotted,
        line: node.start_point()[0] + 1,
    })
}
pub fn extract(
    catalog: &GrammarCatalog,
    label: &str,
    source: &[u8],
) -> Result<StructuralSignals, ParseError> {
    let mut result = StructuralSignals::default();
    let Some(lang) = language(label) else {
        return Ok(result);
    };
    if source.is_empty() {
        return Ok(result);
    }
    // Original signals select TypeScript by language, even for a .tsx path.
    let tree = catalog.syntax(lang, source, "signals")?;
    let mut stack = vec![tree.root()];
    while let Some(node) = stack.pop() {
        let call = if lang == Language::Dart {
            dart_call(node, source)
        } else if call_kind(node.kind(), lang) {
            let callee = ["function", "constructor", "macro", "name", "type"]
                .into_iter()
                .find_map(|f| node.field(f))
                .or_else(|| {
                    node.children()
                        .into_iter()
                        .find(|c| c.is_named() && !c.kind().contains("argument"))
                });
            rightmost(callee, source)
        } else {
            None
        };
        if let Some(name) = call {
            result.calls.push(CallSite {
                name,
                line: node.start_point()[0] + 1,
            });
        }
        let class = match lang {
            Language::Python | Language::Dart => node.kind() == "class_definition",
            Language::JavaScript | Language::TypeScript | Language::Java => {
                node.kind() == "class_declaration"
            }
            _ => false,
        };
        if class {
            let name = text(node.field("name"), source);
            if !name.is_empty() {
                result.bases.push(ClassBases {
                    bases: bases(node, source, &name),
                    name,
                    line: node.start_point()[0] + 1,
                });
            }
        }
        if matches!(
            node.kind(),
            "decorator" | "annotation" | "marker_annotation"
        ) {
            result.wiring.push(decorator(node, source));
        } else if let Some(site) = env(node, source) {
            result.wiring.push(site);
        }
        stack.extend(node.children());
    }
    Ok(result)
}
