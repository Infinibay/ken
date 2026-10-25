# Linux x86_64 Native CPU Cores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. User authorized continued migration,x86_64 and pushes. One final fresh reviewer,no implementation agents or stage-approval stop.

**Goal:** Make native CPU runtime preparation and loading work on Linuxx86_64 without ARM fallback.
**Architecture:** Versioned resource metadata owns bytes;native_platform owns host identity;transformer_cores owns exact backend selection;existing copy/load APIs retain authentication and lifetime.
**Tech Stack:** Rust1.95.0,Python3.12.9,ORT1.25.1/API25,Torch2.9.0CPU,tch0.22.0;no dependency/version changes.
**Spec:** docs/superpowers/specs/2026-10-24-rust-x86-runtime-cores-design.md.

## Global Constraints

Preserve1066frozen files and all accepted originals/receipts. Preserve existing ARM record identities byte-for-byte. Source-wheel SHA/bytes and selected library closure are authenticated before publication. CPU only,no Python/CUDA runtime. Fresh explicit SDKs,no overwrites. Keep raw local. No x86model/index/global acceptance from core-only tests. Continue full x86target afterward. No install/merge/release/tag.

## Review Focus

1.Mixed LinuxARM/x86registries must select by architecture even if ARM is first.
2.Unknown/duplicate targets must reject rather than use a same-OS fallback.
3.Wrong-architecture/corrupt SDK at a warm destination must not overwrite it.
4.Native code must retain its verified library closure after declaring owners drop.
5.Runtime declaration,actual native binary architecture and API/core version must agree;Python package suffixes must not be mistaken for native version proof.

### Task 1: Authenticate CPU SDK sources and register native x86bytes

**Files:** Create crates/ken-models/resources/onnx-runtime-libraries.json and tools/rust_migration/data/native-sdk-sources.json. Modify tools/rust_migration/data/transformer-cores.json and tests/rust_migration/test_native_platform.py. Raw under .ken/rust-migration/x86-runtime-cores.
**Interfaces:** Existing NativeOnnxRuntime accepts ken-native-onnx/1;Torch core entries retain existing schema. Native source metadata records exact source URL/package/platform/bytes/SHA and license provenance separately from strict runtime records.

- [x] Read official PyPI metadata and PyTorch CPU index;download/authenticate the pinned x86wheels without executing them. Inventory native files,ELFarchitecture,SDK version header and actual dependency closure. Retain all raw evidence;do not install globally or import these packages.
- [x] Write a missing-registration test requiring uniqueLinuxx86ONNX/API25 andTorchCPU registrations plus unchanged ARM canonical digests. Witness RED,then add actual verified records and consumed source metadata;GREEN. ARM source metadata may be recorded from official existing wheels for the subsequent3hostSDKjob.

### Task 2: Make runtime selection and callers architecture-aware

**Files:** Create tools/rust_migration/native_platform.py,tools/rust_migration/transformer_cores.py. Modify context_compare.py,transformer_prepare.py and its exact core-selection consumers as needed;point Rust ONNX callers/probe fingerprints and affected tooling at the canonical versioned registration. Do not rewrite historical ignored registrations.
**Interfaces:** native_target(system:str,machine:str)->tuple[str,str];transformer_core(registry:dict,system:str,machine:str,backend:str)->dict;transformer_cores(registry:dict,system:str,machine:str)->list[dict]. Existing core_for_platform/prepare_transformers signatures remain compatible;prepared metadata must retain actual architecture.

- [x] Add public-use target tests for allthreehosts,mixed/duplicate/missing/foreign records,including ARM-first Linux selection and preserved ARM results. Run new target/preparation tests;Expected unsupported/missingAPIRED.
- [x] Implement one authoritative target mapping and exact Torch lookup;use them in preparation and capacity planning. Keep native artifact/version validation with existing loaders/SDKcopy owner. Preserve current callers/error domains;reject foreign target/prepared SDK before publication.
- [x] Update actual ONNX runtime callers,compiled-source fingerprint paths and supporting snapshot paths consistently to the new versioned metadata. Read/recall each file before editing and trace changed consumers/tests. Run complete affected context/fastembed/transformer/integration tooling,not only the new tests.

### Task 3: Prepare actual native cores and run host contracts

**Files:** Add tools/rust_migration/native_core_prepare.py,tests/rust_migration/test_native_core_prepare.py and .github/workflows/rust-runtime-cores.yml;reuse existing copy_torch_sdk/native loaders/backend builds. Use isolated local package-data directories/SDKs.
**Interfaces:** prepare_native_cores(repo:Path,cache:Path,out:Path,*,target:tuple[str,str])->dict returns explicit ONNX library,TorchSDK,source/runtime identities. Existing native Torch tests consume LIBTORCH/LIBTORCH_CXX11_ABI=1 and owned loader paths;Rust ONNX tests consume KEN_ORT_LIBRARY. No Python package runtime is required.

- [x] Before implementation,add wrongsourcehash/foreignarch/existingdestination regressions;Expected missingAPIfailure. Reuse uv's pinned-wheel data extraction with no dependencies and existing strict SDK copy;do not introduce a second generic archive framework. Authenticate all relevant bytes before publishing.
- [x] Prepare current x86SDKs,run complete native_onnx test target and standalone native/ken-torch-backend tests,loader/exec audits,fmt andstrictClippy. Record actualbinary/corearchitecture and versions. Exercise library lifetime and corrupt/missing-core tests (ReviewFocus3–5). Do not run oldARMnumerical goldens as x86acceptance.
- [x] Add native three-host CPU-core workflow(ubuntu24x86/ubuntu24ARM/macos15),pinnedtools/source records,actual runtime contracts and complete affected tooling. Preserve command/discovery/exit/source/tooling/binary/resource records as ignored artifacts. No original model-suite reruns or MLX-on-Linux claims.

### Task 4: Review,seal and continue the complete x86target

**Files:** Local docs/validation/rust-migration-2026-10-24/x86-runtime-cores;tracked handoff/guide/thisplan.
**Interfaces:** Only NativeCPUCore_x86_64 may be accepted after actualthreehostgates/review;full x86M2/M3/M4 remain pending until their own actual observations.

- [x] Require complete local/tooling/native host gates and existing sourcepiece/syntax regressions;authenticate archived CI sources againstGit and replay each runtime packet. Preserve oldreceipts and all1066original identities.
- [x] One fresh read-only final reviewer over fullplan/base/head/spec. Rule on every finding/declined behavior;one Important/Critical RED→GREEN repair pass and complete gates if necessary,no secondreview.
- [x] Preserve local review/receipt and update exact capability/status/limits. Commit/push;continue fresh x86model oracles/full indexhistory/retrievalmatrix rather than claiming complete architecture support prematurely.

Cierre acotado: candidato ece7a0c6, CI de cores40149696864, gramáticas40149696833
y piezas40149696715 completos. Recibo y límites en docs/rust-migration-handoff.md.
La continuación ya capturó20historias originales x86 del encoder contextual y
comparó las20en Rust; fixture permanente y aceptación de modelos/índice completos
x86 quedan como siguiente bloque. No se acredita M2/M3x86 ni M4/global aquí.
