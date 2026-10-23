//! C++ declarations coordinate lexical ownership, declarators and header recovery.
use crate::{
    ParseError, SyntaxNode, SyntaxTree,
    c::conditional,
    cpp_declarator::{CallableName, callable},
    helpers::{block_doc, child_text, line_doc, qualified, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
};

#[derive(Default)]
struct Scope {
    qualname: String,
    namespace: String,
    in_type: bool,
}
impl Scope {
    fn qualify(&self, name: &str) -> String {
        if name.is_empty() {
            self.qualname.clone()
        } else {
            qualified(&self.qualname, name)
        }
    }
    fn callable_kind(&self, name: &CallableName, owner: &str) -> &'static str {
        let member = self.in_type || !name.qualifier.is_empty();
        if name.destructor {
            "destructor"
        } else if member
            && !owner.is_empty()
            && owner.rsplit('.').next() == Some(name.name.as_str())
        {
            "constructor"
        } else if member {
            "method"
        } else {
            "function"
        }
    }
}
fn type_kind(kind: &str) -> Option<&'static str> {
    match kind {
        "class_specifier" => Some("class"),
        "struct_specifier" => Some("struct"),
        "union_specifier" => Some("union"),
        _ => None,
    }
}
fn documentation(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    block_doc(node, source).or_else(|| line_doc(node, source, "///"))
}
fn namespace_name(node: SyntaxNode<'_>, source: &[u8]) -> String {
    child_text(node, "name", source)
        .unwrap_or_default()
        .replace("::", ".")
}

pub(crate) fn has_syntax(root: SyntaxNode<'_>) -> bool {
    let mut pending = vec![root];
    while let Some(node) = pending.pop() {
        if matches!(
            node.kind(),
            "class_specifier"
                | "namespace_definition"
                | "namespace_alias_definition"
                | "template_declaration"
                | "alias_declaration"
                | "using_declaration"
                | "friend_declaration"
                | "access_specifier"
                | "reference_declarator"
                | "qualified_identifier"
                | "scoped_type_identifier"
                | "lambda_expression"
                | "new_expression"
                | "delete_expression"
        ) {
            return true;
        }
        pending.extend(node.named_children());
    }
    false
}
pub(crate) fn extract<F>(
    source: &[u8],
    root: SyntaxNode<'_>,
    reparse: F,
) -> Result<ParsedFile, ParseError>
where
    F: Fn(&[u8]) -> Result<SyntaxTree, ParseError>,
{
    let mut extraction = Extraction {
        source,
        reparse,
        out: ParsedFile::default(),
    };
    extraction.walk(root, &Scope::default())?;
    Ok(extraction.out)
}
struct Extraction<'a, F> {
    source: &'a [u8],
    reparse: F,
    out: ParsedFile,
}
impl<F: Fn(&[u8]) -> Result<SyntaxTree, ParseError>> Extraction<'_, F> {
    fn walk(&mut self, node: SyntaxNode<'_>, scope: &Scope) -> Result<(), ParseError> {
        for child in node.children() {
            self.dispatch(child, scope)?;
        }
        Ok(())
    }
    fn dispatch(&mut self, node: SyntaxNode<'_>, scope: &Scope) -> Result<(), ParseError> {
        match node.kind() {
            kind if conditional(kind) => self.walk(node, scope)?,
            "preproc_include" => self.include(node),
            "function_definition" => self.function(node, scope, node)?,
            "declaration" | "field_declaration" => self.declaration(node, scope, node)?,
            kind if type_kind(kind).is_some() => {
                self.declared_type(node, type_kind(kind).expect("matched type"), scope, node)?
            }
            "enum_specifier" => self.simple(node, "enum", scope, node),
            "namespace_definition" => {
                let name = scope.qualify(&namespace_name(node, self.source));
                if let Some(body) = node.field("body") {
                    self.walk(
                        body,
                        &Scope {
                            qualname: name.clone(),
                            namespace: name,
                            in_type: false,
                        },
                    )?;
                }
            }
            "friend_declaration" => self.walk(
                node,
                &Scope {
                    qualname: scope.namespace.clone(),
                    namespace: scope.namespace.clone(),
                    in_type: false,
                },
            )?,
            "template_declaration" => self.template(node, scope)?,
            "linkage_specification" => {
                if let Some(body) = node.field("body") {
                    self.walk(body, scope)?;
                }
            }
            "alias_declaration" | "type_definition" => self.typedef(node, scope),
            _ => {}
        }
        Ok(())
    }
    fn template(&mut self, node: SyntaxNode<'_>, scope: &Scope) -> Result<(), ParseError> {
        for child in node.children() {
            match child.kind() {
                "function_definition" => self.function(child, scope, node)?,
                "declaration" | "field_declaration" => self.declaration(child, scope, node)?,
                kind if type_kind(kind).is_some() => {
                    self.declared_type(child, type_kind(kind).expect("matched type"), scope, node)?
                }
                _ => self.dispatch(child, scope)?,
            }
        }
        Ok(())
    }
    fn function(
        &mut self,
        node: SyntaxNode<'_>,
        scope: &Scope,
        doc: SyntaxNode<'_>,
    ) -> Result<(), ParseError> {
        let Some(info) = callable(node.field("declarator"), self.source) else {
            return self.recover_namespace(node, scope);
        };
        let owner = self.append_callable(node, scope, info, doc);
        if let Some(body) = node.field("body") {
            self.local_types(
                body,
                &Scope {
                    qualname: owner,
                    namespace: scope.namespace.clone(),
                    in_type: false,
                },
            )?;
        }
        Ok(())
    }
    fn local_types(&mut self, node: SyntaxNode<'_>, scope: &Scope) -> Result<(), ParseError> {
        let mut pending = vec![node];
        while let Some(current) = pending.pop() {
            if let Some(kind) = type_kind(current.kind()) {
                self.declared_type(current, kind, scope, current)?;
            } else if !matches!(current.kind(), "function_definition" | "lambda_expression") {
                let mut children = current.named_children();
                children.reverse();
                pending.extend(children);
            }
        }
        Ok(())
    }
    fn recover_namespace(&mut self, node: SyntaxNode<'_>, scope: &Scope) -> Result<(), ParseError> {
        let Some(body) = node.field("body") else {
            return Ok(());
        };
        let Some(keyword) = node
            .named_children()
            .into_iter()
            .find(|n| n.start_byte() < body.start_byte() && text(*n, self.source) == "namespace")
        else {
            return Ok(());
        };
        let mut header = self.source[keyword.start_byte()..body.start_byte()].to_vec();
        header.extend_from_slice(b"{}");
        let recovered = (self.reparse)(&header)?;
        let root = recovered.root();
        let children = root.named_children();
        if root.has_error() || children.len() != 1 || children[0].kind() != "namespace_definition" {
            return Ok(());
        }
        let name = scope.qualify(&namespace_name(children[0], &header));
        self.walk(
            body,
            &Scope {
                qualname: name.clone(),
                namespace: name,
                in_type: false,
            },
        )
    }
    fn declaration(
        &mut self,
        node: SyntaxNode<'_>,
        scope: &Scope,
        doc: SyntaxNode<'_>,
    ) -> Result<(), ParseError> {
        if let Some(declared) = node.field("type")
            && let Some(kind) = type_kind(declared.kind())
        {
            self.declared_type(declared, kind, scope, doc)?;
        }
        if let Some(info) = callable(node.field("declarator"), self.source) {
            self.append_callable(node, scope, info, doc);
        }
        Ok(())
    }
    fn append_callable(
        &mut self,
        node: SyntaxNode<'_>,
        scope: &Scope,
        info: CallableName,
        doc: SyntaxNode<'_>,
    ) -> String {
        let owner = if info.qualifier.is_empty() {
            scope.qualname.clone()
        } else {
            scope.qualify(&info.qualifier)
        };
        let mut item = symbol(
            node,
            scope.callable_kind(&info, &owner),
            info.name,
            &owner,
            documentation(doc, self.source),
        );
        item.line_start = doc.start_point()[0] + 1;
        let owner = if item.qualname.is_empty() {
            item.name.clone()
        } else {
            item.qualname.clone()
        };
        self.out.symbols.push(item);
        owner
    }
    fn declared_type(
        &mut self,
        node: SyntaxNode<'_>,
        kind: &str,
        scope: &Scope,
        doc: SyntaxNode<'_>,
    ) -> Result<(), ParseError> {
        let Some(name) = child_text(node, "name", self.source).filter(|n| !n.is_empty()) else {
            return Ok(());
        };
        let owner = scope.qualify(&name);
        self.simple_named(node, kind, scope, doc, name);
        if let Some(body) = node.field("body") {
            let scope = Scope {
                qualname: owner,
                namespace: scope.namespace.clone(),
                in_type: true,
            };
            for member in body.children() {
                self.dispatch(member, &scope)?;
            }
        }
        Ok(())
    }
    fn simple(&mut self, node: SyntaxNode<'_>, kind: &str, scope: &Scope, doc: SyntaxNode<'_>) {
        if let Some(name) = child_text(node, "name", self.source).filter(|n| !n.is_empty()) {
            self.simple_named(node, kind, scope, doc, name);
        }
    }
    fn simple_named(
        &mut self,
        node: SyntaxNode<'_>,
        kind: &str,
        scope: &Scope,
        doc: SyntaxNode<'_>,
        name: String,
    ) {
        let mut item = symbol(
            node,
            kind,
            name,
            &scope.qualname,
            documentation(doc, self.source),
        );
        item.line_start = doc.start_point()[0] + 1;
        self.out.symbols.push(item);
    }
    fn typedef(&mut self, node: SyntaxNode<'_>, scope: &Scope) {
        let name = if node.kind() == "alias_declaration" {
            node.named_children()
                .into_iter()
                .find(|n| n.kind() == "type_identifier")
                .map(|n| text(n, self.source))
        } else {
            child_text(node, "declarator", self.source)
        };
        if let Some(name) = name.filter(|n| !n.is_empty()) {
            self.simple_named(node, "typedef", scope, node, name);
        }
    }
    fn include(&mut self, node: SyntaxNode<'_>) {
        for child in node.named_children() {
            let module = match child.kind() {
                "system_lib_string" => {
                    Some(trim(text(child, self.source).trim_matches(['<', '>'])).to_owned())
                }
                "string_literal" => child
                    .named_children()
                    .into_iter()
                    .find(|n| n.kind() == "string_content")
                    .map(|n| text(n, self.source))
                    .filter(|s| !s.is_empty())
                    .map(|s| format!("\"{s}\"")),
                _ => continue,
            };
            if let Some(module) = module.filter(|n| !n.is_empty()) {
                self.out.imports.push(ParsedImport {
                    module,
                    line: node.start_point()[0] + 1,
                });
            }
            return;
        }
    }
}
