# Native public search on Linux x86_64

The user requests autonomous completion of the existing Rust migration. This
slice connects the implemented default BestSearch to real public callers. It
does not certify the pending Intel CT2 or SkylakeX numerical profiles, replace
the installed Python application, or complete the remaining global milestones.

## Concepts and responsibilities

- **Compact presentation** projects a verified search response into the original
  human-readable text without selecting, ranking, reading or changing evidence.
- **Native search installation** describes explicit grammar, ranking, model and
  runtime files. It resolves deployment paths and creates lazy registered owners;
  it never discovers Python packages or launches an interpreter.
- **Search application** owns one native engine and opens the selected project
  database. Public CLI and MCP callers share this application and response policy.
- **CLI boundary** parses the original search arguments, selects text/JSON and
  writes the original exit code and streams.
- **MCP boundary** handles newline-delimited JSON-RPC, advertises the implemented
  find operation and delegates file/symbol default search to the same application.

Representative use is `ken-rs search-symbols Cache.lookup --path PROJECT --json`
or an MCP `tools/call` for `ken_find` with the same query and scope. Exact and
empty searches remain cold. General queries use the existing registered Potion,
context, Ettin and translation owners and existing ranking policy. No controlled
model, precomputed answers or Python fallback belongs in the application.

## Decisions

Reuse `ken-search` rather than duplicate retrieval inside transports. Keep the
small pure compact renderer in `ken-retrieval`; public preparation failures and
installation assembly belong to `ken-search`. A separate application crate is
unnecessary for these responsibilities. Environment/executable discovery belongs
to the CLI boundary; the engine consumes explicit immutable resource inputs.

An explicit versioned installation JSON is preferable to inferring libraries
from a development checkout or Python environment. Relative paths resolve against
the manifest directory, allowing a copied installation. User model configuration
and legacy compatibility identities remain explicit; no new package versions.
Missing installations produce actionable preparation errors. Loading the manifest
must not load native runtimes or model weights. Production packaging/default
discovery remains M8 work.

Preserve original `auto`/`compact` file/symbol semantics, query joining, purpose,
piece kind, result/output budgets and JSON/text behavior. `compact --json` is an
error. `evidence` and `legacy` require their own implemented execution paths;
they must never silently invoke BestSearch. Unimplemented MCP scopes are explicit
until their migration slices land; an unsupported request is not a successful
empty result. The installed Python tool inventory stays unchanged.

## Validation and evidence

Observe only newly migrated public behavior against frozen original1066 sources
(`5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038`).
The pure renderer reuses previously preserved response inputs, but its text is
observed independently for the first time; it does not repeat model inference,
index construction or accepted original tests. Preserve script, source/input/output
digests and raw stdout/stderr before freezing its fixture.

Exercise real CLI and stdio MCP processes, Unicode, multiple fragments, stale and
partial cards, empty results, warnings, omitted results, diagnostic JSON number
formatting, argument failures, absent projects, malformed protocol requests,
installation relocation and cold exact/empty paths. Registered non-exact paths
must execute the real model owners. Strict fmt/Clippy and existing affected suites
are mandatory. Use one fresh final read-only review and one Important repair pass.
Keep all evidence/workspaces local/untracked by user instruction.

## Stdio binding and public database lifetime

This binding explicitly supports the 2025-11-25 MCP lifecycle and tool protocol.
It negotiates that supported version, advertises only native file/symbol search,
and keeps other scopes and the 2026-07-28 protocol pending for M7. Follow the
[versioned lifecycle](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/lifecycle.mdx)
and [tool error contract](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx).
Physical frames are bounded to 8MiB; malformed frames are drained and reported
without corrupting the next request. Notifications produce no response. Tool
argument validation is distinct from an invalid CallToolRequest envelope.

The frozen original SDK answered the first seven observed protocol requests but
did not answer the final isolated-surrogate query within 120 seconds. Preserve
that failed observation and all completed rows. Native framing carries existing
PythonText into the domain and responds; this is an explicit correction of a
transport hang, not a claim of byte equivalence for the original failed case.

The public application binds its current database to device/inode/path, checks
that binding around opening it, and clears prepared source catalogs on binding
changes. Model owners remain loaded. This prevents an atomically replaced database
with the same generation from reusing another database's source context. The
application serves one configured MCP project; changing the public binding may
reprepare context, while the underlying BestSearch library keeps its original
two-project cache policy. This does not add a hostile filesystem ABA guarantee.

For source-bound public qualification, use a copied Rust integration caller and
the actual copied CLI ELF outside the checkout. The caller may spawn only that
declared CLI; the CLI may create threads but no child processes. Stage explicit
authenticated native/model resources, retain actual CLI/MCP streams and loader
logs, and audit exec/process/network calls. Test-only resource routing belongs to
the caller, never production behavior. The caller contains assertions; application
inputs contain only configuration, source, database state and public requests.
