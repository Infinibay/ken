# Final fresh review
Reviewer: /root/m4_kernels_final_review, gpt-6-astra/high; read-only; no builds, suite reruns or subagents. Verdict With fixes.2Important,0Critical,0Minor.

1. Scalar F32 query norm and matrix dot accumulation can reverse dense owner cutoff and same-owner evidence order versus NumPy. Darwinarm64/NumPy2.4.4/C-contiguousfloat32 reproduction: e=2**-26, rows [[.5,e,-.5,e,.5,0,-.5,0],[e,0,0,-.5,.5,.5,-.5,e]], query eightones, ids[1,2], limit1. Original scores[1.053671194739536e-08,0], owner first; scalar native picks second at5.26835597369768e-09. Bound permits score rounding, never membership/order differences. Fix compatible reduction; include both cutoff and same-owner evidence in both-platform actual differential capture.
2. Scalar BM25 unchecked zero denominators return successfulNaN instead of original ZeroDivisionError("float division by zero"). Cases: identityTF1, emptylengths/averages,df1/docs2,k1=-1; bodyTF1,length=-1,average3,df1/docs2,k1=1.2. Explicit diagnostic errors; update original error-category mapping; retain legitimate nonfinite categories.

Declined: publicCLI/MCP/productionreranking/fullM4; end-to-endsearchperformance/speedup; unrelateduserdirt. Parent rulings in LEDGER.
