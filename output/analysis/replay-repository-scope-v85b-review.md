Independent review of repository-scoped replay85b — closed

No equivalence defect found. Every real 400 pool was compared one repository at a time against frozen85. The new loader used the complete catalog with repositories=[repo]; the original loader used the exact 25 catalog lines for that repository and a temporary symlink to its original index. The new default None was also checked against the original on each identical 25-row partition. Together those comparisons exhaust all 400 queries without retaining all pools at once.

Order and every dataclass value match for 167,360 candidates, 383,836 complete passages and 316,573 owned regions. The comparison includes 1,693,365 candidate signals and 437,607 passage signals. Every Candidate and Passage field is canonically serialized, including full source bodies, field dictionaries, identities, spans, entity extents, source hashes and metadata. Separate per-query SHA256 streams record complete identities/passages/signals/regions plus full objects. This is exhaustive content comparison, not top1 or sampled metadata.

All 16 original index hashes and the 129,884,940-byte candidate catalog remain unchanged. Temporary filtered catalogs and symlinks were removed. The current replay hash 0914d57b3d42f56e5ed970099d16a0e5291ad4f107dbedd3755fb5ac0b75a43e matches the actual 85b freeze; all src/ files are unchanged from 85. The actual 85b receipt is 4f44d3303cae3033f11672848ed022e95b70bb7877c956d10f9c23487897c335.

The scope is explicit, nonempty and unique. Missing repositories and malformed scopes fail before opening an index. All catalog rows still require a bound query, even outside the requested scope. Only selected repositories are restored; input streaming avoids retaining unselected catalog records. Refresh branches and restore_matches are unchanged. Forty-seven focused tests pass, including original helper/parent tests and scope failures. Mypy reports no issues in replay.py.

No label/reference, model fit, quality or private reserve was read. No source/index/model/dataset was changed by review; index digests were checked before and after. This establishes current data equivalence and bounded repository selection, not final API memory/latency or pre-fit acceptance for 85b. Source/pair artifacts, selections, cache, moments and isolation still require review when complete. No marker was created.

Detailed per-query field digests and counts: replay-repository-scope-v85b-review.json.
