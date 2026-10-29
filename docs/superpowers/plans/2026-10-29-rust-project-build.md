# Native structural project construction and artifact cache

Continue the same requested long autonomous work block from7d707f4d. Core outward,
Linux x86_64 only; grouped validation, one fresh final review, commit/push authorized.
Keep original sources/installed Python and raw/workspaces local. No model/CPU/CI
loops or new dependency versions. KQL execution and persistent executable graph
publication remain later work, not claims of this stage.

Concepts: ProjectBuilder orchestrates a confined source manifest, reusable source
frontend, full project linker, and optional content-addressed artifact cache.
SourceManifest owns one captured source revision per file, explicit limits/skips
and complete coverage metadata. IrCache owns compressed JSON, length-framed keys,
transactional LRU and disk quota, and degrades to misses on disposable cache errors.
Core SourceFile owns bounded handle reads; GrammarCatalog owns grammar identity.
New ken-structural crate depends on core/program/syntax/store, without model/search
runtime dependencies. Reuse authoritative TypeRef/parse_type already in ken-program;
remove the duplicate parser introduced in the new semantic materializer, validating
against all639 new descriptors before consolidating.

Usage: ProjectBuilder::new(paths, context, frontend, cache).build(path, limits, check)
returns graph plus analysis including files/skipped, resolution, cache stats,
graph_key and coverage_complete. Default limits match original2MB/no file ceiling.
Frontend exposes stable revision and lower; native adapter derives grammar identity
and accepts explicit engine revision for semantic invalidation. A failed frontend
file is skipped and a partial graph is never cached under a complete manifest key.
Cache project hits still report this scan's skipped coverage; skip lists aren't
cached as whole answers. Source handles enforce max_file_bytes while reading.

1. Capture original cache/key/manifest/build behavior on new input trees once.
2. Implement compatible safe disposable cache and bounded source support.
3. Implement manifest/build orchestration and native frontend adapter; reuse types.
4. Group cache/service parity, edit/delete/add, grammar/engine revision, corrupted
   cache, disabled/tiny quota, frontend failure/recovery, limits and confined IO.
5. Final review/fix once, docs and authorized commit/push. Reuse existing linker
   captures as native test inputs, never replay accepted original observations.

All five steps complete. New original11builds/4manifests/6keys and portable SQLite
fixture captured once;12 native integration roots and43 affected roots passed.
Strict Clippy and format passed. One final review, five Important findings fixed
in one RED→GREEN pass, no re-review/minors. The linked graph key intentionally
adds a native engine namespace independent of frontend revisions; original unit
framing/entry codec remain compatible. Actual build program resource/local-parser/
manifest/path tests cover identity closure. Service/config transport and executable
query-index/KQL remain out of scope. No new dependency versions; only local crate.
