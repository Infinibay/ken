# Native static table implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Native execution was selected by the user.

**Goal:** Reproducir el encoder NPZ existente con inferencia Rust autónoma.

**Architecture:** lector de arrays autocontenidos → encoder tabla/tokenizer → probe real → comparación con Python congelado. No cambiar selección de modelos ni consumidores todavía.

**Tech Stack:** Rust1.95, tokenizers0.22.2, half2.7.1, npyz0.9.1, zip6.0.0(deflate), ndarray0.17.1, Python sólo oráculo/tooling.

**Spec:** `docs/superpowers/specs/2026-10-18-rust-static-table-design.md`.

## Global Constraints

- Conservar todos los originales y cambios previos; branch `codex/rust-migration`.
- Capturar expectativas independientes antes del port; no ampliar tolerancias.
- F32 atol2e-6/rtol1e-5/coseno0.999999, ceros exactos e IDs exactos.
- Dos plataformas observadas Linux/macOS; autonomía y trazas verificadas.
- Sólo tabla actual acreditada; otros runtimes/datos/M2–M8 pendientes.

## Review Focus

1. Tokenizer serializado con padding/truncation: conservarlo incluso en vacíos y token_count.
2. Matrices Fortran/big endian y LUT negativo: seleccionar las mismas filas/columnas.
3. Lotes con vacíos intercalados y textos largos: no sumar la fila siguiente ni usar la política Potion.
4. Archivo corrupto, escala/forma incompatible o no finito: error explícito, sin pánico ni vector válido aparente.
5. Proyección y reducción cerca de cancelación: paridad numérica sobre valores reales y sintéticos, no sólo coseno.

---

### Task 1: Oráculo independiente y fixtures de formato

**Files:** Create `tools/rust_migration/table_reference.py`, `tests/rust_migration/test_table_reference.py`, `crates/ken-models/tests/fixtures/table/`; evidence `docs/validation/rust-migration-2026-10-18/m2-table/`.

**Interfaces:** Consumes `Reference.load/root/python`, `reference_env`, `verify_reference`. Produces `table_cases()->list[dict]`, `capture(reference:Reference,artifact:Path,output:Path,cases:list[dict]|None=None)->dict`, JSON format `ken-table-oracle/1` containing exact artifact hash, cases, runtime, dimension, meta, results, tolerances. Calls: tokens/count/query/passages/queries.

- [ ] Write test `test_frozen_table_capture_preserves_unknown_and_empty` asserting frozen import, tokens `[0,4,1]`, count3, mixed batch zero and diagonal `[.70710677,.70710677,0]`; changed artifact or frozen source must fail. Test missing module RED.
- [ ] Implement capture in a sanitized child importing only frozen `src`; hash artifact before/after, verify reference, record numpy/tokenizers versions and phase times/RSS. Fix 16 representative cases including512/513/4097 tokens, nonempty surrounding empties and batching. No Rust/native outputs enter capture.
- [ ] Generate independent tiny NPZ fixtures with original Python: F32, int8 scales, F16/F64, Fortran+big endian, serialized padding/truncation, negative LUT and cancellation; malformed required arrays/shapes/scales/NaN/object fixtures. Retain generator and expected outputs.
- [ ] Run `.venv/bin/python -m pytest tests/rust_migration/test_table_reference.py tests/test_static_head.py -q`; Expected all pass. Capture bundled table to public reference JSON before native implementation. Verify original manifest and commit only own artifacts/tooling/tests.

### Task 2: Native table and lexical/numerical contracts

**Files:** Create `crates/ken-models/src/table_npz.rs`, `static_table.rs`, `tests/static_table.rs`; Modify `src/lib.rs`, own Cargo manifests/lock.

**Interfaces:** Consumes NPZ bytes and fixed fixtures. Produces `StaticTableEncoder::from_npz(&[u8])->Result<Self,ModelError>`, `dim()->usize`, `meta()->&serde_json::Value`, `tokenize(&str)->Result<Vec<u32>,ModelError>`, `token_count(&str)->Result<usize,ModelError>`, `embed_query(&str)->Result<Vec<f32>,ModelError>`, `embed_passages(&[&str])->Result<Vec<Vec<f32>>,ModelError>`, `embed_queries(&[&str])->Result<Vec<Vec<f32>>,ModelError>`.

- [ ] Write integration tests for every valid fixture, exact IDs/count, query/passages/queries, independent copies, zero/long/mixed batches, F16/int8 and layout conversions. Corrupt fixtures must return Err. Include cases for all five Review Focus lines. Run `cargo test --locked -p ken-models --test static_table`; Expected unresolved encoder RED.
- [ ] Add exact dependencies; reader validates dimensions/type/shape/LUT/finite bytes, preserves endian/Fortran by conversion, rejects pickle. Encoder owns tokenizer and matrices; keep serialized policies, use sum→projection→L2 F32. Do not reuse Potion lexical policy.
- [ ] Run same test GREEN, `cargo fmt --all --check`, `cargo clippy --locked --workspace --all-targets -- -D warnings`, prepared `cargo test --locked --workspace`; Expected all pass, real Potion test mandatory. Commit own sources/fixtures only.

### Task 3: Real native process and two-platform gate

**Files:** Create `crates/ken-models/examples/table_probe.rs`, `tools/rust_migration/table_compare.py`, `tests/rust_migration/test_table_compare.py`; modify own native CI and migration guide/evidence.

**Interfaces:** Probe consumes stdin `{artifact,cases}`, returns actual hash/runtime/dimension/meta/results/phase data. Comparator `compare(reference:Reference,native:Path,artifact:Path,out:Path)->dict` executes copied native binary outside checkout, matches fixed IDs/vectors/zero/finite outputs and records autonomy/fingerprints. Strict matching macOS/Linux receipts accept only table profile.

- [ ] Write negative comparison tests: wrong IDs/dimension/vector/NaN/zero and false executable must fail; real probe integration must pass full frozen bundled cases. Run missing module/probe RED.
- [ ] Implement probe with actual encoder, hash checked data and explicit failure exit; comparator uses existing native/dependency/isolated-process helpers where compatible. Require Linux actual trace1exec, retain stdout/stderr/arrays. No subprocess from Rust.
- [ ] Build release, run comparison and all new/tooling/original table tests on macOS and Linux; run complete Python suite with exact baseline IDs and full Rust/fmt/clippy on both. Preserve outputs; compare hashes before/after; no promoted entrypoint.
- [ ] Record both-platform receipts, measurements and review once with fresh reviewer per executing-plans. Fix only Critical/Important in one TDD pass; defer Minors. Commit own code/docs; mark only table profile accepted and continue remaining M2 runtimes/data.

## Self-review

All spec contracts map to T1 fixtures, T2 encoder and T3 real process/platform gate.
T1 produces expectations before Rust; T2 signatures match T3. Three deliverables
are independently testable. Global tests run at the final gate, with original
table tests and prepared workspace tests at task boundaries. Existing M0/M1 and
Potion receipts remain historical evidence rather than claims for new sources.
