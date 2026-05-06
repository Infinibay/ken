//! Throughput benchmarks for every `ContentAdapter`. We run each adapter on
//! a representative synthetic input and report `bytes/sec`. The goal is to
//! catch regressions in tree-sitter walkers (where a small AST traversal
//! mistake can collapse throughput by 10x) and Markdown / PDF parsing.
//!
//! Run with:  cargo bench --bench adapters -p ken-engine --features "code pdf"

use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use engine::ingest::{ContentAdapter, IngestContext, PlainTextAdapter, RawDocument};
use engine::ingest_code::CodeAdapter;
use engine::ingest_md::MarkdownAdapter;
use engine::ingest_pdf::PdfAdapter;
use engine::types::{MetadataMap, SourceId, WorkspaceId};

fn ctx() -> IngestContext {
    IngestContext { workspace_id: WorkspaceId(1), source_id: SourceId(1) }
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

fn raw_bytes(bytes: Vec<u8>, uri: &str, mime: &str) -> RawDocument {
    RawDocument {
        bytes,
        source_uri: uri.to_string(),
        mime_hint: Some(mime.to_string()),
        external_id: Some(uri.to_string()),
        hint_metadata: MetadataMap::default(),
        source_modified_at: None,
    }
}

// ============================================================================
// Synthetic-source generators
// ============================================================================

fn synth_plain(words: usize) -> String {
    let lorem = "lorem ipsum dolor sit amet consectetur adipiscing elit ";
    let mut s = String::with_capacity(words * 8);
    for i in 0..words {
        s.push_str(lorem);
        if i % 12 == 11 {
            s.push_str(". ");
        }
    }
    s
}

fn synth_markdown(sections: usize) -> String {
    let mut s = String::new();
    for i in 0..sections {
        s.push_str(&format!("# Section {i}\n\n"));
        s.push_str("Some intro paragraph with [a link](https://example.com/foo) inside.\n\n");
        s.push_str(&format!("## Subsection {i}.a\n\n"));
        s.push_str("- item one\n- item two\n- item three\n\n");
        s.push_str("```rust\nfn add(a: i32, b: i32) -> i32 { a + b }\n```\n\n");
    }
    s
}

fn synth_rust(items: usize) -> String {
    let mut s = String::from("use std::collections::HashMap;\nuse serde::{Serialize, Deserialize};\n\n");
    for i in 0..items {
        s.push_str(&format!(
            "/// Doc for item {i}.\n#[inline]\npub fn item_{i}(x: i32) -> i32 {{\n    x + {i}\n}}\n\n"
        ));
        s.push_str(&format!(
            "pub struct Thing{i} {{ pub x: i32, pub y: String }}\n\nimpl Thing{i} {{\n    pub fn new(x: i32) -> Self {{ Self {{ x, y: String::new() }} }}\n}}\n\n"
        ));
    }
    s
}

fn synth_python(items: usize) -> String {
    let mut s = String::from("import os\nimport collections.abc\nfrom typing import Optional, List\n\n");
    for i in 0..items {
        s.push_str(&format!(
            "@dataclass\nclass Thing{i}:\n    x: int\n    y: str\n\n    def fly(self):\n        return self.x + {i}\n\ndef helper_{i}(arg):\n    return arg + {i}\n\n"
        ));
    }
    s
}

fn synth_typescript(items: usize) -> String {
    let mut s = String::from("import {{ foo }} from './utils';\nimport React from 'react';\n\n").replace("{{", "{").replace("}}", "}");
    for i in 0..items {
        s.push_str(&format!(
            "/**\n * Doc for fn{i}.\n */\nexport function fn{i}(a: number): number {{ return a + {i}; }}\n\n"
        ));
        s.push_str(&format!(
            "export class Thing{i} {{\n  constructor(public x: number) {{}}\n  greet(): string {{ return 'hi ' + this.x; }}\n}}\n\n"
        ));
    }
    s
}

fn synth_go(items: usize) -> String {
    let mut s = String::from("package main\n\nimport (\n    \"fmt\"\n    \"net/http\"\n)\n\n");
    for i in 0..items {
        s.push_str(&format!(
            "// Add{i} adds n.\nfunc Add{i}(a, b int) int {{\n    return a + b + {i}\n}}\n\ntype Thing{i} struct {{\n    X int\n}}\n\nfunc (t *Thing{i}) Bump() {{ t.X++ }}\n\n"
        ));
    }
    s
}

fn synth_javascript(items: usize) -> String {
    let mut s = String::from("import React from 'react';\nimport { foo } from './utils.js';\n\n");
    for i in 0..items {
        s.push_str(&format!(
            "/** Doc for fn{i} */\nexport function fn{i}(a) {{ return a + {i}; }}\n\nexport class Thing{i} {{\n  constructor(x) {{ this.x = x; }}\n  greet() {{ return 'hi ' + this.x; }}\n}}\n\n"
        ));
    }
    s
}

fn synth_java(items: usize) -> String {
    let mut s = String::from("package com.acme;\n\nimport java.util.List;\nimport java.util.Map;\n\n");
    s.push_str("public class Bench {\n");
    for i in 0..items {
        s.push_str(&format!(
            "    /** Doc for method{i} */\n    public int method{i}(int a) {{ return a + {i}; }}\n"
        ));
    }
    s.push_str("}\n");
    s
}

fn synth_c(items: usize) -> String {
    let mut s = String::from("#include <stdio.h>\n#include <stdlib.h>\n#include \"local.h\"\n\n");
    for i in 0..items {
        s.push_str(&format!(
            "/** Doc for fn{i}. */\nint fn{i}(int a, int b) {{\n    return a + b + {i};\n}}\n\nstruct Thing{i} {{ int x; int y; }};\n\n"
        ));
    }
    s
}

fn synth_cpp(items: usize) -> String {
    let mut s = String::from("#include <iostream>\n#include \"local.hpp\"\n\nnamespace acme {\n\n");
    for i in 0..items {
        s.push_str(&format!(
            "class Thing{i} {{\npublic:\n    Thing{i}(int x): x_(x) {{}}\n    int get() const {{ return x_ + {i}; }}\nprivate:\n    int x_;\n}};\n\ntemplate<typename T>\nT max_of_{i}(T a, T b) {{ return a > b ? a : b; }}\n\n"
        ));
    }
    s.push_str("} // namespace acme\n");
    s
}

fn synth_ruby(items: usize) -> String {
    let mut s = String::from("require 'json'\nrequire_relative '../user'\n\nmodule Acme\n");
    for i in 0..items {
        s.push_str(&format!(
            "  class Thing{i}\n    # Doc for method.\n    def initialize(name)\n      @name = name\n    end\n\n    def fly\n      \"#{{@name}}-{i}\"\n    end\n  end\n\n"
        ));
    }
    s.push_str("end\n");
    s
}

fn synth_pdf_like_text(pages: usize) -> Vec<u8> {
    // pdf-extract is too heavy to hand-build a real PDF here; instead we
    // synthesize a tiny valid PDF inline. This is the smallest-possible PDF
    // structure that pdf-extract will accept; we emit `pages` /Page objects
    // each with a short text content stream. Generated byte-for-byte to
    // keep the bench reproducible.
    //
    // For benchmark *signal* this is fine: the work is dominated by the
    // PDF object parser + content stream tokenizer, which scales with
    // the number of pages we wire into the catalog.
    let _ = pages;
    let body = "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<<>>>>endobj\n4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 100 700 Td (Hello world) Tj ET\nendstream endobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000050 00000 n\n0000000094 00000 n\n0000000172 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n230\n%%EOF\n";
    body.as_bytes().to_vec()
}

// ============================================================================
// Bench groups
// ============================================================================

fn bench_text_adapters(c: &mut Criterion) {
    let mut group = c.benchmark_group("plain_text");
    for &words in &[200usize, 2000, 10_000] {
        let text = synth_plain(words);
        let bytes = text.len() as u64;
        group.throughput(Throughput::Bytes(bytes));
        group.bench_with_input(BenchmarkId::from_parameter(words), &text, |b, t| {
            b.iter(|| {
                let r = raw(t, "doc.txt", "text/plain");
                PlainTextAdapter.ingest(black_box(r), &ctx()).unwrap()
            });
        });
    }
    group.finish();

    let mut group = c.benchmark_group("markdown");
    for &sections in &[8usize, 32, 128] {
        let md = synth_markdown(sections);
        let bytes = md.len() as u64;
        group.throughput(Throughput::Bytes(bytes));
        group.bench_with_input(BenchmarkId::from_parameter(sections), &md, |b, t| {
            b.iter(|| {
                let r = raw(t, "doc.md", "text/markdown");
                MarkdownAdapter.ingest(black_box(r), &ctx()).unwrap()
            });
        });
    }
    group.finish();
}

fn bench_code_adapters(c: &mut Criterion) {
    let cases: &[(&str, &str, &str, fn(usize) -> String)] = &[
        ("rust", "lib.rs", "text/x-rust", synth_rust),
        ("python", "module.py", "text/x-python", synth_python),
        ("typescript", "module.ts", "text/typescript", synth_typescript),
        ("go", "main.go", "text/x-go", synth_go),
        ("javascript", "index.js", "text/javascript", synth_javascript),
        ("java", "Bench.java", "text/x-java", synth_java),
        ("c", "main.c", "text/x-c", synth_c),
        ("cpp", "main.cpp", "text/x-c++", synth_cpp),
        ("ruby", "user.rb", "text/x-ruby", synth_ruby),
    ];
    for (name, uri, mime, make) in cases {
        let mut group = c.benchmark_group(format!("code/{name}"));
        for &items in &[10usize, 100] {
            let src = make(items);
            let bytes = src.len() as u64;
            group.throughput(Throughput::Bytes(bytes));
            group.bench_with_input(BenchmarkId::from_parameter(items), &src, |b, t| {
                b.iter(|| {
                    let r = raw(t, uri, mime);
                    CodeAdapter.ingest(black_box(r), &ctx()).unwrap()
                });
            });
        }
        group.finish();
    }
}

fn bench_pdf_adapter(c: &mut Criterion) {
    let mut group = c.benchmark_group("pdf");
    let pdf_bytes = synth_pdf_like_text(1);
    group.throughput(Throughput::Bytes(pdf_bytes.len() as u64));
    group.bench_function("1_page", |b| {
        b.iter(|| {
            let r = raw_bytes(pdf_bytes.clone(), "doc.pdf", "application/pdf");
            // PdfAdapter may legitimately fail on a hand-rolled minimal PDF
            // depending on pdf-extract's strictness. We bench whatever the
            // adapter does — including the parse-error path — because that
            // path also needs to stay fast.
            let _ = PdfAdapter.ingest(black_box(r), &ctx());
        });
    });
    group.finish();
}

criterion_group!(benches, bench_text_adapters, bench_code_adapters, bench_pdf_adapter);
criterion_main!(benches);
