# Native Spanish query expansion — specification

Continues the approved whole Rust migration, with native inline execution and
no intermediate confirmation pauses. Ettin is accepted at 1ae4bb97 with 23 gates
on both registered platforms; M2 remains open. Preserve all original sources,
tests, resources, unrelated work, installed entrypoint and user indexes.

Status: independent original oracles captured; native product implementation and
profile acceptance remain pending. Private runtime experiments are feasibility
evidence only.

## Purpose, concepts and representative use

Run the existing lazy Spanish-to-English query expansion without Python. Preserve
the original decision to translate, protected identifiers, model bytes, token
policy, outputs, failure boundaries and compatibility revision. Retrieval owns
whether/where to use expansion; model selection and public network acquisition
remain later migration work.

- TranslationModel owns the source/derived declarations, recipe and compatibility
  identity. Its cache_path(root) yields the original models/translation/recipe/revision.
- PreparedTranslation owns authenticated derived bytes and their association with
  the model. No unchecked public constructor.
- TranslationPreparation owns JSON normalization and atomic cache publication.
- QueryExpansionPlan owns the decision and protected text for one query;
  ProtectedQuery owns exact placeholder restoration.
- LocalQueryExpansion owns lazy loading, the native translator/SentencePiece
  lifetime, serialized calls and actual native provenance.

Caller: parse the existing es-en-ct2-int8.json into TranslationModel; construct
LocalQueryExpansion(model, optional source snapshot, explicit cache destination);
expand(query) returns String or ModelError. An English request succeeds with no
model/cache/runtime preparation. Diagnostic public methods expose the query plan,
actual token pieces/IDs, readiness and native policy for independent probes.

Chosen approach: ct2rs with static CTranslate2 and SentencePiece, preserving the
published CPU model. Rejected alternatives: invoking Python/subprocesses, which
does not migrate execution; converting to a new neural format/runtime, which
introduces new numeric and preparation behavior without a demonstrated need.
Native computation uses Ruy for int8 and the original platform's float backend:
Accelerate on macOS, OpenBLAS 0.3.26 on Linux. Ruy alone changes translations near
the sequence boundary in the private experiment and is not an accepted fallback.

## Fixed data and native preparation

Original owners: src/ken/retrieval/{query_expansion,translation_preparation}.py and
src/ken/embedder/data/es-en-ct2-int8.json. Registration stays authoritative.
Source Prukario/opus-mt-es-en-ct2-int8@ad91ad1697ea1761111ff4c179400796d085b347,
CC-BY-4.0. Derived Helsinki-NLP/opus-mt-es-en@c96e2c5399ebfae4fc43d9669556b9afa74bb69d.
Require exactly model.bin,config.json,shared_vocabulary.json,source.spm,target.spm
in both declarations. Preserve attribution and every recipe field when hashing.

model.bin is 79567635 bytes, SHA256
44c5adc2c680f27c14c991e5ab7f74f38b41597153f7123bc8f6455f09a3b38b.
Source/target SentencePiece are 825924/801636 bytes; all five source/derived hashes
come from the original registration. No Torch, weight conversion or remote code.

Normalize config.json and shared_vocabulary.json with the original JSON object
insertion order, indent two, ASCII escapes and no trailing newline; config alone
adds one newline. The real config has strings/bools/null; vocabulary is an array
of 65000 strings. Preserve other three artifacts byte-for-byte. Derived config
is 223 bytes/SHA8f6496adfc930cbfecbe8281112197705c488fab47d34b4829b06d7f478909af;
vocabulary is 1276136 bytes/SHA040e48c9d00734f48506e052695837720bd1f6aa01c70636cde83038362baf19.

The supported normalization representation is ordered objects, arrays, strings,
bools, null and bounded integers. Limit each JSON text to4194304bytes and the
standard serde_json128-level recursion budget. Reject unsupported floats, duplicate object
keys, unpaired surrogates and oversized/malformed input explicitly, without
publishing. The fixed public profile needs none of those extensions. Do not claim
a general Python JSON interpreter. Share the authoritative ASCII string escaping
with assets::python_json; extend its compact sorted formatter for recursive
arrays so the full original definition hashes correctly. Do not enable global
serde_json preserve_order or change established object ordering.

Default recipe SHA256 is
1af342f7677e9f51477171000e5aa6e6527590a715f064bd64679c1aa491a9f0,
computed from Python json.dumps(full_definition,sort_keys=True). Validate the
destination basename equals the derived revision before even cache reuse.
An existing cache is fully verified and reused without touching upstream; corrupt
cache errors. New preparation uses authenticated owned source bytes, a private
sibling stage with ordinary umask-readable inner directory, exact derived checks,
file/directory sync and atomic publication. Reverify a concurrent winner. No
partial destination on failure, no unchecked reopen after verification.

## Text policy

Accept UTF-8 scalar text. Fix word/decimal/whitespace/casefold semantics to the
original Python 3.12 Unicode 15.0.0 on both platforms, using checked-in generated
data with an independent whole-scalar digest. No dependence on Rust's evolving
Unicode categories, lowercasing or default regex word/space classes.

Translation is needed when the input contains U+00BF, or at least two DISTINCT
words from the exact original _SPANISH lexicon occur in
set(re.findall(r'\w+',query.casefold())). One repeated word counts once;
accented/unaccented aliases are distinct members. Long-s and dotted-I casefolding,
combining marks, numeric categories and non-ASCII connector characters are pinned.
Otherwise return the exact original bytes without preparing data or a runtime.

For translated text, preserve this original regex's priority, greedy matching and
Python word boundaries:

```text
`[^`]+`|\b[A-Za-z_$][\w$]*(?:[.:]+[\w$]+)+\b|\b[A-Za-z_$]+_[A-Za-z_$\d]+\b
```

Use explicit Unicode15 classes/boundaries with onig 6.5.3. Nonempty backticks can
contain newlines. Assign ZXQ0QXZ,ZXQ1QXZ,... per match, including repeated values;
keep a local ordered vector of originals. Restore placeholders sequentially,
case-insensitively, permitting Python whitespace between EVERY character,
including multi-digit indices. Preserve exact matched originals and backticks.
Original global restoration also replaces a literal colliding placeholder and
leaves a placeholder the model damaged beyond recognition; preserve those
behaviors rather than silently changing the migration contract. Reject a restored
empty/whitespace-only translation using Python whitespace, including U+001C..001F.

## Runtime, errors and identity

Pin ct2rs 0.10.1, compiled CTranslate2 4.8.2, sentencepiece and sentencepiece-sys
0.13.2 with embedded SentencePiece 0.2.1. Disable default ct2rs features; enable
Ruy/SentencePiece, macOS Accelerate, Linux OpenBLAS/OpenMP COMP. Enable system
only on the separate openblas-src0.10.14 dependency, not ct2rs: the latter's
system feature skips compiling CTranslate2 and incorrectly requests CUDA archives
for this CPU profile. Linux build
prepares verified OpenBLAS0.3.26 privately/static, TARGET=ARMV8, BUILD_SINGLE=1,
NO_SHARED=1, NO_LAPACK=1, ONLY_CBLAS=1, USE_OPENMP=1, NUM_THREADS=64,NUM_PARALLEL=1.
The ordinary system libgomp is an explicit Linux native dependency. Never link a
Python extension as a substitute runtime. Public crates and source provenance,
checksums, compiler/tool versions and actual linked libraries travel with proof.

Model configuration: cpu,int8,intra_threads2,inter_threads1; verify actual replica
count is one. Source SentencePiece pieces plus exactly one explicit </s>;
translate_batch with beam_size1,max_decoding_length256, remaining original defaults
including max_input_length1024. Decode first result/first hypothesis with target
SentencePiece. All native failures return ModelError; no plausible fallback text.
The actual model permits at most512 input positions: test 511/512 success,513
error and1023/1024/1025 default truncation/error boundaries without inventing a
new preprocessor cap. Empty raw decoding errors only on the translated path.

Verify all five artifacts before native load. Materialize C++ path-loaded data
from owned authenticated bytes into a private retained directory; SentencePiece
may load authenticated serialized bytes. Retain storage until model destruction.
Loading and calls use one mutex; failures leave the runtime unprepared/retryable.
Concurrent same/different queries must preserve results and independently owned
outputs. Replacing the source/cache after authentication cannot substitute bytes
used by the initialized runtime. English remains lazy even after failed loading.
Serialization preserves inter_threads1; no new latency/concurrency SLA is claimed.

Compatibility identity is the exact original object and sorted Python JSON hash:
derived model_id/revision and five artifact records; runtime ctranslate2 and
sentencepiece versions; cpu/int8,2/1,beam1,maxdecode256, preprocessing
spanish-lexicon-two-or-question-protect-qualified-identifiers-v1. Provide explicit
frozen compatibility profiles macOS(4.8.3,0.2.1) and Linux(4.8.2,0.2.1). Report
executing native versions and float/int8 backend separately. Compatibility metadata
must not imply Rust imported or executed those Python packages.

## Evidence and acceptance

Private both-platform viability matched all24 raw histories after adding
Accelerate/OpenBLAS. The failed Ruy-only histories are retained. These experiments
are not final profile proof. Original macOS and Linux themselves produce different
text at511/512 repeated-token boundaries; preserve each platform's original
behavior with an explicit per-platform oracle, not cross-platform text equality.

Create frozen-original independent preparation, query-policy and real-model
oracles before native implementations. Adapt the original tiny preparation
fixture through recorded helper/source hashes. Whole-scalar Unicode digest and
fixed/generated lexical histories cover boundaries and match priority. Neural
histories include English/lazy/missing assets, repeated Spanish word versus two
distinct words, question mark, empty/plain Spanish, identifiers/backticks/repeats/
indices above9, Unicode/emoji/NUL/newlines, literal placeholders, repeated calls,
concurrent calls,511/512/513/1023/1024/1025 source lengths and error-then-English.
Compare exact IDs/pieces/hypotheses/text/errors/order/state/recipe/artifact bytes.
No numeric tolerance or output-text whitelist may conceal a different translation.

Negative preparation/runtime cases cover wrong revision, missing/extra artifacts,
size/hash/recipe damage, unsupported JSON, corrupt cache, failed publication,
source/cache path replacement, nonregular input, native construction failures,
and invalid/empty model output. Tests exercise public usage and actual native
code; policy-only doubles are labelled and never stand in for real inference.

Acceptance composes the existing23 gates plus translation_release,
translation_preparation and translation_parity=26 on both registered ARM platforms.
Use fresh immutable-source complete Python exact-baselineIDs/mypy, Rust/fmt/clippy,
original1066hashes and every prior profile. Prepare a fresh cache NATIVELY from
source, reuse it without source, run actual copied executable outside checkout
with sentinel PATH, audit native dependencies and retain actual Linux exec trace.
Bind every receipt to current source/tool fingerprints and platform/runtime pins;
measure process/preparation/call time and raw/observed peak memory without a
speedup/SLA claim. Explicit preparation inputs flow through tooling and CI without
global environment mutation. Missing prerequisites fail instead of skipping.

After all tasks, one fresh whole-plan reviewer on the most capable available
model; regrade findings by user effect, one TDD fix pass for Critical/Important,
defer Minors and rule explicitly on every declined scope. Accept this profile
only, then continue remaining M2 and M3–M8. No installation, push, merge or deletion
of originals is part of this profile.

Sources: pinned original code/data/tests; cached ct2rs0.10.1 C++/Rust source and
its platform wheel-build recipes;
[CTranslate2 installation](https://opennmt.net/CTranslate2/installation.html),
[hardware support](https://opennmt.net/CTranslate2/hardware_support.html),
[OpenBLAS0.3.26 release](https://github.com/OpenMathLib/OpenBLAS/releases/tag/v0.3.26),
[openblas-src0.10.14 build source](https://docs.rs/crate/openblas-src/0.10.14/source/build.rs).
