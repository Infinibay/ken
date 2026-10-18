# Validation evidence

Published validation reports, compact observations, protocols and reproduction
scripts live here. Keep the evidence needed to check a published claim; do not
commit working directories, model caches, source checkouts or session databases.

The current public code-search comparison is
[Ken on the benchmark created by Semble](semble-embedding-comparison-2026-10-17-v323/README.md).
It includes a model-free scoring recheck and uses an external, pinned checkout of
[Semble](https://github.com/MinishLab/semble) for the original evaluator.

Older reports can name `output/` paths or absolute machine paths. These identify
local research artifacts, not files distributed with Ken. Generated checkpoints
and intermediate runs remain local and ignored. Private acceptance data stays
closed. Historical session databases and supervisor logs under
`docs/benchmark-evidence/` are also local artifacts; their compact reports and
metadata remain versioned.
