# Blind consumer protocol

Read one current query/card at a time. Do not open Gold, source repositories,
ranking outputs, scores, model identity, the other curator's private files or a
mapping file. Do not infer correctness from another variant or remembered source.
Persistent context and general source familiarity are limitations; cite only the
current card. The harness already authenticates source bytes, owners and budgets.

For each public facet, decide supported/contradicted/unobservable using only this
card. A nonidentity requirement needs source evidence. Metadata can establish the
canonical identity/type/path, not behavior. Docstrings can establish a declared
contract/responsibility when that answers the question; implementation conditions,
ordering or absence need appropriate code. A suggestive callee name, lexical
containment or a partial window does not prove hidden execution/absence.
Do not require a particular fragment or all source when visible evidence suffices.

Relevance:0wrong/unrelated responsibility;1related but requested responsibility
not established;2directly suitable for the literal request. Sufficiency:0cannot
verify essentials;1some essentials observable;2can verify the essential decision
from the response. A complete wrong card can beS2/R0, with contradicted facets.
OnlyR2/S2 with every facet supported is a pass. Missing information is insufficient,
not automatically irrelevant. If genuinely unable to judge, abstain explicitly;
it stays in the denominator. No confidence or length bonus.

Write exactly one JSONL row per judge_id, with citations before verdict fields:

```json
{"judge_id":"opaque","requirements":[{"facet_id":"F1","state":"supported","evidence":[{"excerpt":0,"quote":"literal visible substring"}],"reason":"brief if needed"}],"relevance":2,"sufficiency":2,"abstain":false,"reason":"brief overall rationale"}
```

Use excerpt0-based index or `"unit"` for identity metadata; quotes must be literal,
nonempty substrings of that excerpt/content or unit field value. For an unobservable
facet use evidence=[] and a brief explanation of what is missing. Do not silently
omit facets. Keep rationale compact; do not copy long passages. Do not edit input
cards, questions, facets or your sealed calibration decisions after seeing labels.

Calibration first:30anonymous cards from the other curator's strata. Seal all
decisions before any feedback. Curator audits their own calibration Gold and
returns aggregate pass/fail agreement and false-accept counts. Gate≥90% agreement
and≤5%falseaccept among negatives across60cards. General rubric issues are recorded
before principal decisions. Main judgments are anonymous/de-duplicated top1cards;
never open the other curator's Gold until all principal judgments are sealed.
