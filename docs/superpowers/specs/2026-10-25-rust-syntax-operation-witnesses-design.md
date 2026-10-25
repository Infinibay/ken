# Native syntax operation witnesses

Continue the approved Rust migration inline on Linux x86_64. Complete the
Tree-sitter backend of source operation observation for Java, JavaScript and
TypeScript. This backend composes later with a separate Python AST backend;
full OperationWitnesses/SymbolRanker/PieceSearch and global migration stay pending.

The contract is the frozen OperationWitnesses._observe_body, not a general
execution analyzer. SourceCatalog owns immutable lines, canonical owners and
extents; GrammarCatalog owns verified native grammars; SyntaxOperationWitnesses
owns file parse/result caches and the two observations: invocation and
returned_flag_refresh. All source comes from catalog snapshots, joined with LF,
including when current disk content changes or disappears.

Caller: SyntaxOperationWitnesses::new(Arc<SourceCatalog>,Arc<GrammarCatalog>),
for_owner(&mut self,&EntityKey)->SourceResult<BTreeSet<String>>. supports(path)
names .java/.js/.mjs/.cjs/.ts/.tsx. Unknown owners or an unsupported extension
return explicit typed errors; Python is not silently assigned empty evidence.
The future full observer router will own dispatch and original unsupported-file
fallback. A returned set is independent of the cache. No new dependencies.

Preserve original root selection: intersect extent, collect exact frozen callable
node kinds wholly inside it, choose earliest start and widest end, retain first
on ties, require matching end line. Inspect only the selected body's descendants;
skip nested callables, including arrows/generators/lambdas. Calls/new expressions
and explicit constructor invocations supply invocation. Return refresh requires
binary ||, parenthesis unwrapping, assignment on the right to the same raw target
with Python whitespace removed, and a call/method invocation assigned. The raw
comparison intentionally also removes whitespace inside string literals; do not
silently replace it with Python AST equivalence or claim runtime execution.
Preserve Tree-sitter recovery behavior; do not reject the entire tree merely
because it contains an error. Grammar preparation failures remain errors.

Alternatives: one generalized AST/CST observer would mix two distinct contracts.
RustPython0.4 was inspected as a Python backend, but its surrogate replacement,
identifier handling and pre-PEP701 string lexer need a separate compatibility
solution. Porting this complete existing CST backend requires none of that work.
This bounded decomposition is the implementer's choice under the user's
continued migration authorization; it is not acceptance of Python witnesses.

First capture independent original observations before Rust implementation:
all six suffixes, invocation/new/constructors, refresh target/call shapes,
parentheses/whitespace/string-literal behavior, nested callables, unrelated
owners/extents, recovery, unsupported backend inputs and immutable snapshot/cache
behavior. Use original catalogs and explicit admitted synthetic owner extents for
otherwise unextractable declarations; never substitute the original observer.
Run four disjoint original roots once. Keep all1066frozen files and accepted
model/fusion/view/preference references unchanged; no original recapture.

Validate caller tests RED→GREEN, actual pinned grammars, input-only native probe,
full affected native suites/fmt/Clippy, tamper/tooling checks, x86 CI and
Git-authenticated archived replay. Keep known contextual runner variability
separate and retain failing evidence; numerical checks stay unchanged. One fresh
final scoped review, one Important repair pass and no re-review. Preserve raw
locally outside Git; push to the existing migration branch is authorized.
