# Contextual proposal and coarse ranking control v38

Keep all original 400 development queries, references, decisive anchors, strict
scorer and output budgets. The private reserve is unused. This is a prepared
development control, not promotion or an actual API performance claim.

v36 adds one contextual family to the static/translated proposal family. It
encodes every source owner independently before requests are read; the previous
query-pool encoding cache is not used. Report original source eligibility for the
RRF prefix100 and broad union separately. More broad candidates do not satisfy
the first100 candidate gate.

Recompute the 227 existing source features on every complete v36 proposal pool.
Do not reuse old pool-relative ranks, RRF or document-frequency summaries. Add
eight features: for original and locally translated CodeRank cosine, each raw
score, distance to query-pool maximum, range-relative score and reciprocal rank.
The contextual scores for every combined owner are measured against the full
source index, not assigned zero merely because an owner missed the code top300.
The entire producer reads public requests and sources only, never labels.

Use the same pre-existing core-v18 LightGBM parameters, 16 repository-held-out
folds, and the corrected complete-owner eligibility target from v27/v32. Every
prediction excludes its entire repository. Train no thresholds or query-specific
weights. Export the numeric forest and check exact native/exported parity.

Measure held-out source eligibility at ranks1,5,10,12,20,32,50,100 and broad.
Separately grade all400 final responses using the original presenter and strict
evaluator, retaining retrieved/complete/query-cue presentations as separately
reported controls. All failures, unanswerable hypotheses and missing candidates
remain in their original denominator. Source coverage is not visible accuracy.

Record every input/model/source hash, dimensions, fold training repos and CPU
provider. These 235-feature models cannot be loaded through the existing
227-feature production interface. Any later adoption needs an explicit new
profile/feature version, source-only query integration, actual API/CLI/MCP
validation and final latency/RAM measurements.
