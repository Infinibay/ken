//! Bind a whole explicit source namespace to a complete qualified symbol.
use crate::{
    EntityKey,
    text_patterns::{self as p, strip_chars},
};
use ken_text::{PythonText, unicode::identifier};
use serde::{Deserialize, Serialize};
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolLocator {
    pub namespace: String,
    pub qualname: String,
}
impl SymbolLocator {
    pub fn matches(&self, key: &EntityKey) -> bool {
        if key.qualname.as_deref() != Some(&self.qualname) {
            return false;
        }
        if key.path == self.namespace || module_name(&key.path).as_deref() == Some(&self.namespace)
        {
            return true;
        }
        if key.path.ends_with(".java") && self.namespace.split('.').all(identifier) {
            let mut parts: Vec<_> = key
                .path
                .split('/')
                .filter(|p| !p.is_empty() && *p != ".")
                .collect();
            parts.pop();
            let package: Vec<_> = self.namespace.split('.').collect();
            return parts.ends_with(&package);
        }
        false
    }
}
pub fn symbol_locator(query: &PythonText) -> Option<SymbolLocator> {
    let mut value = query.clone().trimmed();
    if let Some(m) = p::find(
        r"^(?:locate|find|show|open|busca|buscá|localiza|muestra|mostrame)\s+(?:(?:the\s+)?(?:definition|declaration)\s+of\s+|(?:la\s+)?(?:definición|declaración)\s+(?:de|del)\s+)?",
        true,
        &value,
    ) {
        value = p::tail(&value, m.end);
    }
    value = strip_chars(&value, &[46, 63, 33], false, true).trimmed();
    if value.codepoints().first() == Some(&96) && value.codepoints().last() == Some(&96) {
        if value.codepoints().len() < 2 {
            return None;
        }
        value = p::slice(&value, 1, value.codepoints().len() - 1);
    }
    let m = p::full(
        r"(?P<namespace>[\w$][\w$./-]*)::(?P<qualname>[\w$]+(?:\.[\w$]+)*)",
        &value,
    )?;
    let namespace = m.named["namespace"].to_utf8()?;
    let qualname = m.named["qualname"].to_utf8()?;
    if namespace.split('/').any(|v| matches!(v, "" | "." | ".."))
        || namespace.contains("..")
        || namespace.ends_with('.')
        || !qualname
            .split('.')
            .all(|part| identifier(&part.replace('$', "_")))
    {
        return None;
    }
    Some(SymbolLocator {
        namespace,
        qualname,
    })
}
pub fn module_name(path: &str) -> Option<String> {
    let mut parts: Vec<String> = path
        .split('/')
        .filter(|v| !v.is_empty() && *v != ".")
        .map(str::to_owned)
        .collect();
    if path.starts_with('/') {
        parts.insert(
            0,
            if path.starts_with("//") && !path.starts_with("///") {
                "//".into()
            } else {
                "/".into()
            },
        );
    }
    let name = parts.last()?;
    let dot = name.rfind('.')?;
    if dot == 0 {
        return None;
    }
    let suffix = &name[dot..];
    if !matches!(
        suffix,
        ".py" | ".pyi" | ".js" | ".jsx" | ".mjs" | ".cjs" | ".ts" | ".tsx" | ".mts" | ".cts"
    ) {
        return None;
    }
    let python = matches!(suffix, ".py" | ".pyi");
    if parts[..parts.len() - 1]
        .iter()
        .any(|v| v.starts_with('.') || matches!(v.as_str(), "node_modules" | "vendor"))
    {
        return None;
    }
    let stem = name[..dot].to_owned();
    *parts.last_mut()? = stem;
    if parts.last().is_some_and(|s| s == "__init__") {
        parts.pop();
    }
    if parts.first().is_some_and(|s| s == "src") {
        parts.remove(0);
    }
    if python && !parts.iter().all(|p| identifier(p)) {
        return None;
    }
    Some(parts.join(if python { "." } else { "/" }))
}
