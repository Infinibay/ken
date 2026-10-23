# M3d native common program model

Complete common-ast/1 model codec, annotation TypeRefs, ordered structuralIR
normalization, lexical declarations/references, Environment lookup and body ranges.
Actual macOS arm64/Linux aarch64 native processes:90IRinputs,204types,26codecs,
1240lookups;14original top-level failures retained.7Rust/28tooling tests perplatform.
135original tests captured once perplatform; unchanged source/parser/model proofs
reused. Original1066files preserved. Compressed archives keep full provenance.

Replay from repository root:
`PYTHONPATH=. .venv/bin/python docs/validation/rust-migration-2026-10-23/m3-program/VERIFY.py --current`

Acceptance is M3d only. Source→structuralIR production/linking/store remain M5a;
M3 incremental indexing and M4–M8 remain pending. Required fresh whole-plan review
follows functional acceptance; its result/repair must close before advancement.
