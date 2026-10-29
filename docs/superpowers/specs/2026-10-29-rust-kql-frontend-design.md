# Native KQL2 syntax and module preparation

Continue from3d3a2961 on Linux x86_64. Deliver the complete KQL2 syntax frontend
and immutable explicit library/model preparation as a coherent native slice.
This precedes BOTH compiler backends: indexed scans and shared relational plans;
parsing/preparing syntax is not execution or a claim that M5 is complete.

Caller: ken_query::parse(text,source,ParseLimits) -> Result<File,ParseError>;
resolve_libraries(&File,&BTreeMap<String,File>) -> Result<File,ParseError>;
specialize_models(&File) -> Result<File,ParseError>. Typed AST keeps query Expr
and source SourceExpr distinct recursively; all spans are UTF-8 byte offsets.
AST supports faithful Python repr for the following compiler identity step.

Concepts: Lexer owns contextual tokens/regex validation, Syntax owns immutable
records, Parser owns declarations and context/Pratt grammar, LibraryResolver owns
an explicit immutable module snapshot and qualification, ModelSpecialization owns
signature checking, hygienic substitutions and bounded instantiation.
IndexedAlternatives owns the ordered128-branch expansion used only by indexed
compilation; PredicateComponents owns dependency SCCs and stratification checks. Neither
parser nor preparation opens source projects/databases or evaluates host code.

Preserve defaults2MB input, regex4KB, nesting96, model instantiation128; original
code/message/span diagnostics, named argument speculation and last-span rollback;
all query/constraint/effect/BODY productions and both expression dialects. Preserve
ordered declarations, parameters, blocks, arguments and generated model IDs.
Rust entry strings are UTF-8; expose a byte entry that rejects invalid UTF-8 at
span0 just as original does. Match original regex syntax under its restricted
extensions/backreference policy without compiling input to a huge automaton.

Keep installed Python/frozen original1066 untouched. Authenticate before/after new
observations; retain typed class tags, ordered tuples and original repr in the
new bounded fixture. Do not rerun accepted frontend/linker/model/CPU/CI matrices.
Use locked dependency versions already available. Continue existing branch in
place as authorized; raw/workspaces local. User opts out of repeated approvals
and per-edit testing; execute inline, group validation, one fresh final reviewer
and one regression/fix pass, then authorized commit/push. Full KQL compiler,
relational/indexed execution/BODY runtime and public config/CLI/MCP remain next.

Native safety: AST/recursive-helper ceiling512 is independent of configured
syntactic nesting. Flat else chains and source generic/function type arguments
use explicit stacks; guarded recursive grammar/rewrites use the already pinned
stacker0.1.25 on small caller stacks. Original emergency RecursionError location
is host-stack dependent: one deep-type stress fixture preserves code/message and
a valid byte span rather than matching that incidental cutoff token. Default
nesting96 and all other captured diagnostics remain exact. Caller-supplied ASTs
are validated iteratively before preparation; this does not promise safe arbitrary
unbounded deserialization or mutation of public records.
