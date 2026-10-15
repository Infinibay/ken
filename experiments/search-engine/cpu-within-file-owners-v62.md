# Separate file discovery from owner discrimination v62

Diagnostic on the valid source5 actualAPI400: file top1345/400 (86.25%), canonical
identity290/400, strict ALL-anchor277/400. Correct file is not strict success.
Test whether training primarily against owners in unrelated files underweights
the distinction between neighboring functions. No new encoder or source data.

Use the COMPLETE source6 pools/235features/eligible_owner labels58 (167374rows),
same400 original strict references/strata/budgets and160tree parameters. The
baseline is58's sixteen repository-excluded models,277strict/291identity. Do not
train a second model on scores from other outer folds: they include heldoutrepo.

Fit a separate235-feature numeric model with training groups(query,file), using
only groups with an original strictly eligible owner IN THE TRAINING REPOS.
Group row order is source-only stable query/path/original-owner order. Train on
all naturally proposed owners of those files; no reference-defined new windows,
owner coordinates, generated labels or test-time file/owner oracle. Every heldout
repo remains completely excluded; native/export scores must match exactly.

At inference, preserve the BASELINE rank order of first-seen files from its full
owner ranking. Select each file's representative by the new within-file score,
with original exact priority and stable original ties. Put representatives in
the original file order, followed by all remaining owners in their original
global order. This changes neither source evidence nor total candidates and
retains all owners for the presenter. Unique exact authority remains unchanged.
The two ordering scores are separate signals; no calibrated probability claim.

Reproduce original source6 baseline277/291 before the new control; output ALL400
through actual present() and original strict scorer, no missing/errors/positive
abstention exclusions or reference changes. Record file/identity/strict outcomes
and top-file parity, including any presenter pruning. This experiment alone has
a ceiling below90% if baseline file discovery stays at~86%; it is not completion.
Prepared benefit would require real API/profile/CPU/RAM integration and blind
acceptance. Public1251 comparison and private reserve remain unchanged.
