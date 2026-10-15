# Prospective shadow: rejection versus fine ordering

Registered before root parses any of the200new public case rows or any new Gold.
User requests initial Ken rank → discard nonsense → order relevant survivors.
The raw-model baseline comparison v98 remains unchanged and immutable.

Hypothesis: a small cross-encoder may provide a useful negative signal while
Ken's existing ordering remains stronger among plausible candidates. Compare:

1. Existing Ken order on its first10typed cards.
2. Ettin17/32/68 raw-logit order on those same10cards (v98 primary).
3. Per-model conservative rejection then raw-logit order (v98 shadow).
4. The identical rejection then ORIGINAL Ken order among survivors (this shadow).

No second forward/model, no new candidate or card, no query-specific rule or HPO.
Threshold remains exactly v98: inclusive minimum score among40faithful correct-unit
calibration cards, sufficient or sparse, after principal judgments close. This
is a small correlated calibration set; zero empirical false drops is no guarantee.
Exact unique lookup bypasses retain existing authority. Missing pools stay failures.

Procedure: close all200raw model outputs, all60calibration blind judgments and
all principal blind judgments; open only calibration Gold to fix thresholds;
generate both shadow selections from fixed first10scores. Blind-review any new
query/card pairs selected by preserve-Ken order; re-use a sealed judgment only
for byte-identical query/card input. Consumers remain cross-curator and never see
the other principal Gold. Seal final combined judgments before any principal Gold
is opened. No main Gold, main outcome metric or model-specific choice can enter
threshold fitting or the two fixed ordering policies.

All policies use the original200denominator and same per-kind/evidence/source
gates. Report identity, joint utility, false drops, retained correct-piece coverage,
known-irrelevant rejection and abstention separately. Do not call all non-Gold
candidates irrelevant. Scalar same-score filtering cannot improve neural top1
on its own; preserve-Ken ordering can select a different survivor and is therefore
judged independently. New/ambiguous alternatives require the same source audit.

CPU timing/RSS of the model forward and full prepared v98 pipeline are measured
live. Shadow choices are offline replays of fixed scores/cards, labeled as such;
do not claim another measured full-pipeline latency or add percentile timings.
