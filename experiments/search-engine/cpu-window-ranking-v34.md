# CPU source-window ranking control v34

Research continuation within the approved search-engine plan. Success criteria,
original references, the strict scorer, all 400 development queries, source
snapshots, output budgets, and the unopened private acceptance reserve stay fixed.

The broader static/translated proposal control reaches 383/400 eligible owners
in its first100 and390 in its broad union. Its source-only numeric ranker reaches
236/400 strict top1 with retrieved evidence. More candidates alone do not solve
ordering. The same broad numeric ranker places an eligible owner within its
first20 for382/400 queries, within100 for389. These are diagnostic source bounds,
not visible-answer accuracy or a completed98% candidate gate.

This control changes the learned object from a potentially sufficient owner to
an **answer hypothesis**: a canonical owner plus a bounded, faithful source
window or bundle. The positive target requires every original anchor of one
original alternative in the actual proposed visible spans, with matching identity
and bytes. This does not modify the evaluation reference or scorer.

## Public hypothesis producer

- Inputs: only public query, root/source snapshot, original and locally translated
  query text, and source-only owner proposals. No case language/purpose label,
  alternatives, anchors, answerability, or relevance scores enter the producer.
- Proposals: contiguous windows and complete statement windows within verified
  owned regions, plus bounded nonoverlapping bundles. At most40 visible source
  lines per hypothesis. Nested-owner gaps remain gaps; no arbitrary sibling or
  module borrowing. Incomplete ownership/delegation cases remain counted misses.
- Fixed initial cap:12 hypotheses per owner (four structurally seeded, remaining
  query windows, two region-edge slots and two disjoint-bundle slots, with spare
  capacity filled deterministically). The source implementation and its quota/
  tie ordering are frozen by receipt before scoring. A coarse20-owner experiment
  therefore has at most240 neural pairs per query; that is an offline quality
  control, not a demonstrated acceptable production latency. A later smaller
  hypothesis budget requires its own registered, paired quality/latency control.
- Keep hypothesis/source hashes, actual visible spans and public coarse ranks.
  Report oracle coverage separately before interpreting learned accuracy.
- Model input: original source path, canonical identity, bounded signature/docs,
  and exactly the proposed source excerpt(s), preserving the full query. Use384
  pair tokens, truncate only the document, and record tokenization. Showing40
  lines does not mean that all40 lines necessarily fit the neural input.

## Fixed initial training experiment

- Base: registered22.7M MiniLM code reranker, revision
  9bcf5f1cceef4914e2fc564b2e4ee78410626702. CPU only. Production-size candidate
  remains the locally exported~23MB int8 graph; training/native and quantized
  inference results must be distinguished and checked before adoption.
- Sixteen repository-held-out folds. Every prediction excludes its entire
  repository from model training, negative mining, threshold fitting and model
  selection. Query variants remain in the same group. Private acceptance is unused.
- Training candidate selection is label-blind RRF first100 owners. Positives are
  naturally proposed satisfying hypotheses from those owners; negatives include
  wrong owners and non-satisfying windows of the correct owner. No gold-constructed
  windows. Queries with no positive remain in every reported denominator.
- Negatives are chosen from fixed public proposal ranks, not predictions of a
  cross-fitted model that may have trained on the outer held-out repository.
- Initial settings fixed before results: seed42, two epochs, AdamW learning
  rate2e-5, weight decay0.01, gradient clipping1.0; one positive with up to four
  negatives per listwise softmax group, gradient accumulation4 groups. No outer
  held-out early stopping or epoch selection. Record actual updates/empty groups.
- Start every fold from the identical registered base weights and a new optimizer;
  never warm-start from another fold. Select the first satisfying hypothesis in
  public proposal order as the positive. Choose at most one failing window from
  that owner, then wrong-owner negatives by original RRF owner rank and public
  hypothesis order; fill any remaining slots by that same order without duplicates.
  These are training-only label choices, never inference selection rules.
- Store the actual single-hypothesis rendered response before assigning targets.
  Training eligibility uses its post-budget visible spans, not complete owner
  regions, auxiliary signature/docs, or pre-trimming text. The final multi-result
  response is still graded independently by the unchanged original evaluator.
- Evaluation may use the numeric coarse first20 owners for the held-out query,
  provided that coarse model also excludes the entire held-out repository. The
  fine model never trains on those coarse selected candidate sets from other folds.
  Fixed candidate counts are reported; no gold-dependent inference budgets.
- At inference order hypotheses by the learned score, preserving original exact
  authority, then expose the winning hypothesis as the top result. Source flags,
  actual JSON budgets, omitted responses/errors and all strata use the original
  evaluator. Full API/CLI/MCP and public Semble1251 results remain separate gates.
- Record source/model/data receipts, CPU provider, measured native/quantization
  parity and ranking differences, query p50/p95/max and peak RSS. Any claim about
  latency or RAM of final search needs that final prepared profile measured through
  actual API; concurrent research timings are descriptive only.

Primary references consulted: [cross-encoder training](https://www.sbert.net/docs/cross_encoder/training_overview.html),
[ranking losses](https://sbert.net/docs/package_reference/cross_encoder/losses.html),
[AdamW](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW).
These motivate an experiment; they do not establish Ken's accuracy.
