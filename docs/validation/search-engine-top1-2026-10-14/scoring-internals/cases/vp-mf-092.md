# vp-mf-092 — file

¿Qué archivo Java declara la anotación que habilita una prueba sólo si una variable de entorno coincide con una regex y documenta que queda deshabilitada si la variable no existe?

**Pieza elegida:** `junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/EnabledIfEnvironmentVariableCondition.java`
**Pieza aceptable:** `junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/EnabledIfEnvironmentVariable.java` — posición6.

Owner representante elegido: `EnabledIfEnvironmentVariableCondition.evaluate`; puesto de owner1.
Owner representante aceptable: `None`; puesto de owner7.

**Interpretación del caso (hipótesis de dominio):** Evaluador de la condición frente a la anotación que la declara.

**Mecanismo numérico comprobado:** orden por `numeric_model_score`; score elegido=4.976912585295346; aceptable=-1.0626562902728849; margen=6.03956887556823.
Residuo de acumulación flotante=-3.552713678800501e-15.

Los márgenes de árboles se agrupan por su primera rama divergente. Signo positivo favorece al elegido y negativo al aceptable. La suma más el residuo reproduce el margen; no son pesos lineales ni efectos causales aislados. Los caminos completos están en forest-pairs.jsonl.gz.

| Señal | Elegido | Aceptable | Diferencia de valor | Margen de árboles |
|---|---:|---:|---:|---:|
| `rrf` | 0.030679156908665108 | 0.02423417290673928 | 0.006444984001925828 | 0.0 |
| `cosine_identity` | 0.5273065567016602 | 0.4145303964614868 | 0.11277616024017334 | 0.09898107131321618 |
| `cosine_behavior` | 0.7061275243759155 | 0.5731022357940674 | 0.13302528858184814 | 0.0 |
| `bm25f` | 3.947793392583226 | 3.4206990740534673 | 0.5270943185297585 | 0.0 |
| `bm25_body` | 3.767595622516297 | 3.31415065410049 | 0.4534449684158073 | 0.0 |
| `bm25_documentation` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_identity` | 2.9052189906157313 | 0.0 | 2.9052189906157313 | 0.0 |
| `bm25_signature` | 2.7937289429432566 | 0.0 | 2.7937289429432566 | 0.0 |
| `bm25_path` | 2.6108344381482995 | 2.6108344381482995 | 0.0 | 0.0 |
| `role_match` | 1.0 | 1.0 | 0.0 | 0.0 |
| `class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `module` | 0.0 | 1.0 | -1.0 | 0.0 |
| `log_lines` | 3.044522437723423 | 3.6109179126442243 | -0.5663954749208013 | 0.0 |
| `name_overlap` | 0.045454545454545456 | 0.0 | 0.045454545454545456 | 0.0 |
| `body_overlap` | 0.13636363636363635 | 0.13636363636363635 | 0.0 | 0.0 |
| `is_exception` | 0.0 | 0.0 | 0.0 | 0.0 |
| `is_constructor` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_log_tokens` | 3.1354942159291497 | 3.1354942159291497 | 0.0 | 0.0 |
| `query_identifier` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_kind_class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_exact` | 0.045454545454545456 | 0.0 | 0.045454545454545456 | 0.0 |
| `identity_mean` | 0.17442065477371216 | -0.00034326111199334264 | 0.1747639158857055 | 0.0 |
| `identity_min` | -0.0017783427610993385 | -0.14732420444488525 | 0.14554586168378592 | 0.0 |
| `identity_p25` | 0.08888890594244003 | -0.04013257101178169 | 0.12902147695422173 | 0.0 |
| `identity_above50` | 0.09090909090909091 | 0.0 | 0.09090909090909091 | 0.0 |
| `identity_above70` | 0.045454545454545456 | 0.0 | 0.045454545454545456 | 0.0 |
| `identity_weighted` | 0.15487809180805978 | 0.007737571612075189 | 0.1471405201959846 | 0.0 |
| `identity_mean_cosine` | 0.20239431445698008 | -0.04920131462092741 | 0.2515956290779075 | 0.0 |
| `identity_log_words` | 2.302585092994046 | 0.6931471805599453 | 1.6094379124341005 | -0.06494108496679347 |
| `signature_exact` | 0.045454545454545456 | 0.0 | 0.045454545454545456 | 0.0 |
| `signature_mean` | 0.21048060059547424 | 0.0 | 0.21048060059547424 | 0.0 |
| `signature_min` | 0.06422446668148041 | 0.0 | 0.06422446668148041 | 0.0 |
| `signature_p25` | 0.1035190224647522 | 0.0 | 0.1035190224647522 | 0.0 |
| `signature_above50` | 0.09090909090909091 | 0.0 | 0.09090909090909091 | 0.0 |
| `signature_above70` | 0.045454545454545456 | 0.0 | 0.045454545454545456 | 0.0 |
| `signature_weighted` | 0.19529608218892036 | 0.0 | 0.19529608218892036 | 0.0 |
| `signature_mean_cosine` | 0.18536683344801955 | 0.0 | 0.18536683344801955 | 0.0 |
| `signature_log_words` | 2.6390573296152584 | 0.0 | 2.6390573296152584 | 0.0 |
| `documentation_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
| `body_exact` | 0.13636363636363635 | 0.13636363636363635 | 0.0 | 0.0 |
| `body_mean` | 0.384656697511673 | 0.44983959197998047 | -0.0651828944683075 | 0.0 |
| `body_min` | 0.10509149730205536 | 0.14883677661418915 | -0.04374527931213379 | 0.0 |
| `body_p25` | 0.1426185965538025 | 0.26500463485717773 | -0.12238603830337524 | -0.00929655833740645 |
| `body_above50` | 0.3181818181818182 | 0.2727272727272727 | 0.04545454545454547 | 0.0 |
| `body_above70` | 0.18181818181818182 | 0.13636363636363635 | 0.04545454545454547 | 0.0 |
| `body_weighted` | 0.33484374344032675 | 0.389290059651911 | -0.054446316211584245 | 0.0 |
| `body_mean_cosine` | 0.22674399054553232 | 0.15573818913866566 | 0.07100580140686666 | 0.0 |
| `body_log_words` | 3.871201010907891 | 5.459585514144159 | -1.5883845032362678 | 0.0 |
| `path_exact` | 0.09090909090909091 | 0.09090909090909091 | 0.0 | 0.0 |
| `path_mean` | 0.24647831916809082 | 0.24741464853286743 | -0.0009363293647766113 | 0.0 |
| `path_min` | 0.06607574224472046 | 0.06438849121332169 | 0.0016872510313987732 | 0.0 |
| `path_p25` | 0.09605494141578674 | 0.1035190224647522 | -0.007464081048965454 | 0.0 |
| `path_above50` | 0.13636363636363635 | 0.13636363636363635 | 0.0 | 0.0 |
| `path_above70` | 0.09090909090909091 | 0.09090909090909091 | 0.0 | 0.0 |
| `path_weighted` | 0.19934377686814736 | 0.20053608835654285 | -0.0011923114883954922 | 0.0 |
| `path_mean_cosine` | 0.19668002571028068 | 0.197880059980223 | -0.001200034269942335 | 0.0 |
| `path_log_words` | 2.70805020110221 | 2.70805020110221 | 0.0 | 0.0 |
| `all_exact` | 0.18181818181818182 | 0.13636363636363635 | 0.04545454545454547 | 0.0 |
| `all_mean` | 0.4325824975967407 | 0.44983959197998047 | -0.017257094383239746 | 0.0 |
| `all_min` | 0.10509149730205536 | 0.14883677661418915 | -0.04374527931213379 | 0.0 |
| `all_p25` | 0.17628297209739685 | 0.26500463485717773 | -0.08872166275978088 | -0.03655368654870895 |
| `all_above50` | 0.36363636363636365 | 0.2727272727272727 | 0.09090909090909094 | 0.0 |
| `all_above70` | 0.22727272727272727 | 0.13636363636363635 | 0.09090909090909091 | 0.0 |
| `all_weighted` | 0.3506622347180949 | 0.389290059651911 | -0.03862782493381611 | 0.0 |
| `all_mean_cosine` | 0.24245705838061374 | 0.15370931178510666 | 0.08874774659550708 | 0.0 |
| `all_log_words` | 4.07753744390572 | 5.476463551931511 | -1.3989261080257913 | 0.0 |
| `rrf_relative` | 0.947886160179531 | 0.7351613228717078 | 0.2127248373078232 | 0.3986035479069625 |
| `rrf_rank` | 0.5 | 0.04 | 0.46 | 0.8585575800579972 |
| `cosine_identity_relative` | 0.8383735011861438 | 0.6590688005158326 | 0.17930470067031123 | 0.0 |
| `cosine_identity_rank` | 0.025 | 0.0078125 | 0.0171875 | 0.0 |
| `cosine_behavior_relative` | 1.0 | 0.8116129396040501 | 0.18838706039594988 | -0.02415077251264401 |
| `cosine_behavior_rank` | 1.0 | 0.03125 | 0.96875 | 0.2193368874990395 |
| `bm25f_relative` | 0.9899172762430086 | 0.857747296653292 | 0.13216997958971666 | 0.0 |
| `bm25f_rank` | 0.5 | 0.02127659574468085 | 0.4787234042553192 | 0.08252149545073971 |
| `bm25_body_relative` | 1.0 | 0.8796460624102326 | 0.12035393758976742 | -0.006841219229949165 |
| `bm25_body_rank` | 1.0 | 0.043478260869565216 | 0.9565217391304348 | 0.0 |
| `bm25_documentation_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_documentation_rank` | 0.014705882352941176 | 0.012987012987012988 | 0.0017188693659281884 | 0.0 |
| `bm25_identity_relative` | 0.848186422164883 | 0.0 | 0.848186422164883 | 0.0 |
| `bm25_identity_rank` | 0.02564102564102564 | 0.006211180124223602 | 0.01942984551680204 | 0.13713584828061468 |
| `bm25_signature_relative` | 0.7979618632138926 | 0.0 | 0.7979618632138926 | 0.0 |
| `bm25_signature_rank` | 0.027777777777777776 | 0.0058823529411764705 | 0.021895424836601306 | 0.0 |
| `bm25_path_relative` | 0.9130787132151392 | 0.9130787132151392 | 0.0 | 0.0 |
| `bm25_path_rank` | 0.018518518518518517 | 0.017857142857142856 | 0.0006613756613756613 | 0.0 |
| `expanded_identity_exact` | 0.1875 | 0.0 | 0.1875 | 0.0 |
| `expanded_identity_stem` | 0.25 | 0.0 | 0.25 | 0.0 |
| `expanded_identity_mean` | 0.3579924702644348 | 0.02216080203652382 | 0.335831668227911 | 0.0 |
| `expanded_identity_min` | 0.036181483417749405 | -0.14732420444488525 | 0.18350568786263466 | 0.1815638358806752 |
| `expanded_identity_p25` | 0.09906332194805145 | 0.00541535671800375 | 0.0936479652300477 | 0.0 |
| `expanded_identity_above50` | 0.3125 | 0.0 | 0.3125 | 0.0 |
| `expanded_identity_above70` | 0.25 | 0.0 | 0.25 | 0.0 |
| `expanded_identity_weighted` | 0.3259682290176533 | 0.03643733868322393 | 0.2895308903344294 | 0.02431898546297562 |
| `expanded_identity_mean_cosine` | 0.5300490960508532 | 0.04833539104233054 | 0.4817137050085226 | 0.10502846394932154 |
| `expanded_identity_log_words` | 2.302585092994046 | 0.6931471805599453 | 1.6094379124341005 | 0.0 |
| `expanded_signature_exact` | 0.25 | 0.0 | 0.25 | 0.0 |
| `expanded_signature_stem` | 0.3125 | 0.0 | 0.3125 | 0.0 |
| `expanded_signature_mean` | 0.40473872423171997 | 0.0 | 0.40473872423171997 | 0.0 |
| `expanded_signature_min` | 0.059128012508153915 | 0.0 | 0.059128012508153915 | 0.0 |
| `expanded_signature_p25` | 0.08986768126487732 | 0.0 | 0.08986768126487732 | 0.009517342780915775 |
| `expanded_signature_above50` | 0.375 | 0.0 | 0.375 | 0.0 |
| `expanded_signature_above70` | 0.3125 | 0.0 | 0.3125 | -0.02237770193128326 |
| `expanded_signature_weighted` | 0.3565267589082227 | 0.0 | 0.3565267589082227 | 0.03380792430125065 |
| `expanded_signature_mean_cosine` | 0.47325873957191134 | 0.0 | 0.47325873957191134 | 0.0 |
| `expanded_signature_log_words` | 2.6390573296152584 | 0.0 | 2.6390573296152584 | 0.0 |
| `expanded_documentation_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_documentation_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_implementation_exact` | 0.5625 | 0.6875 | -0.125 | 0.0 |
| `expanded_implementation_stem` | 0.625 | 0.875 | -0.25 | 0.0 |
| `expanded_implementation_mean` | 0.6747176647186279 | 0.8499416708946228 | -0.17522400617599487 | 0.0 |
| `expanded_implementation_min` | 0.07901723682880402 | 0.1858944296836853 | -0.10687719285488129 | 0.0 |
| `expanded_implementation_p25` | 0.1884818822145462 | 0.7865619659423828 | -0.5980800837278366 | 0.0 |
| `expanded_implementation_above50` | 0.625 | 0.875 | -0.25 | 0.0 |
| `expanded_implementation_above70` | 0.625 | 0.75 | -0.125 | 0.0 |
| `expanded_implementation_weighted` | 0.5926572502589118 | 0.7423163421103469 | -0.1496590918514351 | 0.0 |
| `expanded_implementation_mean_cosine` | 0.5706461043964933 | 0.5507091653666392 | 0.01993693902985416 | 0.0 |
| `expanded_implementation_log_words` | 3.6888794541139363 | 5.459585514144159 | -1.7707060600302227 | 0.0653524018340681 |
| `expanded_executable_exact` | 0.5625 | 0.4375 | 0.125 | 0.0 |
| `expanded_executable_stem` | 0.625 | 0.5625 | 0.0625 | 0.0 |
| `expanded_executable_mean` | 0.6747176647186279 | 0.6293637752532959 | 0.04535388946533203 | 0.0 |
| `expanded_executable_min` | 0.07901723682880402 | 0.1506759077310562 | -0.0716586709022522 | 0.0 |
| `expanded_executable_p25` | 0.1884818822145462 | 0.2887588143348694 | -0.10027693212032318 | 0.0 |
| `expanded_executable_above50` | 0.625 | 0.5 | 0.125 | 0.0 |
| `expanded_executable_above70` | 0.625 | 0.5 | 0.125 | 0.0 |
| `expanded_executable_weighted` | 0.5926572502589118 | 0.5272235639856471 | 0.06543368627326474 | 0.0 |
| `expanded_executable_mean_cosine` | 0.5817997450125619 | 0.5100540865186534 | 0.07174565849390857 | 0.08989616789131115 |
| `expanded_executable_log_words` | 3.6375861597263857 | 4.276666119016055 | -0.6390799592896697 | 0.0 |
| `expanded_comments_exact` | 0.0 | 0.6875 | -0.6875 | 0.0 |
| `expanded_comments_stem` | 0.0625 | 0.8125 | -0.75 | 0.0 |
| `expanded_comments_mean` | 0.15218231081962585 | 0.8444294929504395 | -0.6922471821308136 | 0.0 |
| `expanded_comments_min` | -0.01375957578420639 | 0.1858944296836853 | -0.1996540054678917 | 0.0 |
| `expanded_comments_p25` | 0.03289446234703064 | 0.7865619659423828 | -0.7536675035953522 | 0.0 |
| `expanded_comments_above50` | 0.0625 | 0.875 | -0.8125 | 0.0 |
| `expanded_comments_above70` | 0.0625 | 0.75 | -0.6875 | 0.0 |
| `expanded_comments_weighted` | 0.12143746695509974 | 0.7295784815825799 | -0.6081410146274802 | 0.0 |
| `expanded_comments_mean_cosine` | 0.1971131267684015 | 0.5189368664857822 | -0.32182373971738065 | 0.0 |
| `expanded_comments_log_words` | 1.3862943611198906 | 5.278114659230517 | -3.891820298110626 | 0.0 |
| `expanded_calls_exact` | 0.4375 | 0.125 | 0.3125 | 0.0 |
| `expanded_calls_stem` | 0.5 | 0.125 | 0.375 | 0.07268967676834057 |
| `expanded_calls_mean` | 0.5796865224838257 | 0.2879907488822937 | 0.291695773601532 | 0.0 |
| `expanded_calls_min` | 0.06408093869686127 | 0.06333523243665695 | 0.0007457062602043152 | 0.0 |
| `expanded_calls_p25` | 0.1404079794883728 | 0.10254134237766266 | 0.037866637110710144 | 0.0139539690516851 |
| `expanded_calls_above50` | 0.5 | 0.125 | 0.375 | 0.0 |
| `expanded_calls_above70` | 0.5 | 0.125 | 0.375 | 0.04134685119898764 |
| `expanded_calls_weighted` | 0.48618207390740287 | 0.27625137937163163 | 0.20993069453577123 | 0.03745779985490489 |
| `expanded_calls_mean_cosine` | 0.5733373064669427 | 0.3061677103695391 | 0.2671695960974036 | 0.0 |
| `expanded_calls_log_words` | 3.2188758248682006 | 2.70805020110221 | 0.5108256237659905 | 0.0 |
| `expanded_returns_exact` | 0.4375 | 0.0 | 0.4375 | 0.0 |
| `expanded_returns_stem` | 0.5 | 0.0 | 0.5 | 0.0 |
| `expanded_returns_mean` | 0.5844975709915161 | 0.0 | 0.5844975709915161 | 0.0 |
| `expanded_returns_min` | 0.06989291310310364 | 0.0 | 0.06989291310310364 | 0.0 |
| `expanded_returns_p25` | 0.12493525445461273 | 0.0 | 0.12493525445461273 | 0.0 |
| `expanded_returns_above50` | 0.5625 | 0.0 | 0.5625 | 0.0 |
| `expanded_returns_above70` | 0.5 | 0.0 | 0.5 | 0.0 |
| `expanded_returns_weighted` | 0.522548485460469 | 0.0 | 0.522548485460469 | 0.0 |
| `expanded_returns_mean_cosine` | 0.6037876364404058 | 0.0 | 0.6037876364404058 | 0.05150775897301092 |
| `expanded_returns_log_words` | 2.995732273553991 | 0.0 | 2.995732273553991 | 0.0 |
| `expanded_path_exact` | 0.25 | 0.25 | 0.0 | 0.0 |
| `expanded_path_stem` | 0.3125 | 0.3125 | 0.0 | 0.0 |
| `expanded_path_mean` | 0.43176764249801636 | 0.43176764249801636 | 0.0 | 0.0 |
| `expanded_path_min` | 0.05831398069858551 | 0.05831398069858551 | 0.0 | 0.0 |
| `expanded_path_p25` | 0.10878876596689224 | 0.10878876596689224 | 0.0 | 0.0 |
| `expanded_path_above50` | 0.375 | 0.375 | 0.0 | 0.0 |
| `expanded_path_above70` | 0.3125 | 0.3125 | 0.0 | 0.0 |
| `expanded_path_weighted` | 0.3504504352039657 | 0.3504504352039657 | 0.0 | 0.0 |
| `expanded_path_mean_cosine` | 0.5263877303029733 | 0.5326341341433162 | -0.006246403840342918 | 0.0 |
| `expanded_path_log_words` | 2.70805020110221 | 2.70805020110221 | 0.0 | 0.0 |
| `expanded_all_exact` | 0.625 | 0.6875 | -0.0625 | 0.0 |
| `expanded_all_stem` | 0.6875 | 0.875 | -0.1875 | 0.0 |
| `expanded_all_mean` | 0.7525917291641235 | 0.8499416708946228 | -0.09734994173049927 | 0.0 |
| `expanded_all_min` | 0.08987978100776672 | 0.1858944296836853 | -0.09601464867591858 | 0.0 |
| `expanded_all_p25` | 0.39443331956863403 | 0.7865619659423828 | -0.3921286463737488 | 0.0 |
| `expanded_all_above50` | 0.6875 | 0.875 | -0.1875 | 0.0 |
| `expanded_all_above70` | 0.6875 | 0.75 | -0.0625 | 0.0 |
| `expanded_all_weighted` | 0.6208602005092145 | 0.7423163421103469 | -0.12145614160113238 | -0.06107124444901716 |
| `expanded_all_mean_cosine` | 0.6073628465931824 | 0.5504318418454939 | 0.05693100474768853 | 0.0 |
| `expanded_all_log_words` | 4.07753744390572 | 5.476463551931511 | -1.3989261080257913 | 0.0 |
| `expanded_kind_function` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_method` | 1.0 | 0.0 | 1.0 | 0.46209230003391155 |
| `expanded_kind_class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_struct` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_interface` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_enum` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_trait` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_type` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_module` | 0.0 | 1.0 | -1.0 | 0.0 |
| `expanded_kind_constant` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_property` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_variable` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_constructor` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_log_executable_lines` | 2.772588722239781 | 3.1780538303479458 | -0.4054651081081646 | 0.0 |
| `expanded_log_comment_lines` | 0.6931471805599453 | 4.418840607796598 | -3.725693427236653 | 0.0933522104106434 |
| `expanded_log_owned_lines` | 3.044522437723423 | 4.74493212836325 | -1.7004096906398272 | 0.0 |
| `expanded_log_regions` | 1.0986122886681098 | 1.791759469228055 | -0.6931471805599452 | 0.0 |
| `expanded_documentation_fraction` | 0.15000000000000002 | 0.0 | 0.15000000000000002 | 1.837741716659256 |
| `expanded_query_negation` | 1.0 | 1.0 | 0.0 | 0.0 |
| `expanded_query_test` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_return` | 1.3862943611198906 | 0.0 | 1.3862943611198906 | 0.0 |
| `expanded_op_raise` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_throw` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_panic` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_if` | 1.0986122886681098 | 0.0 | 1.0986122886681098 | 0.0 |
| `expanded_op_else` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_try` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_catch` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_except` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_for` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_while` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_match` | 0.6931471805599453 | 0.0 | 0.6931471805599453 | 0.0 |
| `expanded_op_switch` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_await` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_yield` | 0.0 | 0.0 | 0.0 | 0.0 |
| `code_original_raw` | 0.4030437767505646 | 0.2853683829307556 | 0.11767539381980896 | 0.0 |
| `code_original_to_max` | -0.023210078477859497 | -0.14088547229766846 | 0.11767539381980896 | 0.2934108791400191 |
| `code_original_range_relative` | 0.9424196453153039 | 0.6504865128931346 | 0.29193313242216923 | 0.0 |
| `code_original_reciprocal_rank` | 0.3333333333333333 | 0.010416666666666666 | 0.32291666666666663 | 0.0 |
| `code_expanded_raw` | 0.559658944606781 | 0.5156017541885376 | 0.04405719041824341 | 0.0 |
| `code_expanded_to_max` | 0.0 | -0.04405719041824341 | 0.04405719041824341 | 0.5083562807479616 |
| `code_expanded_range_relative` | 1.0 | 0.9138227071576798 | 0.08617729284232023 | 0.0 |
| `code_expanded_reciprocal_rank` | 1.0 | 0.2 | 0.8 | 0.0 |
| `view_contract_original_raw` | 0.24268034100532532 | 0.2774808704853058 | -0.03480052947998047 | 0.0 |
| `view_contract_original_to_max` | -0.14340448379516602 | -0.10860395431518555 | -0.03480052947998047 | 0.0 |
| `view_contract_original_range_relative` | 0.5906461418025867 | 0.6899856508118791 | -0.09933950900929245 | 0.0 |
| `view_contract_original_reciprocal_rank` | 0.005235602094240838 | 0.011111111111111112 | -0.0058755090168702735 | 0.0 |
| `view_contract_expanded_raw` | 0.39772334694862366 | 0.4878455400466919 | -0.09012219309806824 | 0.0 |
| `view_contract_expanded_to_max` | -0.10539624094963074 | -0.0152740478515625 | -0.09012219309806824 | 0.0 |
| `view_contract_expanded_range_relative` | 0.7599414208657569 | 0.9652106546510815 | -0.20526923378532458 | 0.0 |
| `view_contract_expanded_reciprocal_rank` | 0.011904761904761904 | 0.16666666666666666 | -0.15476190476190477 | 0.0 |
| `view_implementation_original_raw` | 0.4030437767505646 | 0.2853683829307556 | 0.11767539381980896 | 0.0 |
| `view_implementation_original_to_max` | -0.031110048294067383 | -0.14878544211387634 | 0.11767539381980896 | 0.19334881682979724 |
| `view_implementation_original_range_relative` | 0.9243046471104265 | 0.6379829938165414 | 0.28632165329388504 | 0.07942144813285192 |
| `view_implementation_original_reciprocal_rank` | 0.2 | 0.009900990099009901 | 0.1900990099009901 | 0.0 |
| `view_implementation_expanded_raw` | 0.559658944606781 | 0.5156017541885376 | 0.04405719041824341 | 0.0 |
| `view_implementation_expanded_to_max` | 0.0 | -0.04405719041824341 | 0.04405719041824341 | 0.08128769532238486 |
| `view_implementation_expanded_range_relative` | 1.0 | 0.9138227059017684 | 0.0861772940982316 | 0.16869172542817717 |
| `view_implementation_expanded_reciprocal_rank` | 1.0 | 0.2 | 0.8 | 0.02552046238301664 |

## Señales crudas de recuperación

Estos valores preceden al vector; por ejemplo BM25 pasa por log1p. No sumarlos al score del bosque.

| Señal | Elegido | Aceptable |
|---|---:|---:|
| `bm25_body` | 42.275888075035155 | 26.499027876451677 |
| `bm25_documentation` | 0.0 | 0.0 |
| `bm25_identity` | 17.269244007167174 | 0.0 |
| `bm25_path` | 12.610403154380815 | 12.610403154380815 |
| `bm25_signature` | 15.341844130432609 | 0.0 |
| `bm25f` | 50.82089221590158 | 29.59079277736786 |
| `cosine_behavior` | 0.7061275243759155 | 0.5731022357940674 |
| `cosine_code` | 0.559658944606781 | 0.5156017541885376 |
| `cosine_code_expanded` | 0.559658944606781 | 0.5156017541885376 |
| `cosine_code_original` | 0.4030437767505646 | 0.2853683829307556 |
| `cosine_identity` | 0.5273065567016602 | 0.4145303964614868 |
| `cosine_view_contract_expanded` | 0.39772334694862366 | 0.4878455400466919 |
| `cosine_view_contract_original` | 0.24268034100532532 | 0.2774808704853058 |
| `cosine_view_implementation_expanded` | 0.559658944606781 | 0.5156017541885376 |
| `cosine_view_implementation_original` | 0.4030437767505646 | 0.2853683829307556 |
| `proposal_code` | 1.0 | 0.2 |
| `proposal_expanded` | 0.125 | 0.018867924528301886 |
| `proposal_original` | 0.1111111111111111 | 0.014084507042253521 |
| `proposal_static` | 0.1 | 0.018867924528301886 |
| `rrf` | 0.030679156908665108 | 0.02423417290673928 |
