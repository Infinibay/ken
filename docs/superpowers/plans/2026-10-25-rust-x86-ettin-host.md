# Ettin x86 host integration plan

Use superpowers:executing-plans inline. Spec:docs/superpowers/specs/2026-10-25-rust-x86-ettin-host-design.md.
Base ce420a2c. User explicitly requests x86 only; pushes already authorized. Keep
all originals/raw local. No ARM investigation, fresh oracle or version changes.

## Review focus

- Generated files are authorized by caller pins, never receipt self-declaration.
- The /1 default remains strict and compatible; /2 cannot overwrite immutable inputs.
- Original/platform/request/resource closures are exact; unknown hosts reject.
- All16Rust and scoped Python roots bind actual command/JUnit destinations.
- Archived validator uses captured sources; scoped x86 closure never implies M2/M4.

### Task 1: Explicit generated-file process contract

Files:tools/rust_migration/native_json.py,tests/rust_migration/test_native_json_outputs.py.
Interface:optional generated_files mapping on NativeJsonCapture/verify_native_json.
- [ ] Add native C process tests for /1 readonly success/write rejection and /2
  exact output success; reject invalid/overlapping paths, missing/extra/damaged
  outputs, input mutation, symlinks, wrong timeout/contract and verifier opt-in.
  Run scoped pytest. Expected RED missing keyword. Implement bounded /2 alongside
  unchanged /1, run scoped tests GREEN. Commit; task-done same scoped suite.

### Task 2: Ettin host runner and strict evidence

Files:tools/rust_migration/ettin_host.py,tests/rust_migration/test_x86_ettin_host.py.
Interfaces:host_original(repo,system,machine);ettin_request(repo,original,root);
verify_ettin_capture(packet,repo);verify_ettin_gates(out);verify_ettin_host;
run_ettin_host(repo,sdk,source,packet). Reuse parent snapshot and compare_output.
- [ ] Add RED exactx86 original/missing packet guards, then implementation. Pin
  original ec1a7477, canonical Rust registration, fixed cases/tolerances. Reject
  other targets. Add input-only capture/binary/immutable resources/generated cache
  verification and full16Rust/scoped Python command/JUnit binding.
- [ ] Add resealed tamper tests: host,original,input answers,vector,binary,audit,
  source,generated/missing/extra cache, missing parent and crossedJUnit destination.
  Run actual source/core/model gates and new scoped tests GREEN. Commit/task-done.

### Task 3: x86 CI, final review and closure

Files:.github/workflows/rust-runtime-cores.yml and migration docs.
- [ ] Restrict active runtime workflow to Linuxx86_64 as explicitly requested;
  prepare pinned Ettin source data and run core→context→Ettin. Remove active ARM
  diagnosis. Preserve historical originals/validators and full acceptance flags.
- [ ] Full local fresh parent6ONNX/15Torch/364tooling,context8/20/11,Ettin16/23+
  scoped tooling,fmt/strictClippy; immutable-source x86 CI. Expected allgreen.
- [ ] One fresh final read-only review; one Important TDDrepair pass if needed;
  no re-review. Authenticate Git/source/tooling, archive and independently replay
  extracted evidence. Keep raw local, update exact scoped status, commit/push.
