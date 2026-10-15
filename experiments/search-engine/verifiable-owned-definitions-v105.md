# v105: source ownership governs evidence, not index fragment boundaries

Development-only after v102 descriptive Gold was opened. The new v104 acceptance
reserve remains hidden; no question, identity or label from it is an input here.
Same v98 metric/rubric/budgets and same200development queries. No new model or
ranking math is adopted. Existing core/head/sourceviews/queryexpansion are fixed.

Four failing public-usage tests demonstrated: a64line definition split among
20line retrieval fragments was truncated unnecessarily; a36line context window
was reduced to19lines; overlapping passages could waste capacity; gaps belonging
to a nested owner prevented the rest of the caller's own source from appearing.

SourceCatalog.owned_ranges merges adjacent/overlapping ranges of the SAME owner,
retains excluded-owner gaps, and is the source for context windows. Short symbol
cards quote all exclusively owned ranges when64lines/4excerpts/12000canonical
characters permit it. They truthfully remain truncated when nested owners are
not shown. Larger symbols and classes/files/modules retain query-conditioned
selection, now allowed to cross adjacent retrieval fragment boundaries. No
unrelated owner, generated summary, facets, Gold or ranker score is introduced.

Four regression tests nowpass; all35verifiable+10Ettin helper tests pass. Oldv102
freeze/outputs/opinions/report stay untouched. Newbaseline-only controller avoids
rerunning already measured neural arms while isolating evidence. Default remains
four arms; anonymity/reporting use the actually registered closed arms.

Replay all200prepared baseline queries inCPU under a new immutable producer
snapshot. Verify every candidate20unit identity/order and expansion equals v102;
answers can change only their excerpts/truncation metadata. Authenticate source
and budget for ALL cards. Blind cross-curator review of byte-distinct new cards
is required before any new joint utility percentage. Exact unchanged query/card
opinions may be reused; no self-judged success claim. Current rankings cap utility
at84% even if evidence were perfect, so later ranking work is still required.
