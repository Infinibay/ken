# Linux x86_64 Native Grammars Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inline execution and continuation are already authorized; use one final reviewer, not implementation subagents or another stage-approval handoff.

**Goal:** Enable authenticated native syntax on Linux x86_64 before the remaining M4d search composition.

**Architecture:** Extend the existing immutable grammar resource registration and host selector. Preparation owns bytes/licenses, GrammarCatalog owns loading/lifetime, and ParserRegistry retains all parser rules. Reuse the existing original/native parser observation and audit tools.

**Tech Stack:** Rust1.95.0,tree-sitter0.25.10,pack1.8.1,Python3.12.9/Unicode15;existing Cargo/development dependencies only.

**Spec:** docs/superpowers/specs/2026-10-24-rust-x86-grammars-design.md.

## Global Constraints

- Preserve pack revision33602ce7d17edd24cc00a1a9fe7129a61138f8ef and both ARM bundle entries exactly.
- Official x86archive:19144528bytes,SHA256f670f0582aa186df8da69d60624653df3d482f85546e162bdfaedbc77d2cf390;13dynamic modules,20grammars,19parsers,44extensions.
- Rust1.95.0,tree-sitter0.25.10,pack1.8.1,Python3.12.9/Unicode15 and all Cargo versions remain unchanged; no new dependency.
- Capture new x86original parser observations/scoped suites once before enabling native loading. Reuse all accepted originals; keep1066frozen files unchanged.
- Generated archives/SDKs/raw/receipts stay local/ignored; only consumed original/regression fixtures and registration metadata belong in Git.
- Accept Grammar_x86_64 only; full x86M3/index/model profiles,M4public search and M5–M8 remain pending. No promotion,merge,release,tag or installed-command replacement.

## Review Focus

1. A cached ARM SDK at an x86destination must reject without overwriting bytes or masquerading as another host's accepted resource.
2. Every selected dynamic library must authenticate before dlopen; a valid filename with wrong architecture or bytes must fail its own consumer without breaking builtin languages.
3. Held syntax trees and concurrent parsers must retain the native module after catalog drop, on the added host as on ARM.
4. Unicode15,invalid UTF8,CRLF and error-node observations must remain exact with the x86build, including all complete syntax records.
5. An SDK/probe copied outside checkout must remain sufficient with empty PATH/HOME, and the actual Linux loader/exec/connect logs must certify native execution rather than a passing summary.

---

### Task 1: Register and prepare the pinned x86grammar resource

**Files:** Modify crates/ken-syntax/grammars.lock.json;tests/rust_migration/test_grammar_prepare.py. Create crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz. Preserve tools/rust_migration/grammar_prepare.py signatures. Local raw under .ken/rust-migration/m4d-x86-grammar.

**Interfaces:** Existing prepare_grammars(lock:dict,cache:Path,destination:Path)->dict produces ken-native-grammars/1. KEN_PARSER_ORIGINAL_GRAMMARS selects its explicit SDK for capture_parser_reference(reference,out,repo=repo)->dict; no observer/schema change.

- [x] Add a registration regression requiring linux-x86_64,exact official archive identity,13unique selected files and unchanged ARM bundle digest. Run pytest test_grammar_prepare; Expected missing-registration RED.
- [x] Inventory the authenticated official archive,copy the same grammar revisions/symbols/licenses,add only the x86bundle metadata and prepare it at .ken/rust-migration/m4d-x86-grammar/sdk-linux-x86_64. Never overwrite an existing different SDK. Add/reuse the prepared-cache tamper/cross-platform regression for Review Focus1.
- [x] Capture the new x86original parser corpus and its exact scoped suite once with the frozen reference and explicit SDK. Preserve observer/request/stdout/stderr/JUnit/source/runtime/package bindings. Reuse a completed capture on retry; no ARM-original recapture. Save the validated complete new reference as deterministic gzip at crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz,consumed by the new tooling caller; preserve existing fixtures.
- [x] Run the native all-grammar public-use test with this prepared manifest before changing grammar.rs. Expected host rejection RED. Commit registration/preparation/original fixture with native support still disabled.

### Task 2: Enable the host and authenticate native parser behavior

**Files:** Modify crates/ken-syntax/src/grammar.rs;tests/rust_migration/test_grammar_prepare.py. Create tools/rust_migration/grammar_extension.py,tools/rust_migration/grammar_packet.py,tools/rust_migration/command_gates.py,tools/rust_migration/native_snapshot.py,tests/rust_migration/test_grammar_extension.py,tests/rust_migration/test_command_gates.py and .github/workflows/rust-syntax.yml; reuse tools/rust_migration/{parser_validate,parser_evidence,parser_reference,grammar_prepare}.py and related tests. No parser-rule changes without a demonstrated differential.

**Interfaces:** New grammar_extension.read_reference(path:Path)->dict reads the bounded frozen JSON/gzip reference;restore_fixture_original(path:Path,destination:Path)->dict restores its six authenticated raw records without reexecution;grammar_packet.capture_packet(repo:Path,manifest:Path,out:Path)->dict produces the host packet;snapshot_packet(repo:Path,out:Path)->None archives its immutable source/tooling inputs;extract_grammar_snapshot(packet:Path,destination:Path)->Path reuses bounded regular-only snapshot transport; verify_grammar_packet(packet:Path,repo:Path)->list[str] authenticates original/case/source/binary/module/gate bindings; aggregate_grammar_hosts(directory:Path,repo:Path,review:Path|None=None)->dict requires linux-x86_64,linux-aarch64,macos-arm64 and source-bound review before Grammar_x86_64_accepted=true. Existing GrammarCatalog::prepared(&Path)->Result<GrammarCatalog,ParseError>,ParserRegistry::new(GrammarCatalog),ParserRegistry::parse(Language,&[u8],&str)->Result<ParsedFile,ParseError>. Existing run_parser_capture(repo,probe,manifest,cases,out)->dict and verify_parser_capture(out,cases,sources,native_sha256,lock)->list[str].

- [ ] Add the Linux/x86_64 platform branch; unsupported hosts still reject. Keep current manifest,byte,license and lifetime contracts. Run complete grammar and detection tests; Expected GREEN. Exercise existing corruption/foreign-platform and concurrent/held-tree regressions for Review Focus1–3.
- [ ] Run complete syntax/parser/doc tests and grammar/parser tooling against the actual x86original observations. Compare every case ID,full outline/import/scope and syntax record. Review Focus4 includes all existing invalid-UTF8/CRLF/Unicode/error-node cases; no fixture rewriting or broader tolerance.
- [ ] Build parser_probe;capture it outside checkout with the copied SDK,empty PATH/HOME,actual strace exec/connect and loader logs. Authenticate current sources,executable,all13modules,requests and raw complete outputs using existing verifier (Review Focus5).
- [ ] Write tamper tests before the new packet/aggregate verifier: wrong platform/SDK/source/binary,missing/extra cases,changed syntax,resealed raw output,incomplete discovery/lint and missing host/review reject. Delegate actual parser execution/audit verification to the existing tools; do not copy parsing or semantic comparison. Then add a scoped native three-host workflow (ubuntu-24.04,ubuntu-24.04-arm,macos-15) with pinned tools/prepared SDK,complete syntax/doc/tooling gates,fmt and strict Clippy. Reuse ARM-original semantic fixtures; do not rerun accepted ARM-original suites. Preserve source/tooling/executable/resource/raw/discovery/exit records in ignored Actions artifacts. No unrelated model downloads/builds.
- [ ] Run all8incremental index roots locally with KEN_GRAMMAR_MANIFEST and the already prepared x86BLAS build environment. Label this integration smoke,not complete x86index acceptance. Commit/push only after affected local gates pass; complete all three native hosts.

### Task 3: Review and seal the added platform capability

**Files:** Local docs/validation/rust-migration-2026-10-24/x86-grammars;update docs/rust-migration-handoff.md,docs/rust-migration.md,docs/validation-artifacts.md and this plan.

**Interfaces:** Receipt binds x86original/native/source/tooling/module identities and complete host gates. Only Grammar_x86_64_accepted may become true after review/replay; global migration and M4 remain false.

- [ ] Authenticate downloaded host packets and archived sources. Verify new x86oracle and original1066inventory; preserve prior ARM/M4c2receipts. Independently replay actual observations from the archived validator.
- [ ] Dispatch one fresh read-only final reviewer with scope/base/head/spec/plan and the five Review Focus lines. Regrade every finding/declined behavior; one Important/Critical defensive TDD repair pass and complete gates if needed,no second review. Record remaining minors/limits explicitly.
- [ ] Seal the platform-specific local receipt and transport archive;test its independent replay. Commit/push tracked status and identity references,keep raw local,remove only owned regenerable scratch and continue M4dsource/symbol/piece composition without another stage-confirmation stop.
