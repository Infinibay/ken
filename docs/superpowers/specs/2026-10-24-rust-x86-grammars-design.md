# Authenticated native grammars on Linux x86_64

The user approved Linux x86_64 support. Retrieval/BLAS now works on that host,
but GrammarCatalog currently rejects its architecture. The next search slice
needs syntax observations, so remove that concrete preparation barrier before
adding public search composition. This is a small extension of the existing
resource registration, not a new parser implementation.

## Caller and responsibilities

```rust,ignore
let grammars = GrammarCatalog::prepared(Path::new("sdk-linux-x86_64/manifest.json"))?;
let parsers = ParserRegistry::new(grammars);
let outline = parsers.parse(Language::Python, b"def read(): return 1\n", "reader.py")?;
```

The grammar lock owns immutable archive/library/revision/license identities.
Preparation authenticates the archive before publishing its selected modules
and licenses. GrammarCatalog owns host selection, manifest checks, native
library authentication and lifetime. ParserRegistry retains all language and
extraction rules. No parser, ownership, feature or search rule moves to setup.

## Approach and limits

Reuse the official **1.8.1** Linux x86_64 bundle, keeping pack revision
`33602ce7d17edd24cc00a1a9fe7129a61138f8ef`. Rebuilding every grammar would add a
second compiler/toolchain provenance problem without a required behavior change.
This choice is the executor's implementation decision under the approved x86
extension. Preserve the existing ARM bundle entries exactly.

The official release asset is
`https://github.com/xberg-io/tree-sitter-language-pack/releases/download/v1.8.1/parsers-linux-x86_64.tar.zst`,
19,144,528bytes, SHA256
`f670f0582aa186df8da69d60624653df3d482f85546e162bdfaedbc77d2cf390`.
Inventory all13selected dynamic modules from those authenticated bytes, keeping
the same grammar revisions, symbols and license texts as the pinned release.
Store only registration metadata and actual regression fixtures in Git; archives,
SDK modules, originals and execution receipts stay local/Actions artifacts.

Rust1.95.0, tree-sitter0.25.10, pack1.8.1, Python3.12.9/Unicode15 and all Cargo
versions remain unchanged; Cargo.lock confirms tree-sitter0.25.10 and remains
the version authority. No new dependency, unsupported
host fallback, architecture aliasing or unchecked dynamic loading.

## Acceptance

- An actual prepared x86manifest loads all20grammars/19parsers and preserves
  the44extension inventory. Foreign-platform, incomplete, missing or corrupt
  resources retain their existing rejection/isolation behavior. Held syntax
  trees outlive catalog drop without unloading their grammar.
- Capture only the new x86original parser observations/scoped suites, once,
  before enabling native x86loading. Use KEN_PARSER_ORIGINAL_GRAMMARS to point
  at the separately prepared SDK. Existing ARM originals remain immutable.
- Compare the complete native parser output and syntax records with that
  actual x86oracle outside checkout, with empty PATH/HOME, actual Linux
  exec/connect and loader evidence, source/binary/module identities and bounds.
- Complete affected syntax tests, doc tests, grammar/parser tooling,fmt and
  strict Clippy. Exercise all8incremental index roots locally with the prepared
  SDK as integration smoke; that alone does not accept complete x86M3/indexing.
- Require native Linux x86_64 and regression checks on both existing ARM hosts,
  one final fresh review, one defensive Important/Critical repair pass if needed,
  and an independently replayed local receipt. Do not recapture approved oracles.

The receipt may accept **Grammar_x86_64** only. M4 search composition, x86model
profiles/full indexing, global M3-on-x86, CLI/MCP, M5–M8 and replacing installed
Python Ken remain required separate work. Preserve all1066frozen originals and
accepted M4c2 receipts; no release,tag,merge or installed-command replacement.
