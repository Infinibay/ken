# Native model-selection and prompt policy

Continues the approved whole Rust migration after accepted translation97262af3.
Execution remains native/inline, continuous, without new stage confirmations.
All originals, installed entrypoints and user indexes remain preserved. This cut
implements policy only; overall M2 and all later stages remain open.

## Problem and boundaries

A default-model change must not repin an existing vector space. Model selection
and query/passage prompts are domain decisions independent of inference engines.
Implement them in ken-models, reusing its fixed Python Unicode15 whitespace owner.
Project/storage readers remain independent and supply established facts; this
cut does not implement their SQL/file I/O or publish model pins to user databases.
Unknown/unreadable storage is not an established empty index: its future reader
must return an error instead of supplying false presence or absent-project facts.

| Concept | Responsibility |
|---|---|
| ProjectModelFacts | Carry the recorded model and proven file-vector presence |
| ModelPolicy | Resolve names and prospective initial pins from explicit inputs |
| InitialModelPin | Describe the two metadata values for a proven fresh index |
| ModelPrompts | Preserve the exact query/passage prefix pair for a model name |
| Policy receipt | Compare original/native decisions and bind current process proof |

Representative use:

```rust,ignore
let policy = ModelPolicy::new(Some("user/default"));
let facts = ProjectModelFacts { recorded_model: None, file_vectors_present: true };
let selected = policy.resolve_project(&facts, None);
assert_eq!(selected.model, LEGACY_MODEL);
assert!(selected.initial_pin.is_none());
let prefixes = prompts_for("intfloat/e5-base");
assert_eq!(prefixes.passage, "passage: ");
```

The factual presence means any ci_files embedding IS NOT NULL OR vec_slot IS NOT
NULL, including an empty BLOB or slot zero/negative. Native storage extraction is
still pending. Policy receives the logical fact, without duplicating physical
format rules. No encoder, singleton, network or model artifact is needed here.

## Exact policy

Constants retain the original IDs: LEGACY_MODEL sentence-transformers/all-MiniLM-L6-v2;
RECOMMENDED_MODEL sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2;
POTION_MODEL minishlab/potion-code-16M-v2. New-project recommendation is a valid
user default or POTION_MODEL; it is not RECOMMENDED_MODEL.

ModelPolicy::new consumes an already-read optional string. A missing, empty or
Python15-whitespace-only user default is absent. Valid strings retain their exact
bytes, including outer spaces/NUL/zero-width characters. No model-ID validation,
trimming, aliasing or backend selection is added by this policy.

Project resolution: nonempty environment override, then nonempty recorded model,
then LEGACY_MODEL if file vectors exist, otherwise recommendation. Whitespace
strings are nonempty overrides. Forced process state does not affect this method.
An InitialModelPin is returned only when recorded_model is None and no file
vectors exist. It carries the selected name and document_space=2. Present-empty
metadata therefore falls back for selection but prevents prospective publication.
The later writer must apply this plan inside the transaction proving freshness.

Active resolution: nonempty forced model, then nonempty environment override,
then project resolution when known, otherwise recommendation. Pending upgrade is
suppressed by a nonempty environment override; otherwise the resolved project
model equal to LEGACY_MODEL yields (legacy,recommendation), even if both IDs equal.
No shared process state is introduced; callers pass current overrides explicitly.
Each policy owns a configuration snapshot; live file reload/singleton lifecycle
belongs to later adapters and must not be inferred from this pure API.

Prompts are case-sensitive, longest-prefix matches, preserving exact spaces:
Qwen/Qwen3-Embedding -> query "Instruct: Given a developer's question, retrieve the code file that answers it\nQuery: ", passage "";
intfloat/multilingual-e5 and intfloat/e5 -> "query: ", "passage: ";
all others -> "", "". is_asymmetric means the pair differs from ("", "").

## Interfaces and ownership

model_policy is a public module. ProjectModelFacts{recorded_model:Option<String>,
file_vectors_present:bool}; ProjectModelResolution{model:String,
initial_pin:Option<InitialModelPin>}; InitialModelPin{model:String,
document_space:u32}; ModelUpgrade{current:String,recommended:String}.
ModelPrompts{query:&'static str,passage:&'static str}.
ModelPolicy::new(Option<&str>)->Self; recommended_model(&self)->&str;
resolve_project(&self,&ProjectModelFacts,Option<&str>)->ProjectModelResolution;
active_model(&self,Option<&ProjectModelFacts>,Option<&str>,Option<&str>)->String;
pending_upgrade(&self,&ProjectModelFacts,Option<&str>)->Option<ModelUpgrade>.
prompts_for(&str)->ModelPrompts and is_asymmetric(&str)->bool.

The oracle first captures real frozen-original functions using an isolated
project marker, minimal real SQLite DB and actual config file. It calls
resolve_model/active_model/pending_upgrade and observes configure_for_project's
metadata delta to obtain the prospective pin. No native code produces expected
values. Selection reads must preserve logical rows; original WAL coordination
is not certified as a new native storage implementation. The native process
consumes explicit JSON facts, not a user database, and its results own their data.

## Verification and acceptance

Freeze Cartesian combinations of8 config cases,4 environment cases,5 recorded
markers,4 physical vector states and2 discovery states (=1280), plus12 explicit
Unicode/NUL/empty-BLOB/zero-negative-slot/NULL-marker cases. Every history includes
six forced-model variants. Freeze exact prompt outputs for the declared prefix
families, symmetric IDs and boundary/case variants. Both original platforms must
agree on logical outputs before native implementation; retain platform identity.

Native public-usage tests compare every frozen case, prospective pins, exact
strings/prompts, independent returned results and simultaneous policy instances.
A copied JSON probe runs outside the checkout with sentinel PATH/no model data;
Linux records exactly one exec. Bad requests, missing explicit probe, stale
binaries, altered case IDs, type/field damage and stale nested proof fail.

validate_policy composes the prior26 gates plus policy_release/policy_parity=28.
It forwards explicit policy_probe through every prior validator into test env;
no fabricated paths or skipped missing prerequisites. Aggregate requires both
current platform receipts and26 input fingerprints (prior24 plus policy cases
and oracle). Policy_accepted may be true; M2_accepted must remain false.
Full Python baseline IDs/typing, Rust/fmt/Clippy, previous model parity, benchmark
and original1066 hashes remain required. Preparation stays outside unchanged
runtime deadlines. One fresh whole-plan reviewer; one Critical/Important TDD pass,
no rereview; defer Minors and rule on every declined scope with its cost.

Self-review: policy/data/runtime responsibilities are distinct; physical storage,
config I/O, backend acquisition/factories, document-generation parsing, caching
lifecycle, other model runtimes and M3–M8 are explicitly pending, not certified by
these logical decision tests. No original removal or installed promotion.
