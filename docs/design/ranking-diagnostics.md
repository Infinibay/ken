# Explain the actual ranking decision

The current development retriever contains an acceptable piece in197/200 top10
lists, but native top1 identity is168/200. Quality targets remain>=90% correct
piece plus sufficient visible source, Recall10>=95%, CPU/modestRAM. New reranker
experiments pause at the user's request; diagnose the actual native Ken ordering.

Four questions define the diagnostic:

1. Was the acceptable piece proposed, and which canonical owner represented it
   when class/module/file grouping selected its position?
2. What exact feature values and tree branches gave the selected owner a higher
   numeric score than the acceptable owner?
3. Did exact identity priority or stable proposal order decide the result instead
   of the numeric score?
4. Which signals recur across failures, and which information was missing at the
   retrieval, owner-ranking or piece-grouping stage?

NumericRanker owns explanation of its forest. Comparing two feature vectors must
reproduce the production predictions and score margin exactly, with threshold
comparisons, paths and leaf values. A forest has interactions rather than a fixed
weight per feature. Grouping a tree's leaf-value difference by its first divergent
split is an exact accounting of that tree's margin, not an isolated causal effect
or SHAP attribution. Both paths remain available so the accounting is auditable.

RankingTrace owns a request-local optional observation: model fingerprint, feature
schema/values, proposal signals, canonical identity/source hash, scores and final
positions. EvidenceReranker passes its actual computed matrix and results to the
trace, with zero feature recomputation. No source body is copied, no telemetry is
sent or logged automatically, and ordinary response shape/ranking stay unchanged.
Query content is optional when exporting a trace; hashes identify inputs by default.
Exact bypass and stable ties have explicit policies; absent numeric features remain
unavailable rather than fabricated. Reusing a trace replaces its current snapshot.

Representative caller: trace=RankingTrace(); matches=ranker.rank(request,
candidates,descriptions,trace=trace); trace.compare(matches[0].entity,alternative)
returns the actual pair margin, branch paths and differing feature values.

The benchmark diagnostic runner must freeze producers and capture ALL200 native
orders/traces without reading Gold. Only after complete hash-pinned closure may a
separate analyst use the already exposed development references to select comparison
pairs and classify failures. Hidden acceptance stays closed. Report successes too,
all failures/missing candidates, and candidate/order parity with the old snapshot.
Do not update weights or claim an accuracy improvement from instrumentation alone.

Boundary tests: hand-computable forest with interactions/cancelling tree effects;
threshold equality; exact score/margin reconstruction; finite/schema checks;
identical ranking with tracing enabled/disabled; true feature values/proposal signals;
stable ties; unique exact bypass without encoder work; captured data cannot mutate
caller candidates/matrix; no full source or automatic query-content export.
