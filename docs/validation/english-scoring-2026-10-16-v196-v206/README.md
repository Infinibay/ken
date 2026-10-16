# English scoring diagnostics196–206

The human narrowed the goal to English before these controls:120original and
120new queries, from fixed existing language metadata,>=108strict top1 in EACH
cohort. English Recall10 stays118/119. Exposed development is not independent
acceptance, and the reserve remains CLOSED. References were not changed.

Current production sourcecccea45b (intent201) measures113/95English top1 in
actual fullMCP. Source195before that correction measures113/93. All diagnostics
below, unless explicitly stated, use the unchanged195native10pools and original
published68M1024scores, never adapted weights. None reached108in the new cohort.

## Why the old audit was rejected

Old152feature vectors do not reproduce current native scores: query052
dynamicRef._callRef differs by0.002826042115771088. The failed exact check and
partial outputs are preserved. The guard was not weakened. Fresh196captured
150English symbols,128normal/22exact bypass, with all251native feature columns,
exact model predictions, exact current MCP orders and query/card-hash matching
before reuse of closed1024neural scores.198audits9800new-English rows and33
error-union cases:27RRF errors and20neural-only errors. Per-case payloads retain
all251values and every tree path/threshold/leaf difference for both candidates.
The trees group leaf deltas by first divergent split: interaction accounting,
not isolated causal feature importance or SHAP. These are195traces; six201intent
queries now have different native scores/pools and must not be labeled195data.

## Findings and isolated controls

RRF discards score margins. Six of27English final errors tie exactly and break
toward native order;20have a greater reciprocal-rank sum for the incorrect
candidate; one target is outside10. Fusion loses13neural top1 hits and gains6.
The six exact ties are among those13losses. Scores have different scales and
are not calibrated probabilities. Population-z equalmean improves new93to97,
but raw neural order already reaches100. Original113is retained by zmean.

Pure CodeRank implementation similarity reaches75new; contract59; mean68;
implementation+neural zmean94. Replacing the forest with one embedding channel
is not an improvement. Zeroing callable-kind or proposal-RRF families also
does not solve the problem: see all native/RRF outcomes in results.json. A large
local tree margin is not evidence that globally deleting that feature helps.
These ablations are diagnostics, not deployable feature corruption.

The200fixed-pool source-role probe gains2(113/95) but its initial grammar later
failed three existing production verb-test guards. Its helper remains research
only. The corrected201implementation is verified separately in actual400MCP
and committed with fullsuite/mypy/cost proof in requested-test-role201docs.

Explicit code operatorsAND/OR are dropped by normal stopword processing.202adds
a separate literal-operator preference without changing the index:113/94RRF,
110/101raw neural,113/98zmean. Only two queries trigger; ANDgains one. No pool
members are removed. This does not prove arbitrary behavioral constraints.

204distinguishes requested test entries from test helpers by canonical nesting
and conventional declaration evidence.9tests pass including a Java annotation
and a nested function namedtest. Results:113/95RRF,110/103neural,113/99zmean.
It does not claim a test runner will collect the declaration. All are isolated
replays: their gains cannot be added to201or202without a combined measurement.

206attempted that combination but correctly failed before producing predictions:
normal MCP responses do not contain debug signals. No scores were invented and
there is no206accuracy result. A next capture must authenticate reused card
scores and obtain actual debug scores for the six changed201queries first.

## Reference review and next information to investigate

203source review confirms the intended unique full matches in attrs172and
boltons156. In Ajv042, additionalItems.validateAdditionalItems AND
unevaluatedItems.code satisfy all literal conditions; the question omits the
distinguishing starting-position rule. This ambiguity is recorded separately;
fixed Gold and historical results remain intact. The reviewer disclosed an
accidental historic Ken snippet exposure for attrs, and no reserve was opened.

251term coverage is a bag of semantic maxima; it does not preserve argument
coupling, conditions or execution order. Attrs172needs kw_only=True AND
init=False on the SAME attribute, while the incorrect candidate assigns those
properties to different fields. Earlier lexical-scope cards expand descendants,
not enclosing object-literal metadata or cross-file imported type contracts.
Those are information hypotheses to test; no new effect is claimed here.
Generic clause/facet splitting was already tested and failed in181–184; do not
repeat it. W2original+docless code remains an earlier102/120English replay,
not an activated setting or a result that can be summed with new preferences.

Each compressed payload has compressed and original SHA256checks. manifest.json
maps each to its exact source path; restore into a separate research directory.
No reserve, modelweights, release, tag, version bump or PyPI publication.
