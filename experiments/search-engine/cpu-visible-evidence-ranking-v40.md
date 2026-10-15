# Fast visible-evidence numeric ranking control v40

The original strict acceptance contract, all400 development requests/references,
ALL decisive anchors, response budgets and unopened private reserve stay fixed.
This is a development experiment before production profile integration.

The v34b neural experiment scores the answer that will actually be visible, but
up to240 transformer pairs per request can be expensive. Test whether a small
numeric forest can rank the same public hypotheses using explicitly collected
visible evidence. This is a different hypothesis from the already tested
complete-owner eligibility objective; the target is the original strict scorer
on each actual postbudget response, not on unseen complete owner regions.

The feature producer reads no relevance, references or anchors. Reuse the227
public source features from v30, append eight original/expanded contextual cosine
summaries computed from the full source v26 index and v31 public query vectors,
and collect43 features from the exact visible fragment: raw and expanded static
term alignment (19), actual source position/coverage/bundle shape (9), and counts
of the same15 keyword spellings used by the existing source feature
contract, measured in visible text without treating comments as executed code. No pseudo-natural-language descriptions, query-specific aliases,
benchmark symbol names or anchor locations enter inference. Total278 features.

Use every naturally proposed renderable hypothesis in public RRF first100 owners
for training, the same16 repository-held-out folds and the existing core-v18
LightGBM parameters. No coarse cross-fitted predictions are training features.
Never optimize on the held-out repository. Every original query remains counted
at evaluation even if optimization has no positive or an input cannot render.

Measure all400 unchanged strict responses for three separately named public
inference budgets: RRF first100 owners, coarse20 owners from v32's model that
also excludes the held-out repo, and the entire existing broad static union.
The broad control is not the production first100 candidate gate. Original exact
authority is refreshed from v36's source-only original-query proposal run. Rank
by learned hypothesis score, retain the best visible hypothesis per canonical
owner, and pass ALL scored owners to the original budget-owning presenter.

Register all primary source-window/label/feature/vector inputs by SHA, numeric
models, versions and fold membership, and verify exact native/exported scoring
parity. Record source preparation and prepared scoring costs separately; final
CPU latency/RAM still require the final integrated API profile. This control
does not consume or replace private acceptance.
