# Native BestSearch and generation-bound preparation

Continue the approved migration on Linux x86_64 by implementing the default search
coordinator, preserving the Python API behavior without replacing the installed app.
Purpose: one serial search owner coordinates source indexing, cold literal lookup,
shared lazy model resources, pinned contextual recovery, owner ranking and PieceSearch.

## Boundaries and choices

Keep algorithms in ken-retrieval, publication/indexing in ken-index, and introduce
ken-search above both. Putting the coordinator in ken-retrieval would form a cycle;
putting source preparation in the coordinator would mix persistence with orchestration.
Use one explicit BestSearch instance per serial worker, with shared resources and a
maximum-two LRU of prepared projects. Its &mut API enforces serial calls on the current
thread and composes the existing Rc model contracts. Process-global threading/MCP
integration remains M7, not an implicit Send/Sync expansion in this library slice.

ContextVectorCache owns SQLite text/model/hash/normalized-vector reuse. Context source
preparation owns canonical owner order, projection deduplication, artifact identity,
publication and authenticated loading. Matrices remain immutable and mapped read-only
from the published NPY files; atomic rename preserves open old-generation mappings.
Mapping assumes application-published immutable files are not modified in place while
in use, as the original. New preparations reject corrupt files before admitting them.
A private mapping/NPY owner confines unsafe lifetime/alignment code; existing workspace
libc/npyz versions may be reused without new external package versions. Public snapshot
constructors keep their owned-vector behavior and numerical reductions.

SearchResources owns one word encoder shared by query/document/word adapters, context
source encoder, EvidenceReranker, PieceReranker, paired reranker, base retrieval profile,
full profile and original runtime identity. A lazy provider is invoked only after cold
empty/exact exits. Production assembly uses ModelFactory, ProductionRankModels, English
stems and fixed registered policies; controlled providers are permitted at this existing
model execution boundary for independent observations, never alternate ranking rules.

## Public use

BestSearch::new(Arc<GrammarCatalog>, Rc<dyn SearchResourceProvider>) constructs no models.
search(&mut self, &mut ProjectDatabase, &ProjectPaths, &SearchRequest) -> Result<SearchResponse>.
prepare(&mut self, &mut ProjectDatabase, &ProjectPaths) -> Result<PreparationReport>.
SearchResourceProvider::build() -> Result<SearchResources> is retried after failures and
cached only after success. A built-in provider accepts the existing explicit ModelFactory,
legacy runtime, registered forest resource directory and pinned model registrations.

A cold search bootstraps source passages when needed without embedding resources; empty
source returns best-empty-source-v1. A single exact owner is ranked through rank_candidates
and presented with best-exact-source-v1. Implicit symbol class lookup becomes a class
request, except file targets. Exact enum/struct/interface declarations retain the older
owner presentation fallback. These exits must not call the resource provider or vectors.

Behavioral search obtains resources, ensures the base source projection outside a read
snapshot, then pins one SQLite source generation through preparation, candidate retrieval,
owner ranking and piece presentation. Native Indexer and index_embeddings provide source
refresh and missing-vector publication without bypassing their generation/profile guards.
Prepared-project keys bind canonical root, actual database filename, source generation and
full profile fingerprint; cache hits move to MRU, successful misses publish then evict to2,
and failed preparation never poisons the cache. Two connections to distinct databases or
profiles may not alias. Old WAL readers keep their source/vector generation consistent.

prepare returns indexed_files=0/owners=0 without resources for an empty project. Otherwise
it performs the same projection/preparation and warms the original Spanish expansion
query and ten paired documents, reporting counts and the full profile fingerprint.
Original request governs intent, exact authority and symbol policies; expanded text only
contributes candidates/ranking evidence. Display budgets retain accepted PieceSearch rules.

## Persistent contextual contract

Use the original vectors.db schema: primary key(model,hash), text collision check, float32
little-endian vectors of exactly768 entries, finite norm within existing1e-5+1e-5 bound.
put_many is transactional and INSERT OR IGNORE matches original conflict semantics.
Order owners by compact sorted-key ensure_ascii=True entity JSON, not UTF8 lexical order.
Full text is path/identity/signature/documentation-prefix800/source; contract and implementation
texts come from accepted owner_view_texts. Deduplicate exact UTF8 text by SHA256 with collision
check; identity includes schema/model/view_model/owners/source_hashes/texts/indexes and excludes
generation. Snapshot key is SHA256 of compact sorted-key ASCII JSON. Publish views.npy,
full.npy and their hash manifest atomically from a temporary sibling; loser processes reuse
the winner. Existing artifact reuse performs no model calls, but revalidates manifest/hashes,
shape/dtype/normalization and immutable source membership. Cache source norms use existing
DenseMath vector norm, while admitted matrices preserve existing axis-wise norm checks.

## Evidence and constraints

Capture distinct new original context/cache histories and complete search/prepare histories
before their native implementation, journal every row and authenticate the frozen1066inputs:
5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038.
Never rerun original pytest roots or recapture accepted model/reference cases. Record model
calls, logical cache/snapshot state and responses cold/warm; exercise changes, failures,
projection repair, exact routes, limits, LRU, database identity and generation transitions.
Controlled source encoders make artifact-byte comparison independent of CPU profiles. Any
new actual model composition uses registered artifacts/profiles and established tolerances;
artifact authentication is against its own observed bytes, not a cross-CPU hash shortcut.

Preserve all old fixtures/model registrations/tolerances and private reserve. Confined native
probes take only physical inputs, database histories and model policy, never expected answers.
Copy and authenticate the three dense BLAS sidecars even for synthetic encoders; retain actual
loader/resource and no-Python/no-child/no-network evidence. Extend the complete local and two
x86 CI chains with actual discovered roots, formatting and strict Clippy, then one fresh final
read-only review, one Important fix pass, no re-review. Seal native+tooling/context support/new
design/frozen inputs with Git proofs; replay outside checkout from archived validators.
Keep raw attempts, receipts and workspaces local/untracked. Commit/push codex/rust-migration
is authorized. No main merge, release, tags, app installation, global quality/performance or
M4 completion claim. Remaining model coverage, public CLI/MCP wiring and M4/global stay explicit.

### Registered-profile diagnostic after complete host qualification

The local Haswell chain and one CI replica pass, but the independently registered
SkylakeX replica produces a different exact owner/piece forest score for a new
registered BestSearch composition. Do not loosen score tolerances or overwrite
the frozen 37-history corpus. First observe only the three new complete registered
compositions on that previously unobserved BestSearch execution-profile pair
(`context=4fd097c7...`, `alignment=1f613df1...`). Reuse the unchanged observer,
frozen1066sources, model registrations and immediate journal. The workflow must
refuse other hardware before invoking the original, so it never repeats the
already captured Haswell compositions or any accepted model/kernel reference.
This is diagnostic evidence, not acceptance. Only independently observed behavior
can justify a supplemental, profile-bound expectation; a native mismatch against
the original on the same profile still requires an implementation correction.
