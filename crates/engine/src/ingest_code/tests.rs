//! Adapter-level tests covering all supported languages.

use super::*;
use crate::ingest::{ContentAdapter, EdgeEndpoint, IngestError, MimeHint, RawDocument};
use crate::types::{ChunkKind, ChunkPosition, EdgeKind, Language as Lang, MetadataMap};

fn ctx() -> crate::ingest::IngestContext {
    crate::ingest::IngestContext {
        workspace_id: crate::types::WorkspaceId(1),
        source_id: crate::types::SourceId(1),
    }
}

fn raw(text: &str, uri: &str, mime: &str) -> RawDocument {
    RawDocument {
        bytes: text.as_bytes().to_vec(),
        source_uri: uri.to_string(),
        mime_hint: Some(mime.to_string()),
        external_id: Some(uri.to_string()),
        hint_metadata: MetadataMap::default(),
        source_modified_at: None,
    }
}

fn ingest_rust(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "src/lib.rs", "text/x-rust"), &ctx())
        .unwrap()
}

fn ingest_py(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "module.py", "text/x-python"), &ctx())
        .unwrap()
}

fn ingest_ts(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "src/mod.ts", "text/typescript"), &ctx())
        .unwrap()
}

fn ingest_tsx(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "src/Component.tsx", "text/tsx"), &ctx())
        .unwrap()
}

fn ingest_go(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "main.go", "text/x-go"), &ctx())
        .unwrap()
}

fn ingest_js(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "src/index.js", "text/javascript"), &ctx())
        .unwrap()
}

fn ingest_java(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "User.java", "text/x-java"), &ctx())
        .unwrap()
}

fn ingest_c(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "src/main.c", "text/x-c"), &ctx())
        .unwrap()
}

fn ingest_cpp(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "src/main.cpp", "text/x-c++"), &ctx())
        .unwrap()
}

fn ingest_ruby(text: &str) -> crate::ingest::IngestOutput {
    CodeAdapter
        .ingest(raw(text, "user.rb", "text/x-ruby"), &ctx())
        .unwrap()
}

fn qns(out: &crate::ingest::IngestOutput) -> Vec<&str> {
    out.chunks
        .iter()
        .filter_map(|c| match &c.position {
            ChunkPosition::SymbolRange { qualified_name, .. } => Some(qualified_name.as_str()),
            _ => None,
        })
        .collect()
}

fn import_targets(out: &crate::ingest::IngestOutput) -> Vec<&str> {
    out.edges
        .iter()
        .filter_map(|e| match &e.to {
            EdgeEndpoint::External(s) => Some(s.as_str()),
            _ => None,
        })
        .collect()
}

// ============================================================================
// Common
// ============================================================================

#[test]
fn accepts_all_supported_languages() {
    let a = CodeAdapter;
    // Rust
    assert!(a.accepts(&MimeHint::from_mime("text/x-rust")));
    assert!(a.accepts(&MimeHint::from_uri("lib.rs")));
    // Python
    assert!(a.accepts(&MimeHint::from_mime("text/x-python")));
    assert!(a.accepts(&MimeHint::from_uri("script.py")));
    assert!(a.accepts(&MimeHint::from_uri("types.pyi")));
    // TypeScript / TSX
    assert!(a.accepts(&MimeHint::from_mime("text/typescript")));
    assert!(a.accepts(&MimeHint::from_uri("module.ts")));
    assert!(a.accepts(&MimeHint::from_uri("config.mts")));
    assert!(a.accepts(&MimeHint::from_uri("legacy.cts")));
    assert!(a.accepts(&MimeHint::from_uri("Component.tsx")));
    // Go
    assert!(a.accepts(&MimeHint::from_mime("text/x-go")));
    assert!(a.accepts(&MimeHint::from_uri("main.go")));
    // JavaScript
    assert!(a.accepts(&MimeHint::from_mime("text/javascript")));
    assert!(a.accepts(&MimeHint::from_mime("application/javascript")));
    assert!(a.accepts(&MimeHint::from_uri("index.js")));
    assert!(a.accepts(&MimeHint::from_uri("module.mjs")));
    assert!(a.accepts(&MimeHint::from_uri("legacy.cjs")));
    assert!(a.accepts(&MimeHint::from_uri("App.jsx")));
    // Java
    assert!(a.accepts(&MimeHint::from_mime("text/x-java")));
    assert!(a.accepts(&MimeHint::from_uri("User.java")));
    // C / C++
    assert!(a.accepts(&MimeHint::from_uri("main.c")));
    assert!(a.accepts(&MimeHint::from_uri("header.h")));
    assert!(a.accepts(&MimeHint::from_uri("main.cpp")));
    assert!(a.accepts(&MimeHint::from_uri("main.cc")));
    assert!(a.accepts(&MimeHint::from_uri("Header.hpp")));
    // Ruby
    assert!(a.accepts(&MimeHint::from_mime("text/x-ruby")));
    assert!(a.accepts(&MimeHint::from_uri("script.rb")));
    assert!(a.accepts(&MimeHint::from_uri("Rakefile.rake")));
    // Rejected
    assert!(!a.accepts(&MimeHint::from_uri("notes.md")));
    assert!(!a.accepts(&MimeHint::from_mime("text/plain")));
    assert!(!a.accepts(&MimeHint::default()));
}

#[test]
fn invalid_utf8_returns_decode_error() {
    let r = RawDocument {
        bytes: vec![0xFF, 0xFE],
        source_uri: "bad.rs".into(),
        mime_hint: Some("text/x-rust".into()),
        external_id: None,
        hint_metadata: MetadataMap::default(),
        source_modified_at: None,
    };
    let res = CodeAdapter.ingest(r, &ctx());
    assert!(matches!(res, Err(IngestError::Decode(_))));
}

#[test]
fn relation_kinds_advertise_imports_and_defines() {
    assert_eq!(
        CodeAdapter.relation_kinds(),
        &[EdgeKind::Imports, EdgeKind::Defines],
    );
}

// ============================================================================
// Rust
// ============================================================================

#[test]
fn rust_extracts_top_level_function() {
    let out = ingest_rust("pub fn add(a: i32, b: i32) -> i32 { a + b }");
    assert_eq!(out.chunks.len(), 1);
    assert_eq!(out.chunks[0].kind, ChunkKind::CodeSymbol);
    match &out.chunks[0].position {
        ChunkPosition::SymbolRange { qualified_name, line_start, line_end } => {
            assert_eq!(qualified_name, "add");
            assert_eq!(*line_start, 1);
            assert_eq!(*line_end, 1);
        }
        _ => panic!(),
    }
    assert!(out.chunks[0].metadata.tags.iter().any(|t| t == "fn"));
}

#[test]
fn rust_extracts_struct_enum_trait_typealias() {
    let src = "struct A { x: i32 }\n\nenum B { Y, Z }\n\ntrait C { fn d(&self); }\n\ntype E = String;";
    let out = ingest_rust(src);
    let names = qns(&out);
    assert!(names.contains(&"A"), "got {names:?}");
    assert!(names.contains(&"B"));
    assert!(names.contains(&"C"));
    assert!(names.contains(&"E"));
}

#[test]
fn rust_impl_methods_become_separate_chunks_with_qualified_names() {
    let src = "struct User { name: String }\n\nimpl User {\n    pub fn validate(&self) -> bool { !self.name.is_empty() }\n    fn private(&self) {}\n}";
    let out = ingest_rust(src);
    let names = qns(&out);
    assert!(names.contains(&"User"), "got {names:?}");
    assert!(names.contains(&"User::validate"));
    assert!(names.contains(&"User::private"));
    let validate = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "User::validate"))
        .unwrap();
    assert!(validate.metadata.tags.iter().any(|t| t == "method"));
}

#[test]
fn rust_doc_comments_and_attributes_are_included_in_chunk() {
    let src = "/// Adds two integers.\n#[inline]\npub fn add(a: i32, b: i32) -> i32 { a + b }";
    let out = ingest_rust(src);
    assert_eq!(out.chunks.len(), 1);
    assert!(out.chunks[0].text.contains("Adds two integers"));
    assert!(out.chunks[0].text.contains("#[inline]"));
    match &out.chunks[0].position {
        ChunkPosition::SymbolRange { line_start, .. } => assert_eq!(*line_start, 1),
        _ => panic!(),
    }
}

#[test]
fn rust_use_declarations_become_imports_edges() {
    let src = "use std::collections::HashMap;\nuse serde::{Serialize, Deserialize};\n\nfn x() {}";
    let out = ingest_rust(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"rust:std::collections::HashMap"), "got {targets:?}");
    assert!(targets.contains(&"rust:serde::Serialize"));
    assert!(targets.contains(&"rust:serde::Deserialize"));
}

#[test]
fn rust_use_wildcard_dropped() {
    let out = ingest_rust("use std::io::*;\n\nfn x() {}");
    assert!(out.edges.is_empty());
}

#[test]
fn rust_use_self_in_brace_keeps_module() {
    let out = ingest_rust("use std::io::{self, Read};\n\nfn x() {}");
    let targets = import_targets(&out);
    assert!(targets.contains(&"rust:std::io"), "got {targets:?}");
    assert!(targets.contains(&"rust:std::io::Read"));
}

#[test]
fn rust_nested_module_qualifies_inner_symbols() {
    let out = ingest_rust("mod auth {\n    pub fn login() {}\n}\n");
    let names = qns(&out);
    assert!(names.contains(&"auth::login"), "got {names:?}");
}

#[test]
fn rust_metadata_records_language() {
    let out = ingest_rust("fn x() {}");
    assert_eq!(out.document.metadata.language, Some(Lang::Rust));
    assert!(out.chunks.iter().all(|c| c.metadata.language == Some(Lang::Rust)));
}

#[test]
fn rust_empty_source_yields_no_chunks() {
    let out = ingest_rust("");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}

// ============================================================================
// Python
// ============================================================================

#[test]
fn py_extracts_top_level_function() {
    let src = "def add(a, b):\n    return a + b\n";
    let out = ingest_py(src);
    assert_eq!(out.chunks.len(), 1);
    assert_eq!(out.chunks[0].kind, ChunkKind::CodeSymbol);
    let names = qns(&out);
    assert!(names.contains(&"add"));
    assert_eq!(out.document.metadata.language, Some(Lang::Python));
}

#[test]
fn py_extracts_class_with_methods() {
    let src = "class User:\n    def __init__(self, name):\n        self.name = name\n\n    def validate(self):\n        return bool(self.name)\n";
    let out = ingest_py(src);
    let names = qns(&out);
    // Class itself + 2 methods.
    assert!(names.contains(&"User"), "got {names:?}");
    assert!(names.contains(&"User.__init__"));
    assert!(names.contains(&"User.validate"));
    let validate = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "User.validate"))
        .unwrap();
    assert!(validate.metadata.tags.iter().any(|t| t == "method"));
}

#[test]
fn py_decorators_are_included_in_chunk() {
    let src = "@dataclass\n@frozen\ndef build():\n    return 1\n";
    let out = ingest_py(src);
    assert_eq!(out.chunks.len(), 1);
    assert!(out.chunks[0].text.contains("@dataclass"));
    assert!(out.chunks[0].text.contains("@frozen"));
    // Line range starts at the first decorator (line 1).
    match &out.chunks[0].position {
        ChunkPosition::SymbolRange { line_start, qualified_name, .. } => {
            assert_eq!(*line_start, 1);
            assert_eq!(qualified_name, "build");
        }
        _ => panic!(),
    }
}

#[test]
fn py_decorated_class_emits_chunk_and_walks_methods() {
    let src = "@dataclass\nclass Point:\n    x: int\n    y: int\n\n    def shift(self, dx, dy):\n        return Point(self.x + dx, self.y + dy)\n";
    let out = ingest_py(src);
    let names = qns(&out);
    assert!(names.contains(&"Point"), "got {names:?}");
    assert!(names.contains(&"Point.shift"));
}

#[test]
fn py_simple_imports() {
    let src = "import os\nimport collections.abc\nimport numpy as np\n\ndef f(): pass\n";
    let out = ingest_py(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"python:os"), "got {targets:?}");
    assert!(targets.contains(&"python:collections.abc"));
    assert!(targets.contains(&"python:numpy"));
}

#[test]
fn py_from_imports_flatten_with_module_prefix() {
    let src = "from collections import OrderedDict, deque\nfrom typing import Optional, List\n\ndef f(): pass\n";
    let out = ingest_py(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"python:collections.OrderedDict"), "got {targets:?}");
    assert!(targets.contains(&"python:collections.deque"));
    assert!(targets.contains(&"python:typing.Optional"));
    assert!(targets.contains(&"python:typing.List"));
}

#[test]
fn py_wildcard_import_dropped() {
    let src = "from os.path import *\n\ndef f(): pass\n";
    let out = ingest_py(src);
    assert!(out.edges.is_empty(), "wildcard should be skipped");
}

#[test]
fn py_aliased_imports_use_real_name() {
    let src = "from typing import List as L\nimport pandas as pd\n";
    let out = ingest_py(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"python:typing.List"), "got {targets:?}");
    assert!(targets.contains(&"python:pandas"));
}

#[test]
fn py_metadata_records_language() {
    let out = ingest_py("def x(): pass");
    assert_eq!(out.document.metadata.language, Some(Lang::Python));
    assert!(out.chunks.iter().all(|c| c.metadata.language == Some(Lang::Python)));
}

#[test]
fn py_empty_source_yields_no_chunks() {
    let out = ingest_py("");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}

// ============================================================================
// TypeScript / TSX
// ============================================================================

#[test]
fn ts_extracts_top_level_function() {
    let src = "export function add(a: number, b: number): number {\n  return a + b;\n}\n";
    let out = ingest_ts(src);
    let names = qns(&out);
    assert!(names.contains(&"add"), "got {names:?}");
    assert_eq!(out.document.metadata.language, Some(Lang::TypeScript));
    // Chunk text should include the `export` keyword.
    let add = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "add"))
        .unwrap();
    assert!(add.text.starts_with("export"), "got start: {:?}", &add.text[..40.min(add.text.len())]);
}

#[test]
fn ts_extracts_class_with_methods() {
    let src = "export class User {\n  constructor(public name: string) {}\n\n  validate(): boolean {\n    return this.name.length > 0;\n  }\n}\n";
    let out = ingest_ts(src);
    let names = qns(&out);
    assert!(names.contains(&"User"), "got {names:?}");
    assert!(names.contains(&"User.validate"));
    let validate = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "User.validate"))
        .unwrap();
    assert!(validate.metadata.tags.iter().any(|t| t == "method"));
}

#[test]
fn ts_extracts_interface_and_type_alias_and_enum() {
    let src = "export interface Foo { x: number; }\n\nexport type Bar = string | number;\n\nexport enum Baz { A, B }\n";
    let out = ingest_ts(src);
    let names = qns(&out);
    assert!(names.contains(&"Foo"), "got {names:?}");
    assert!(names.contains(&"Bar"));
    assert!(names.contains(&"Baz"));
    let foo = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "Foo"))
        .unwrap();
    assert!(foo.metadata.tags.iter().any(|t| t == "interface"));
}

#[test]
fn ts_relative_imports_use_ts_namespace() {
    let src = "import { foo } from './utils';\nimport bar from \"../shared/bar\";\n\nfunction x() {}\n";
    let out = ingest_ts(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"ts:./utils"), "got {targets:?}");
    assert!(targets.contains(&"ts:../shared/bar"));
}

#[test]
fn ts_bare_specifiers_use_npm_namespace() {
    let src = "import React from 'react';\nimport { z } from '@anthropic/sdk';\nimport 'side-effect';\n\nfunction x() {}\n";
    let out = ingest_ts(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"npm:react"), "got {targets:?}");
    assert!(targets.contains(&"npm:@anthropic/sdk"));
    assert!(targets.contains(&"npm:side-effect"));
}

#[test]
fn ts_jsdoc_is_attached_to_symbol() {
    let src = "/**\n * Adds two numbers.\n */\nexport function add(a: number, b: number): number {\n  return a + b;\n}\n";
    let out = ingest_ts(src);
    assert_eq!(out.chunks.len(), 1);
    assert!(out.chunks[0].text.contains("Adds two numbers"));
    match &out.chunks[0].position {
        ChunkPosition::SymbolRange { line_start, .. } => assert_eq!(*line_start, 1),
        _ => panic!(),
    }
}

#[test]
fn tsx_grammar_handles_jsx() {
    // A minimal TSX component with JSX in the body — TYPESCRIPT grammar
    // would fail to parse this; TSX accepts it.
    let src = "export function Hello({name}: {name: string}) {\n  return <div>hi {name}</div>;\n}\n";
    let out = ingest_tsx(src);
    let names = qns(&out);
    assert!(names.contains(&"Hello"), "got {names:?}");
}

#[test]
fn ts_metadata_records_language_typescript() {
    let out = ingest_ts("function x() {}");
    assert_eq!(out.document.metadata.language, Some(Lang::TypeScript));
    assert!(out.chunks.iter().all(|c| c.metadata.language == Some(Lang::TypeScript)));
}

#[test]
fn ts_empty_source_yields_no_chunks() {
    let out = ingest_ts("");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}

// ============================================================================
// Go
// ============================================================================

#[test]
fn go_extracts_top_level_function() {
    let src = "package main\n\nfunc add(a int, b int) int {\n    return a + b\n}\n";
    let out = ingest_go(src);
    let names = qns(&out);
    assert!(names.contains(&"add"), "got {names:?}");
    assert_eq!(out.document.metadata.language, Some(Lang::Go));
}

#[test]
fn go_method_qualified_with_receiver() {
    let src = "package main\n\ntype User struct{ Name string }\n\nfunc (u User) Validate() bool {\n    return u.Name != \"\"\n}\n\nfunc (u *User) Rename(n string) {\n    u.Name = n\n}\n";
    let out = ingest_go(src);
    let names = qns(&out);
    assert!(names.contains(&"User"), "got {names:?}");
    assert!(names.contains(&"User.Validate"));
    // Pointer receiver collapses to base type.
    assert!(names.contains(&"User.Rename"));
    let v = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "User.Validate"))
        .unwrap();
    assert!(v.metadata.tags.iter().any(|t| t == "method"));
}

#[test]
fn go_extracts_struct_interface_and_alias() {
    let src = "package x\n\ntype Foo struct { X int }\n\ntype Bar interface { Do() }\n\ntype Quux = string\n";
    let out = ingest_go(src);
    let names = qns(&out);
    assert!(names.contains(&"Foo"), "got {names:?}");
    assert!(names.contains(&"Bar"));
    assert!(names.contains(&"Quux"));
}

#[test]
fn go_doc_comments_attached_to_symbol() {
    let src = "package x\n\n// Add returns a + b.\n// It is a sample.\nfunc Add(a, b int) int {\n    return a + b\n}\n";
    let out = ingest_go(src);
    let add = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "Add"))
        .unwrap();
    assert!(add.text.contains("Add returns a + b."));
    assert!(add.text.contains("It is a sample."));
}

#[test]
fn go_imports_single_and_grouped() {
    let src = "package x\n\nimport \"fmt\"\n\nimport (\n    \"net/http\"\n    \"github.com/foo/bar\"\n)\n\nfunc f() {}\n";
    let out = ingest_go(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"go:fmt"), "got {targets:?}");
    assert!(targets.contains(&"go:net/http"));
    assert!(targets.contains(&"go:github.com/foo/bar"));
}

#[test]
fn go_empty_source_yields_no_chunks() {
    let out = ingest_go("package x\n");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}

// ============================================================================
// JavaScript
// ============================================================================

#[test]
fn js_extracts_function_and_class() {
    let src = "export function add(a, b) { return a + b; }\n\nclass User {\n  constructor(name) { this.name = name; }\n  greet() { return 'hi ' + this.name; }\n}\n";
    let out = ingest_js(src);
    let names = qns(&out);
    assert!(names.contains(&"add"), "got {names:?}");
    assert!(names.contains(&"User"));
    assert!(names.contains(&"User.greet"));
    assert_eq!(out.document.metadata.language, Some(Lang::JavaScript));
}

#[test]
fn js_relative_imports_use_js_namespace() {
    let src = "import { foo } from './utils.js';\nimport bar from '../shared/bar';\n\nfunction x() {}\n";
    let out = ingest_js(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"js:./utils.js"), "got {targets:?}");
    assert!(targets.contains(&"js:../shared/bar"));
}

#[test]
fn js_bare_specifiers_use_npm_namespace() {
    let src = "import React from 'react';\nimport { z } from '@anthropic/sdk';\n\nfunction x() {}\n";
    let out = ingest_js(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"npm:react"), "got {targets:?}");
    assert!(targets.contains(&"npm:@anthropic/sdk"));
}

#[test]
fn js_jsdoc_attached_to_symbol() {
    let src = "/**\n * Adds two numbers.\n */\nexport function add(a, b) { return a + b; }\n";
    let out = ingest_js(src);
    assert_eq!(out.chunks.len(), 1);
    assert!(out.chunks[0].text.contains("Adds two numbers"));
}

#[test]
fn js_empty_source_yields_no_chunks() {
    let out = ingest_js("");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}

// ============================================================================
// Java
// ============================================================================

#[test]
fn java_class_with_methods() {
    let src = "package com.acme;\n\npublic class User {\n    private String name;\n    public User(String name) { this.name = name; }\n    public boolean validate() { return name != null; }\n}\n";
    let out = ingest_java(src);
    let names = qns(&out);
    assert!(names.contains(&"User"), "got {names:?}");
    assert!(names.contains(&"User.User"));
    assert!(names.contains(&"User.validate"));
    assert_eq!(out.document.metadata.language, Some(Lang::Java));
    let v = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "User.validate"))
        .unwrap();
    assert!(v.metadata.tags.iter().any(|t| t == "method"));
}

#[test]
fn java_imports_and_package() {
    let src = "package com.acme;\n\nimport java.util.List;\nimport java.util.Map;\nimport java.util.*;\n\npublic class X {}\n";
    let out = ingest_java(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"java:com.acme"), "package missing in {targets:?}");
    assert!(targets.contains(&"java:java.util.List"));
    assert!(targets.contains(&"java:java.util.Map"));
    // Wildcard skipped.
    assert!(!targets.contains(&"java:java.util"));
}

#[test]
fn java_interface_enum_and_record() {
    let src = "interface Shape { double area(); }\n\nenum Status { OK, ERR }\n\nrecord Point(int x, int y) {}\n";
    let out = ingest_java(src);
    let names = qns(&out);
    assert!(names.contains(&"Shape"), "got {names:?}");
    assert!(names.contains(&"Status"));
    assert!(names.contains(&"Point"));
}

#[test]
fn java_empty_source_yields_no_chunks() {
    let out = ingest_java("");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}

// ============================================================================
// C / C++
// ============================================================================

#[test]
fn c_extracts_function_and_struct() {
    let src = "#include <stdio.h>\n\nstruct Point { int x; int y; };\n\nint add(int a, int b) {\n    return a + b;\n}\n";
    let out = ingest_c(src);
    let names = qns(&out);
    assert!(names.contains(&"Point"), "got {names:?}");
    assert!(names.contains(&"add"));
    assert_eq!(out.document.metadata.language, Some(Lang::C));
}

#[test]
fn c_includes_split_by_namespace() {
    let src = "#include <stdio.h>\n#include \"local.h\"\n\nint x(void) { return 0; }\n";
    let out = ingest_c(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"c-system:stdio.h"), "got {targets:?}");
    assert!(targets.contains(&"c:local.h"));
}

#[test]
fn cpp_class_with_method_and_namespace() {
    let src = "namespace acme {\n\nclass User {\npublic:\n    bool validate();\n};\n\nbool User::validate() { return true; }\n\n}\n";
    let out = ingest_cpp(src);
    let names = qns(&out);
    // Namespace pushed into scope.
    assert!(names.contains(&"acme::User"), "got {names:?}");
    assert_eq!(out.document.metadata.language, Some(Lang::Cpp));
}

#[test]
fn cpp_template_function_extracted() {
    let src = "template<typename T>\nT max_of(T a, T b) {\n    return a > b ? a : b;\n}\n";
    let out = ingest_cpp(src);
    let names = qns(&out);
    assert!(names.contains(&"max_of"), "got {names:?}");
}

#[test]
fn c_empty_source_yields_no_chunks() {
    let out = ingest_c("");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}

// ============================================================================
// Ruby
// ============================================================================

#[test]
fn ruby_class_and_method() {
    let src = "class User\n  def initialize(name)\n    @name = name\n  end\n\n  def validate\n    !@name.nil?\n  end\nend\n";
    let out = ingest_ruby(src);
    let names = qns(&out);
    assert!(names.contains(&"User"), "got {names:?}");
    assert!(names.contains(&"User.initialize"));
    assert!(names.contains(&"User.validate"));
    assert_eq!(out.document.metadata.language, Some(Lang::Ruby));
    let v = out
        .chunks
        .iter()
        .find(|c| matches!(&c.position, ChunkPosition::SymbolRange { qualified_name, .. } if qualified_name == "User.validate"))
        .unwrap();
    assert!(v.metadata.tags.iter().any(|t| t == "method"));
}

#[test]
fn ruby_module_namespacing() {
    let src = "module Acme\n  class User\n    def greet\n      'hi'\n    end\n  end\nend\n";
    let out = ingest_ruby(src);
    let names = qns(&out);
    assert!(names.contains(&"Acme"), "got {names:?}");
    assert!(names.contains(&"Acme::User"));
    assert!(names.contains(&"Acme::User.greet"));
}

#[test]
fn ruby_singleton_method() {
    let src = "class User\n  def self.build(name)\n    new(name)\n  end\nend\n";
    let out = ingest_ruby(src);
    let names = qns(&out);
    assert!(names.contains(&"User.self.build"), "got {names:?}");
}

#[test]
fn ruby_require_imports() {
    let src = "require 'json'\nrequire_relative '../user'\n\nclass X\nend\n";
    let out = ingest_ruby(src);
    let targets = import_targets(&out);
    assert!(targets.contains(&"ruby:json"), "got {targets:?}");
    assert!(targets.contains(&"ruby-rel:../user"));
}

#[test]
fn ruby_empty_source_yields_no_chunks() {
    let out = ingest_ruby("");
    assert!(out.chunks.is_empty());
    assert!(out.edges.is_empty());
}
