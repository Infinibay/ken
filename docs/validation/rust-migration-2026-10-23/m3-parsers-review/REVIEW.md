# Final whole-plan review

Reviewer: /root/m3_parsers_final_review, gpt-6-astra, high reasoning, fresh context.
Range:2e52412e..1841876297083946a9ff63c36f39910fe0717934. Read-only; no subagents or checkout edits.

## Strengths

- Clear responsibilities: grammar catalog, lifetime-safe syntax views, registry, language extractors, and shared scope rules.
- Native grammar leases outlive trees; parsers are independent per operation.
- Evidence replay with VERIFY.py --current passes: both platforms,239inputs,215syntax shapes, preserved original files.
- Additional differential testing covered1,950mutated corpus inputs and252Python literal variants.

## Critical

None.

## Important

1. Preserve strict UTF-8 failures when extracting annotations (scopes.rs:188).
   annotations() uses lossy text(), whereas original annotations_for_node decodes strictly.
   parse_rust_file(b'#[doc = "\xff"]\nfn f() {}\n', 'x.rs') raises UnicodeDecodeError in original;
   native returns successful metadata with replacement characters. Same for an enclosing module attribute.
   Use strict decoding in the shared annotation owner and propagate errors. Test direct/inherited attributes;
   retain replacement decoding for fields where the original uses it.
2. Preserve valid Python strings containing surrogate escapes (python_literal.rs:69;model.rs:23).
   `def f():\n    "Useful documentation \\ud800 end"\n    pass\n` gives complete original scope documentation,
   including the surrogate point; native returns null because py_literal rejects it and .ok()? discards it.
   Low surrogates and \\U0000D800 reproduce. Preserve Python code points through decoding and serialization;
   ordinary Rust String cannot represent this. Test high/low surrogates, surrounding text and escaped pairs.

## Minor

None.

## Ledger rulings

- Task2 literal ownership/Unicode pinning: sound separation, incomplete for surrogate points as above.
- Task2 evidence reuse: justified by unchanged grammar inputs.
- Task3 symbol identity: indices preserve inspected identity/ordering; callable strict decoding correct,
  shared annotation decoding is the separate gap.
- Task4 Unicode categories/C++fallback: justified and locally owned.
- Task5 PHP identity: first-name selection preserves observed behavior.
- Task7 rustdoc normalization: narrowly scoped, retains execution status.

## Declined to judge

Installed CLI warning presentation and installed SDK discovery: explicitly deferred to M7/M8.

## Verdict

With fixes. Architecture and recorded acceptance strong; repair the two reproduced compatibility gaps before accepting M3b.
No repository, index or HEAD edits made during review.
