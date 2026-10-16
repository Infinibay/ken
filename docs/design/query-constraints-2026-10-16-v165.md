# v165: query obligations and a lexical source-role posterior

Exposed-development research, no production promotion. Kstatic256query role got
171new, roleclassification219/250. Perfect fine-source role oracle only177new,
so role alone is not expected to pass180. P1syntax view155new,P2mean166vsraw169,
rejected. Test another missing distinction: direct named code references and
requested test artifact are obligations, rather than weak broad relevance cues.
Do not replace code correctness with a proof/sufficiency criterion.

R1 replaces only Kquery-role model with fixed char_wb TFIDF(3,5),sublinearTF,
max_features20000,lowercase, training-fold vocabulary/IDF only; LogisticRegression
C1,balanced,maxiter1000,random_state42. Expanded English query as text. Source-role
label of the canonical exposed answer from first100native, even when absent10;
no expected identity as a feature. All query source and role inventories pinned.
Final rawNN + logP(candidate file role|query), clip1e-6, no HPO. Non-test roles
share implementation preference. Each held repository excluded in fitting.

R2 adds only authoritative query-constraint priority: explicit canonical FQN/name
reference equality first when available; requested tests from existing interpret
puts file-test entries first when any present (no new purpose parser); then full
positive explicit-code-reference coverage of owned source/signature or docs,
only if query has no negation cue and at least one fully matching candidate. Use
v160critical-reference parser/coverage, not corpus-specific names or literals.
Then R1score. References are soft textual cues elsewhere; here exact positive
user-specified identifiers have explicit priority. This is a hypothesis: names
mentioned as context can cause false positives, so full400control is mandatory.
No candidates removed; named physical path retains absolute priority. Capture
existing inputs before exposed-label fitting, all400reported incl absent positives.
Required old180/197,new180before final actual CPU and untouched reserve. No release.
