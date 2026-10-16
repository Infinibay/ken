# v166: bounded nonlinear decision head on existing joint representations

Research control, no production change or extra transformer inference. Frozen
linear joint512heads J1/J2trainonly86-88%top1 on positive-containing queries;
corrected L2J3/J4still169new. Existing general-text final direction may be an
insufficient decision boundary. Test a single small nonlinear code relevance
head using those SAME512joint values; no source or expected identity as features.

One fixed architecture:512standardized coordinates ->24ReLU ->1sigmoid, sklearn
MLPClassifier solverlbfgs,alpha1,max_iter300,max_fun15000,random_state42,tol1e-8;
no early validation split, no HPO/restarts. Fit scaler only from eligible training
rows in complete queries with both positives and negatives, exclude entire held
repository. Sample weights: each complete query contributes equal positive and
negative mass (1/numpositives and1/numnegatives), normalize row-weight mean1.
Sort by raw affine output logit (avoid sigmoid saturation ties). Hidden/affine
weights export as ordinary NumPy arrays, no sklearn inference dependency. Check
exported probability parity on real training/test rows. Report convergence and
training hit rate alongside every held-repo result; no training reuse as success.

Data are LEGACY145native10,193newRecall/197old, existing v153closure; current
155/157pool has195new and is NOT this control. Other150old requests retain their
identical current/baseline orders. All400queries retained, absent positives count
as failures. If newCV>=180, recapture actual current250hidden states, re-evaluate
same head recipe on current pool before generic production packaging and final
CPU/fresh-reserve freeze. Never deploy a legacy193pool as if it kept current195.
Original>=180/197,new>=180 plus final independent>=90/98.5gates unchanged. No release.
