# Executable GoF catalogue

This implementation milestone gives each of the 23 GoF concepts a canonical
KenQL query over evidence, with source-based positive and negative fixtures.
It does not equate the 60 proposed implementation variants with 60 implemented
variants. Each executable variant declares the fixture languages actually tested.

Canonical queries share the same engine as user queries. The files remain TOML;
no Python pattern dispatch or hard-coded pattern-name classifier is introduced.
The old root signatures remain available as compatibility queries; canonical
`gof.*` queries select tested variants. The default pattern interface will use
canonical variants, and compatibility queries must be explicitly identified.

Strengthening requirements: Observer needs insertion of a parameter into the
same collection notified; Command needs a separate invoker using the command
contract; Decorator needs forwarding the same slot plus another call; Adapter
maps a different slot; Prototype passes state into the returned construction;
Memento restores state from the snapshot parameter; State constructs a successor
in the transition itself. Joins preserve identity of roles and receiver storage.

Generic IR additions describe collection insertion, callback iteration, member
bases and element writes. They name operations, never patterns. Collection API
models are syntactic idiom evidence, not proof of a library's runtime semantics.
Generators decorated with contextlib contextmanager/asynccontextmanager are
resource scopes rather than exported Iterator implementations.

Remaining capability gaps stay visible as design variants, including arbitrary
framework event buses, generic typestate substitution, ownership proofs, remote
proxy transport models, algebraic interpreters and whole-program alias resolution.
A matching query is structural evidence, not a guarantee of design intent or
runtime correctness. Resource limits yield incomplete outcomes, never absence.
