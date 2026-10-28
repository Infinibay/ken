# Python AST operation witnesses on Linux x86_64

Continue the authorized inline migration: implement the Python backend of frozen
OperationWitnesses and its complete Python/CST/unsupported-file router. Preserve
Python3.12.9 AST semantics, catalog snapshots and canonical owner authority.
No installed-app replacement, ARM/macOS certification, numerical changes or
recapture of previous original observations/pytest roots. Push authorization and
keep-local artifact/workspace preference persist.

Responsibilities: PythonOperationWitnesses caches one parsed file and immutable
results per owner. PythonAst semantics owns Python3.12 admission, source positions
and structural expression equality. OperationWitnesses only dispatches to Python
(.py/.pyi), existing SyntaxOperationWitnesses, or unsupported-file empty evidence.
Unknown catalog owners remain typed errors. All code is read from immutable
catalog lines joined by LF, never reopened from the working tree.

Representative caller: OperationWitnesses::new(Arc<SourceCatalog>,
Arc<GrammarCatalog>); for_owner(&mut self,&EntityKey)->SourceResult<BTreeSet<String>>.
Python module parse errors produce no observations, matching ast.parse failure.
Select exactly one FunctionDef/AsyncFunctionDef/ClassDef by normalized AST name,
end line and extent containment; catalog key names remain raw. Invocation visits
only owned body statements, excluding deferred classes/functions/lambdas/defaults.
Direct observations include causes except None, family from a called Name only,
adjacent get/subscript-write/append triples in body/orelse/finalbody and the exact
two-value return-Or/NamedExpr/Name/Call flag-refresh pattern. Returned sets are
independent of caches.

Approaches: raw Tree-sitter matching loses CPython expression identity and parse
admission. RustPython0.4 has known string/identifier/PEP701 gaps. Selected by the
implementer under continued migration authorization: pinned published
rustpython-ruff_python_parser0.15.8 (MSRV1.92, compatible with Rust1.95) for native
syntax, with a focused CPython3.12 semantic projection. Do not use Ruff's generic
ComparableExpr as ast.dump equality: it deliberately erases contexts and other
metadata. Reuse existing frozen Unicode15 identifier and lossless string literal
logic; preserve string kind, bytes, numeric value/type, f-string semantics and
nested expression shapes. No Python subprocess or interpreter library in native
execution. Parser limitations discovered by conformance tests must be repaired
explicitly, never silently approximated or relabelled original outcomes.

Capture first independent full observations with the frozen1066tree and pinned
Python3.12.9 before implementation. New source cases cover .py/.pyi, functions,
async/classes, roots/extents/ambiguity, nested traversal boundaries, cause shapes,
snapshot adjacency/control blocks/AST equivalence, return refresh, invalid file
syntax, Unicode15/NFKC, numeric/string/bytes/surrogate/f-string equivalences and
snapshot/cache independence. No original pytest suite is reexecuted. Preserve
raw observer/request/output and reject overwrite/tamper/source drift.

Validation: RED→GREEN native caller/corpus tests, input-only confined native probe,
full core/retrieval/model prerequisites and fmt/Clippy, tooling/protocol tamper,
Linux x86 CI, Git-authenticated sealed archive and isolated replay. Report exact
observed scope; SymbolRanker/PieceSearch, remaining models and M4/global remain
pending. One fresh final read-only review and one Important repair pass, no
implementation agents or re-review. Preserve every raw epoch locally.
