# One fresh whole-plan review

Reviewer: gpt-6-astra, high reasoning, fresh context, task m3_index_final_review. Reviewed632d35fc..86493ebc, spec, plan and every ledger ruling. Read-only; focused input-only requests against the existing native probe; no builds or repeated suites. No second review.

Strengths: identifiable responsibility boundaries, frozen Unicode/normalization, transactional passage storage, immutable projection artifacts, real cross-platform original/native observations and adversarial evidence verification.

Critical: none.

Important1: legacy.rs:48/writer.rs:35 returned before retiring an existing ci_files.vec_slot when publishing inline or without an encoder. A mapped→edited inline request left slot0 pointing to [0.65561,0.37463,0.65561] while the new inline vector was [0.89815,0.16330,0.40825]. Slot-first readers used stale data, and an unencoded edit could falsely satisfy need_embedding. Require transactional clear/release, rollback coverage, fallback/recovery and subsequent encoding.

Important2: projections.rs:235 checked output count only. It did not compare cached/fresh vector dimensions to DocumentEncoder::dim or reject invalid output during chunk preparation. A structurally valid2D cached artifact could be reused by a3D encoder. An empty a.txt committed before invalid behavior vectors for b.txt failed publication. Validate positive expected dimension, finite values and positive finite F32 norm during preparation; retain storage defense. Require all-cache hits, wrong-size fresh output and late-file failure coverage.

Important3: projections.rs:299 bulk index_embeddings pinned source generation but omitted StoredProfile. A fingerprint changed during encoding was silently overwritten by final metadata. Capture the stored profile tuple in the initial read snapshot, compare inside the final IMMEDIATE transaction before artifact/metadata writes, and preserve concurrent values on failure.

Minor: none.

Declined to judge1: legacy readers retained across multiple later commits are outside the documented committed-owner/rollback allocator contract and require M4/M7 reader-lifetime coordination. This does not satisfy Review Focus4's unrestricted reader wording or establish safe global cutover; leave that condition explicit.

Declined to judge2: end-to-end query/runtime cutover belongs to subsequent migration stages; this review assesses indexing and its published data.

Verdict: ready with fixes, not ready to accept unchanged. All three findings affect current data correctness or explicit concurrency/failure contracts.
