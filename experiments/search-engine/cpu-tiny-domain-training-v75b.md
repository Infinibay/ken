# Tiny domain adaptation75b: close producer bindings before fitting

Variant75b preserves every model, training parameter, held-repository exclusion,
candidate, source projection, reference and acceptance criterion in75. Original75
completed its untrained400-query float32 baseline, then was deliberately stopped
before its first fit. Its original script/freeze/output remain preserved; no
adapted75 score or quality result exists.

Independent review found two prospective defects before any fit or quality look:
75 recorded observed hashes without checking original producer bindings for the
training labels and69 fusion scores, and raw-score ties used original pool order
despite the protocol specifying69 order then pool position. The actual167,360
rows and fusion scores were independently verified correct. This variant enforces
the existing tie specification and expected original producers; neither decision
uses measured quality.

Before reading arrays, require the original66c/69 producer registration hashes and
their expected DATA SHA256, and the original72c binding of69's score array. Pin
all three producer registration hashes. A swapped-label or reordered-score file
must fail before training even when its shape and qids still match. Retain68
parent/teacher row bindings and source/current-file hash checks, and recheck all
expected inputs before the first fit and after the last prediction.

Reuse only75's completed untrained float32 baseline. Pin its final registration,
score array and export receipt hashes; verify original75 source freeze, script,
all input hashes, zero trained folds, all400 IDs, source projection/policy and
parameters. Compare every cached native tensor exactly to official safetensors,
bind cached ONNX to its export receipt, and recompute one first-pool pair for the
lexicographically first nonexact query in each of16 repos. Selection never uses
labels, logits or relevance. Require bit-identical cached logits before copying
baseline scores and graph unchanged. No adapted cache is reused.

Pause after these checks for independent pre-fit review. Train exactly the same
16 fresh pretrained resets/3 fixed epochs/CPU parameters and groups described75.
No checkpoint selection, parameter sweep, secondary learned fusion, held-repo
training or private-reserve access. Apply69-order→pool-order ties in both raw
and pair-rank formation for equalRRF60. Evaluate the same four prepared controls
only after all fixed fits/predictions and source bindings pass. Retain all failed
and negative results. The integration gate remains at least5 strict hits above
API74b's286/400; prepared controls do not certify API resources or acceptance.
