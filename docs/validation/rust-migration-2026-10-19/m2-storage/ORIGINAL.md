# Storage expectations captured before native implementation

Task1 original-only cut. No native storage crate/code exists at this point.
32real histories on Darwin/arm64 and Linux/aarch64:23valid compatibility histories
agree under fixed abs(error)<=1e-6+1e-6*abs(reference);9integrity-correction
observations remain separate. Exact types/IDs/slots/BLOBs/shape/order are required.
F32 byte payloads preserve NaN/Inf observations without invalid JSON. Physical
segment hashes and OS block counts are recorded as measurements.

Both actual frozen originals ran Python3.12.9,SQLite3.47.1,NumPy2.4.4, with the
same5owner hashes and imports checked against their own verified source trees.
No encoder singleton was instantiated. Parent capture verifies source integrity
before and after; incomplete references fail before output publication.

Four focused tests observed RED before GREEN, then passed on both platforms
(Linux4/4,3.47s). Full Python regression:15706passes plus the same10historicxfail,
0new failures/skips/missing baseline IDs,700.06s. Mac typing retains exactly its
two historic missing-transformers errors;0new. All1066original hashes unchanged.

Observed defects include finiteF32norm overflow persisting false zeros, conflicting
manifest metadata being accepted, an SQL migration error being swallowed and a
controlled original compact callback interruption leaving references paired with
old vector bytes. These observations are not a native correctness oracle; native
regressions must require rejection or complete recovery as specified.

Reference/cases were published before native storage implementation. The source
capture tooling was frozen as5646files with fingerprint
4e79b2c83e031e5b924eaa607bb81fb4ed3702d01b73cdca50ae1fb8db9e7361.
Storage_accepted=false,M2_accepted=false. Follow the storage spec/plan for the
remaining native implementation and31gate/final-review acceptance.
