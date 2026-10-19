# Native contextual ONNX profile — specification

Status: next M2 profile after accepted Potion and NPZ profiles. The approved
whole migration and native inline method authorize its elaboration and execution;
this specification is not an acceptance receipt. All originals remain unchanged.

## Responsibility and use

The problem is to execute the registered contextual graph without Python while
preserving its lexical inputs and raw CLS vectors. Retrieval owns scoring/L2.
The native runtime owns authenticated executable code and its process lifetime;
the contextual encoder owns prefixes, tokenizer policy and one serial session.
ModelAssets remains the only model artifact verification owner.

Representative caller: parse the existing context registration; verify its
snapshot; declare the pinned runtime library; construct a context encoder from
owned verified graph/tokenizer bytes; call tokenize/query/passages. No project,
storage, environment selection or download logic enters these concepts.

Runtime declaration is cheap. Empty passages returns[] without creating an ORT
environment/session. Actual model preparation and native library verification
are measured separately from session construction/inference. Caller-supplied
verified model bytes are an explicit API precondition, as in Potion.

## Fixed registered behavior

- Original: src/ken/embedder/contextual_onnx.py and data/code-context-int8.json.
- CodeRank revision e74f446dc6e67e29fcee77213472c142f73a6bbb; graph138619279bytes,
  SHA4eae31d09b1843103a1ebd5e2b2e24b5a5cad441a33906b35b12b1e2ed91d1db;
  tokenizer711649bytes,SHA91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854.
- Query prefix exactly `Represent this query for searching relevant code: `;
  passages unprefixed. Preserve document_projection and compatible spec identity.
- tokenizers0.22.2: no padding, truncation512, special tokens enabled. Return IDs
  and attention mask exactly; I64 tensor inputs input_ids/attention_mask,[1,L].
- CPUExecutionProvider only, intra2/inter1, sequential/default graph optimizations.
  One text per inference, ordered owned F32 vectors. No encoder L2 or term cache.
- sentence_embedding must be exactly[1,768],F32,finite. Missing/wrong graph inputs
  or output, tokenizer corruption, invalid graph and shape/type/NaN/Inf are errors.
- Empty/Unicode/code/prefix truncation and511/512/513/4097token inputs are explicit
  histories; repeat and concurrent calls must remain stable and independently owned.

## Runtime identity and verified data

Pin ort2.0.0-rc.14, default-features=false, std/alternative-backend/api-25, plus
libloading0.9.0. Actual core version1.25.1; reject incompatible exact version,
size/hash, missing symbols, null API and unavailable CPU. No implicit library
search, ORT_DYLIB_PATH, Python extension import or ORT binary download at inference.

Official crate sources show init_from silently retains the first global library.
An isolated characterization proved the supported custom loading scheme:
authenticated handle -> OrtGetApiBase -> exact GetVersionString -> GetApi25 ->
ort::set_api(cloned table) -> ort::init().build. set_api reports prior registration.
Use one synchronized owner. Reject an unowned preinitialized API. Reuse only the
same authenticated descriptor, including aliases; reject conflicting second
identity even under concurrent loads. Keep the native handle alive for all API
lifetimes, including environment creation failure. No panic-based normal errors.

Read only regular files through opened metadata and declared size bounds; reject
devices/FIFOs without blocking, preserve regular HF blob symlinks. Share this
verification rule with ModelAssets rather than duplicate it in the runtime.
Load a private copy of verified library bytes to avoid unchecked path reopening;
test Unix unlink-after-dlopen while keeping its handle alive so processes leave
no persistent temporary runtime copies. This profile is CPU and Linux/macOS.

Observed cores (test preparation copied native C cores from installed wheels;
they are independent native libraries, not Python extension runtime dependencies):
macOS arm64:28418248bytes,4478626717e213a1827ab52af61d1a0ac08f9906bcb2c2ab4563124967b2948b;
Linux aarch64:19280896bytes,0ebab581324d80e2975d743eabcf640ac3f8acd429ca8af656ce4f121672afde.
Other deployment architectures need their own pinned runtime receipt before M8.
Native preparation/distribution remains separate later work; never replace the
original environment, assume a wheel is installed in production or bypass versions.

## Independent oracle and numerical boundary

Capture the same fixed histories independently from frozen Python on both OSes
before native encoder implementation. Retain platform vector outputs in one
versioned oracle document. IDs/masks/prefixes/artifacts exact; F32 atol2e-6,
rtol1e-5,cosine0.999999, zero outputs exact. No tolerance widening.

The original itself differs across platforms for one calibrated22-token query:
maxabs0.4787996113,cosine0.988123142, same artifacts and ORT1.25.1. This is existing
native platform variation, not license to compare Rust against a different model.
Require tight native-vs-frozen parity on each OS. Record core/architecture/runtime
identities, retain the failed cross-platform experiment, and make no platform
invariant vector or cross-platform index quality claim from package version alone.

Linux core emits the exact known cpuid_info Unknown CPU vendor warning in both
original and native runs. Preserve stderr; allow only the calibrated exact line,
with count and OS recorded. Every other stderr byte fails. Potion/table remain
strictly silent. Do not suppress warnings globally.

Generate tiny independent ONNX graphs/tokenizer fixtures through original Python:
input/mask-dependent valid raw vector, wrong dim/type/name, extra row, NaN/Inf and
corrupt graph. Golden capture never imports Rust or reads its outputs.

## Acceptance

Public callers and error fixtures; actual registered model mandatory; full native
workspace/fmt/clippy; original Python suites and baseline exact IDs; intact1066
original hashes; outside-checkout native probe with owned graph/core copies and
restricted PATH; actual Linux trace exactly1exec, no Python-linked libraries or
Python interpreter; explicit fresh release/hash binding; complete fixed histories
and phase measurements. Both OS receipts share source/cases/oracle/registration
identities and validate their declared per-OS runtime hash.

Compose all18 table/Potion/M1 gates plus contextual release and parity gates.
Fresh whole-plan review once; one TDD pass for Important/Critical. Accept only
context profile. Other embeddings, reranker, translator, optional ST/MLX,
selection, storage and M3–M8 remain pending. No original removal or entrypoint
promotion follows from this profile.

## Source evidence

Original Python and exact installed crate sources are authoritative for this
port. ONNX threading defaults documented at
https://onnxruntime.ai/docs/performance/tune-performance/threading.html .
Private characterization retains both init_from and custom-owned API experiments.

## Clarifications before implementation

Use the existing frozen tests/test_context_encoder.py::contextual_model graph
fixture through an explicit fixture-generator adapter, then vary private copies.
Extra output rows are rejected even though the original first-row indexing hides
them; this is a declared narrow corruption-contract correction.

The probe invokes explicit prepare for measured session construction, except the
empty-passages history which remains unprepared to prove lazy behavior. The shared
case document records this flag. Preparation of model bytes is separate; Python
re-verifies files when loading while Rust consumes already verified owned bytes.
The first runtime load includes native-library verification/copy/mapping; later
loads reuse the authenticated process owner. All differences stay in measurements.

The compatible spec preserves the original six EncoderSpec fields, key and
tokenizer_revision for the fixed original runtime versions captured in the oracle;
actual Rust/core identity is reported separately. No Rust operation executes NumPy.
