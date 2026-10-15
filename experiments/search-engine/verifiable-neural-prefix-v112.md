# v112: spend neural CPU on a fixed prefix without losing candidate recall

The closed68M FP32 top10 control v110 reached identity175/200 with RRF50, but
reranking alone took median2981ms/p953308ms and720MB process RSS. This is NOT a
joint utility result or full Ken measurement and is too expensive to adopt
without further cost controls. All three v110 arms remain reported.

New fixed development control, registered before executing/scoring: score only
the first THREE native candidates with the same68M FP32 model, padding50283,
batch4 runtime, max512/only-second truncation, threads2/1, and v102 fixed cards.
Apply exactly the same raw/RRF60(0.5)/RRF60(0.25) policies within that prefix;
append positions4–10 in unchanged native order. Do not discard any of the10
identities, modify context, train on labels, tune weights, or access private
acceptance. Cases whose correct piece is below position3 can still be misses
for top1; keeping them in top10 is not a top1 success.

Two new regression tests require the unchanged10-member permutation and suffix,
exact-query bypass, and rejection of a scored prefix longer than the retained
pool. Both tests failed on the previous interface before implementation. Keep
all200 cases and all preset arms; no search over prefix sizes after scoring.
Run actual3-pair inference, not just old10-pair scores, and close all outputs
before reading already exposed development Gold. Report replay-only costs and
identity separately; a changed winner still needs independent evidence review.
