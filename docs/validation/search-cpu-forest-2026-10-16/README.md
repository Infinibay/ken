# Bounded CPU forest execution — 16October2026

The native forest2560trees and piece forest1280trees previously traversed each
tree in Python, even for ten candidates. Compile immutable branch arrays lazily
and traverse across trees for batches of at most128rows, using32row scratch
blocks. Keep the existing evaluator above128rows: a prototype regressed at1200
rows(232ms→360ms), so it is deliberately not selected there. No model weights,
feature schema, thresholds, model fingerprints, candidate pool or leaf-addition
order changes. NumPy cumsum retains sequential tree addition, including float
cancellation; no training library/framework or new dependency at runtime.

Source-free warm local10row timing gate20ms first failed both models: native
55.042ms,piece25.559ms. After execution change:2.953ms and1.285ms. These are
interpreter timings, not end-to-end search latency or a CI timing assertion;
concurrent source-evidence collection was active. Complete response time/RAM
must still be measured with the final profile. Compiled arrays are cached once
per model and scratch space is bounded by32rows and at most4096trees.

All400exposed query groups/3988actual piece candidates produce BYTE_EXACT scores
with the1280tree model. Full original200purpose/piece replay:0purpose parser
changes,7resolved-purpose feature changes,0piece order changes,0final order
changes. Thus the original frozen191/200top1 and197/200Recall are retained in
this trace replay; this is not a new independent benchmark. The intended purpose
bugfix resolves auto through interpret and recognizes requested regression/test
nouns and Spanish Localiza while respecting earlier implementation/clause
boundaries. Its new-query quality is not inferred from the old200replay.

Full current tree suite exit0:14918passed,10preexisting xfail; progress dots/x
counted because project and command both request quiet output. Log SHA
b2078994b25a2995e92626b1ed97d33ce6cee6baa8cc5faabc8ca7b8c9e272d5.
Mypy356source files clean. Regression tests cover empty/single/mixed-depth trees,
128/129dispatch, threshold equality, cancellation and canonical fingerprint
stability. A<=to<split mutation failed the boundary test; exact source restored
and targeted72tests passed. No acceptance targets or tests weakened.
