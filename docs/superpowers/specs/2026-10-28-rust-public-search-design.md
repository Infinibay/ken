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
