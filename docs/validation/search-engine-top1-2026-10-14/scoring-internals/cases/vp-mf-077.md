# vp-mf-077 — file

Which physical source file specializes the validator for JSON Schema draft 2020-12, enabling dynamic references and unevaluated tracking and registering that draft's vocabularies?

**Pieza elegida:** `lib/refs/json-schema-2020-12/meta/unevaluated.json`
**Pieza aceptable:** `lib/2020.ts` — posición21.

Owner representante elegido: `None`; puesto de owner1.
Owner representante aceptable: `None`; puesto de owner21.

**Interpretación del caso (hipótesis de dominio):** Esquema JSON de datos frente al código del validador. El aceptable queda fuera del top10; reordenar esos diez no lo recupera.

**Mecanismo numérico comprobado:** orden por `numeric_model_score`; score elegido=0.7458895083131862; aceptable=-5.671955439414481; margen=6.417844947727668.
Residuo de acumulación flotante=-1.7763568394002505e-15.

Los márgenes de árboles se agrupan por su primera rama divergente. Signo positivo favorece al elegido y negativo al aceptable. La suma más el residuo reproduce el margen; no son pesos lineales ni efectos causales aislados. Los caminos completos están en forest-pairs.jsonl.gz.

| Señal | Elegido | Aceptable | Diferencia de valor | Margen de árboles |
|---|---:|---:|---:|---:|
| `rrf` | 0.03252247488101534 | 0.020385395537525355 | 0.012137079343489985 | 0.1987394950105519 |
| `cosine_identity` | 0.4740773141384125 | 0.0 | 0.4740773141384125 | 0.0 |
| `cosine_behavior` | 0.678839921951294 | 0.557459831237793 | 0.12138009071350098 | 0.0 |
| `bm25f` | 3.5839263810328643 | 3.225018357136838 | 0.3589080238960265 | 0.0 |
| `bm25_body` | 3.5423216240521795 | 3.216407264468866 | 0.3259143595833134 | 0.0 |
| `bm25_documentation` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_identity` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_signature` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_path` | 2.694564461880054 | 1.6019081207964878 | 1.0926563410835661 | 0.0 |
| `role_match` | 1.0 | 1.0 | 0.0 | 0.0 |
| `class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `module` | 1.0 | 1.0 | 0.0 | 0.0 |
| `log_lines` | 2.772588722239781 | 3.6375861597263857 | -0.8649974374866045 | 0.0 |
| `name_overlap` | 0.0 | 0.0 | 0.0 | 0.0 |
| `body_overlap` | 0.3684210526315789 | 0.3157894736842105 | 0.05263157894736842 | 0.0 |
| `is_exception` | 0.0 | 0.0 | 0.0 | 0.0 |
| `is_constructor` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_log_tokens` | 2.995732273553991 | 2.995732273553991 | 0.0 | 0.0 |
| `query_identifier` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_kind_class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_mean` | 0.033800844103097916 | 0.033800844103097916 | 0.0 | 0.0 |
| `identity_min` | -0.11256738752126694 | -0.11256738752126694 | 0.0 | 0.0 |
| `identity_p25` | -0.019082577899098396 | -0.019082577899098396 | 0.0 | 0.0 |
| `identity_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_weighted` | 0.0505784268270019 | 0.0505784268270019 | 0.0 | 0.0 |
| `identity_mean_cosine` | 0.060545445674483056 | 0.060545445674483056 | 0.0 | 0.0 |
| `identity_log_words` | 0.6931471805599453 | 0.6931471805599453 | 0.0 | 0.0 |
| `signature_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
| `body_exact` | 0.3684210526315789 | 0.3157894736842105 | 0.05263157894736842 | 0.0 |
| `body_mean` | 0.5739559531211853 | 0.569269597530365 | 0.0046863555908203125 | 0.0 |
| `body_min` | 0.04826570674777031 | 0.13050363957881927 | -0.08223793283104897 | 0.0 |
| `body_p25` | 0.1748199760913849 | 0.25168120861053467 | -0.07686123251914978 | 0.1353753564277975 |
| `body_above50` | 0.5263157894736842 | 0.47368421052631576 | 0.05263157894736842 | 0.0 |
| `body_above70` | 0.47368421052631576 | 0.42105263157894735 | 0.05263157894736842 | 0.0 |
| `body_weighted` | 0.45596908408426995 | 0.45945559600028607 | -0.0034865119160161218 | 0.0 |
| `body_mean_cosine` | 0.6931754882578332 | 0.450954053941084 | 0.24222143431674914 | 0.0 |
| `body_log_words` | 3.4657359027997265 | 4.736198448394496 | -1.2704625455947691 | 0.05102567808109396 |
| `path_exact` | 0.2631578947368421 | 0.05263157894736842 | 0.21052631578947367 | 0.0 |
| `path_mean` | 0.42952707409858704 | 0.16548524796962738 | 0.26404182612895966 | 0.0 |
| `path_min` | 0.03588477894663811 | 0.00455857627093792 | 0.03132620267570019 | 0.0 |
| `path_p25` | 0.1250981241464615 | 0.042615242302417755 | 0.08248288184404373 | 0.0 |
| `path_above50` | 0.3684210526315789 | 0.10526315789473684 | 0.2631578947368421 | 0.0 |
| `path_above70` | 0.3684210526315789 | 0.10526315789473684 | 0.2631578947368421 | 0.0 |
| `path_weighted` | 0.3421656717552945 | 0.16786439427502994 | 0.17430127748026455 | 0.0 |
| `path_mean_cosine` | 0.4879560585947694 | 0.17687343406891531 | 0.3110826245258541 | 0.0 |
| `path_log_words` | 2.302585092994046 | 1.6094379124341003 | 0.6931471805599456 | 0.03891983378931192 |
| `all_exact` | 0.3684210526315789 | 0.3157894736842105 | 0.05263157894736842 | 0.0 |
| `all_mean` | 0.583322286605835 | 0.569269597530365 | 0.01405268907546997 | 0.0 |
| `all_min` | 0.10094165802001953 | 0.13050363957881927 | -0.029561981558799744 | 0.0 |
| `all_p25` | 0.1748199760913849 | 0.25168120861053467 | -0.07686123251914978 | -0.009116198819361918 |
| `all_above50` | 0.5263157894736842 | 0.47368421052631576 | 0.05263157894736842 | 0.0 |
| `all_above70` | 0.47368421052631576 | 0.42105263157894735 | 0.05263157894736842 | 0.0 |
| `all_weighted` | 0.46729969127312126 | 0.45945559600028607 | 0.007844095272835194 | 0.0 |
| `all_mean_cosine` | 0.6863194235525345 | 0.4542732953014435 | 0.232046128251091 | 0.0 |
| `all_log_words` | 3.58351893845611 | 4.762173934797756 | -1.1786549963416464 | 0.09600645901042311 |
| `rrf_relative` | 1.0 | 0.59195821354762 | 0.40804178645238 | 0.4363090401855158 |
| `rrf_rank` | 1.0 | 0.03125 | 0.96875 | 3.99418848765035 |
| `cosine_identity_relative` | 0.9619801991933524 | 0.0 | 0.9619801991933524 | 0.0 |
| `cosine_identity_rank` | 0.3333333333333333 | 0.004366812227074236 | 0.32896652110625907 | 0.0 |
| `cosine_behavior_relative` | 1.0 | 0.8211948254831574 | 0.17880517451684264 | 0.0 |
| `cosine_behavior_rank` | 1.0 | 0.1111111111111111 | 0.8888888888888888 | 0.0382964855984516 |
| `bm25f_relative` | 1.0 | 0.8998561952066126 | 0.10014380479338736 | 0.0 |
| `bm25f_rank` | 1.0 | 0.1111111111111111 | 0.8888888888888888 | 0.056228520241684926 |
| `bm25_body_relative` | 1.0 | 0.9079941365655869 | 0.09200586343441308 | 0.0 |
| `bm25_body_rank` | 1.0 | 0.14285714285714285 | 0.8571428571428572 | 0.060303948105136576 |
| `bm25_documentation_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_documentation_rank` | 0.5 | 0.030303030303030304 | 0.4696969696969697 | 0.01034184010710934 |
| `bm25_identity_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_identity_rank` | 0.02702702702702703 | 0.015151515151515152 | 0.011875511875511877 | 0.0 |
| `bm25_signature_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_signature_rank` | 0.018867924528301886 | 0.012048192771084338 | 0.006819731757217548 | 0.0 |
| `bm25_path_relative` | 1.0 | 0.5944961211574813 | 0.4055038788425187 | 0.0 |
| `bm25_path_rank` | 1.0 | 0.025 | 0.975 | 0.0 |
| `expanded_identity_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_identity_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_identity_mean` | 0.033800844103097916 | 0.033800844103097916 | 0.0 | 0.0 |
| `expanded_identity_min` | -0.11256738752126694 | -0.11256738752126694 | 0.0 | 0.0 |
| `expanded_identity_p25` | -0.019082577899098396 | -0.019082577899098396 | 0.0 | 0.0 |
| `expanded_identity_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_identity_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_identity_weighted` | 0.05057519364920751 | 0.05057519364920751 | 0.0 | 0.0 |
| `expanded_identity_mean_cosine` | 0.060545445674483056 | 0.060545445674483056 | 0.0 | 0.0 |
| `expanded_identity_log_words` | 0.6931471805599453 | 0.6931471805599453 | 0.0 | 0.0 |
| `expanded_signature_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
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
| `expanded_implementation_exact` | 0.3684210526315789 | 0.3157894736842105 | 0.05263157894736842 | 0.0 |
| `expanded_implementation_stem` | 0.42105263157894735 | 0.3684210526315789 | 0.05263157894736842 | 0.0 |
| `expanded_implementation_mean` | 0.5739559531211853 | 0.569269597530365 | 0.0046863555908203125 | 0.0 |
| `expanded_implementation_min` | 0.04826570674777031 | 0.13050363957881927 | -0.08223793283104897 | 0.0 |
| `expanded_implementation_p25` | 0.1748199760913849 | 0.25168120861053467 | -0.07686123251914978 | 0.0 |
| `expanded_implementation_above50` | 0.5263157894736842 | 0.47368421052631576 | 0.05263157894736842 | 0.0 |
| `expanded_implementation_above70` | 0.47368421052631576 | 0.42105263157894735 | 0.05263157894736842 | 0.0 |
| `expanded_implementation_weighted` | 0.4560032290380885 | 0.4594895222431071 | -0.003486293205018587 | 0.0 |
| `expanded_implementation_mean_cosine` | 0.6931754882578332 | 0.450954053941084 | 0.24222143431674914 | 0.047596671497692485 |
| `expanded_implementation_log_words` | 3.4657359027997265 | 4.736198448394496 | -1.2704625455947691 | 0.0 |
| `expanded_executable_exact` | 0.3684210526315789 | 0.3157894736842105 | 0.05263157894736842 | 0.0 |
| `expanded_executable_stem` | 0.42105263157894735 | 0.3684210526315789 | 0.05263157894736842 | 0.0 |
| `expanded_executable_mean` | 0.5739559531211853 | 0.569269597530365 | 0.0046863555908203125 | 0.0 |
| `expanded_executable_min` | 0.04826570674777031 | 0.13050363957881927 | -0.08223793283104897 | -0.0303216956159806 |
| `expanded_executable_p25` | 0.1748199760913849 | 0.25168120861053467 | -0.07686123251914978 | -0.12615805944523575 |
| `expanded_executable_above50` | 0.5263157894736842 | 0.47368421052631576 | 0.05263157894736842 | 0.0 |
| `expanded_executable_above70` | 0.47368421052631576 | 0.42105263157894735 | 0.05263157894736842 | 0.2882797732515402 |
| `expanded_executable_weighted` | 0.4560032290380885 | 0.4594895222431071 | -0.003486293205018587 | 0.0 |
| `expanded_executable_mean_cosine` | 0.6931754882578332 | 0.450954053941084 | 0.24222143431674914 | 0.32326918993678067 |
| `expanded_executable_log_words` | 3.4657359027997265 | 4.736198448394496 | -1.2704625455947691 | 0.0 |
| `expanded_comments_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_comments_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_calls_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_calls_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_calls_mean` | 0.0 | 0.0946371853351593 | -0.0946371853351593 | 0.0 |
| `expanded_calls_min` | 0.0 | -0.00961351953446865 | 0.00961351953446865 | 0.0 |
| `expanded_calls_p25` | 0.0 | 0.04607445001602173 | -0.04607445001602173 | 0.0 |
| `expanded_calls_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_calls_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_calls_weighted` | 0.0 | 0.1077527471387601 | -0.1077527471387601 | 0.0 |
| `expanded_calls_mean_cosine` | 0.0 | 0.15877488512348456 | -0.15877488512348456 | -0.2142712067518566 |
| `expanded_calls_log_words` | 0.0 | 1.791759469228055 | -1.791759469228055 | 0.0 |
| `expanded_returns_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_path_exact` | 0.2631578947368421 | 0.05263157894736842 | 0.21052631578947367 | 0.0 |
| `expanded_path_stem` | 0.2631578947368421 | 0.05263157894736842 | 0.21052631578947367 | 0.0 |
| `expanded_path_mean` | 0.42952707409858704 | 0.16548524796962738 | 0.26404182612895966 | -0.04823602965549765 |
| `expanded_path_min` | 0.03588477894663811 | 0.00455857627093792 | 0.03132620267570019 | 0.0 |
| `expanded_path_p25` | 0.1250981241464615 | 0.042615242302417755 | 0.08248288184404373 | 0.0 |
| `expanded_path_above50` | 0.3684210526315789 | 0.10526315789473684 | 0.2631578947368421 | 0.0 |
| `expanded_path_above70` | 0.3684210526315789 | 0.10526315789473684 | 0.2631578947368421 | 0.0 |
| `expanded_path_weighted` | 0.34220695566588066 | 0.16786166958406282 | 0.17434528608181785 | 0.0 |
| `expanded_path_mean_cosine` | 0.4879560585947694 | 0.17687343406891531 | 0.3110826245258541 | 0.0 |
| `expanded_path_log_words` | 2.302585092994046 | 1.6094379124341003 | 0.6931471805599456 | 0.0 |
| `expanded_all_exact` | 0.3684210526315789 | 0.3157894736842105 | 0.05263157894736842 | 0.0 |
| `expanded_all_stem` | 0.42105263157894735 | 0.3684210526315789 | 0.05263157894736842 | 0.0 |
| `expanded_all_mean` | 0.583322286605835 | 0.569269597530365 | 0.01405268907546997 | 0.0 |
| `expanded_all_min` | 0.10094165802001953 | 0.13050363957881927 | -0.029561981558799744 | 0.0 |
| `expanded_all_p25` | 0.1748199760913849 | 0.25168120861053467 | -0.07686123251914978 | -0.056700523399331994 |
| `expanded_all_above50` | 0.5263157894736842 | 0.47368421052631576 | 0.05263157894736842 | 0.0 |
| `expanded_all_above70` | 0.47368421052631576 | 0.42105263157894735 | 0.05263157894736842 | 0.0 |
| `expanded_all_weighted` | 0.4673331254511096 | 0.4594895222431071 | 0.007843603208002536 | 0.0 |
| `expanded_all_mean_cosine` | 0.6863194235525345 | 0.4542732953014435 | 0.232046128251091 | 0.004838832254383902 |
| `expanded_all_log_words` | 3.58351893845611 | 4.762173934797756 | -1.1786549963416464 | 0.0 |
| `expanded_kind_function` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_method` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_struct` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_interface` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_enum` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_trait` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_type` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_module` | 1.0 | 1.0 | 0.0 | 0.0 |
| `expanded_kind_constant` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_property` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_variable` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_constructor` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_log_executable_lines` | 2.70805020110221 | 3.6888794541139363 | -0.9808292530117262 | 0.0 |
| `expanded_log_comment_lines` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_log_owned_lines` | 2.772588722239781 | 3.8501476017100584 | -1.0775588794702773 | 0.0 |
| `expanded_log_regions` | 0.6931471805599453 | 1.0986122886681098 | -0.4054651081081645 | 0.0 |
| `expanded_documentation_fraction` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_query_negation` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_query_test` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_return` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_raise` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_throw` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_panic` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_if` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_else` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_try` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_catch` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_except` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_for` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_while` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_match` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_switch` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_await` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_yield` | 0.0 | 0.0 | 0.0 | 0.0 |
| `code_original_raw` | 0.496131032705307 | 0.3285161256790161 | 0.1676149070262909 | 0.0 |
| `code_original_to_max` | -0.03330579400062561 | -0.2009207010269165 | 0.1676149070262909 | 0.03625568927276731 |
| `code_original_range_relative` | 0.9284151589871873 | 0.5681569267219836 | 0.3602582322652037 | 0.09934661734661121 |
| `code_original_reciprocal_rank` | 0.5 | 0.017857142857142856 | 0.48214285714285715 | 0.0 |
| `code_expanded_raw` | 0.496131032705307 | 0.3285161256790161 | 0.1676149070262909 | 0.08103125488724086 |
| `code_expanded_to_max` | -0.03330579400062561 | -0.2009207010269165 | 0.1676149070262909 | 0.1602747319017466 |
| `code_expanded_range_relative` | 0.9284151589871873 | 0.5681569267219836 | 0.3602582322652037 | 0.0 |
| `code_expanded_reciprocal_rank` | 0.5 | 0.017857142857142856 | 0.48214285714285715 | 0.22749443729915214 |
| `view_contract_original_raw` | 0.39373505115509033 | 0.19889917969703674 | 0.1948358714580536 | 0.0 |
| `view_contract_original_to_max` | -0.07250344753265381 | -0.2673393189907074 | 0.1948358714580536 | 0.0 |
| `view_contract_original_range_relative` | 0.8350151575855006 | 0.3916574050493705 | 0.4433577525361301 | 0.0 |
| `view_contract_original_reciprocal_rank` | 0.14285714285714285 | 0.0033444816053511705 | 0.13951266125179168 | 0.0 |
| `view_contract_expanded_raw` | 0.39373505115509033 | 0.19889917969703674 | 0.1948358714580536 | 0.0 |
| `view_contract_expanded_to_max` | -0.07250344753265381 | -0.2673393189907074 | 0.1948358714580536 | 0.0 |
| `view_contract_expanded_range_relative` | 0.8350151575855006 | 0.3916574050493705 | 0.4433577525361301 | 0.0 |
| `view_contract_expanded_reciprocal_rank` | 0.14285714285714285 | 0.0033444816053511705 | 0.13951266125179168 | 0.0 |
| `view_implementation_original_raw` | 0.496131032705307 | 0.3285161256790161 | 0.1676149070262909 | 0.20849541301398733 |
| `view_implementation_original_to_max` | -0.03330579400062561 | -0.2009207010269165 | 0.1676149070262909 | 0.031305864471232264 |
| `view_implementation_original_range_relative` | 0.9284151589871873 | 0.5681569267219836 | 0.3602582322652037 | 0.0 |
| `view_implementation_original_reciprocal_rank` | 0.5 | 0.017857142857142856 | 0.48214285714285715 | 0.0 |
| `view_implementation_expanded_raw` | 0.496131032705307 | 0.3285161256790161 | 0.1676149070262909 | 0.24459989387201594 |
| `view_implementation_expanded_to_max` | -0.03330579400062561 | -0.2009207010269165 | 0.1676149070262909 | 0.019254211197282656 |
| `view_implementation_expanded_range_relative` | 0.9284151589871873 | 0.5681569267219836 | 0.3602582322652037 | 0.0 |
| `view_implementation_expanded_reciprocal_rank` | 0.5 | 0.017857142857142856 | 0.48214285714285715 | 0.014870937005073644 |

## Señales crudas de recuperación

Estos valores preceden al vector; por ejemplo BM25 pasa por log1p. No sumarlos al score del bosque.

| Señal | Elegido | Aceptable |
|---|---:|---:|
| `bm25_body` | 33.54703137866315 | 23.93836209975715 |
| `bm25_documentation` | 0.0 | 0.0 |
| `bm25_identity` | 0.0 | 0.0 |
| `bm25_path` | 13.799071789536239 | 3.962492431117298 |
| `bm25_signature` | 0.0 | 0.0 |
| `bm25f` | 35.01467092133919 | 24.154035907659306 |
| `cosine_behavior` | 0.678839921951294 | 0.557459831237793 |
| `cosine_code` | 0.496131032705307 | 0.3285161256790161 |
| `cosine_code_expanded` | 0.496131032705307 | 0.3285161256790161 |
| `cosine_code_original` | 0.496131032705307 | 0.3285161256790161 |
| `cosine_identity` | 0.4740773141384125 | ausente |
| `cosine_view_contract_expanded` | 0.39373505115509033 | 0.19889917969703674 |
| `cosine_view_contract_original` | 0.39373505115509033 | 0.19889917969703674 |
| `cosine_view_implementation_expanded` | 0.496131032705307 | 0.3285161256790161 |
| `cosine_view_implementation_original` | 0.496131032705307 | 0.3285161256790161 |
| `proposal_code` | 0.5 | 0.017857142857142856 |
| `proposal_original` | 1.0 | 0.04 |
| `proposal_static` | 1.0 | 0.04 |
| `rrf` | 0.03252247488101534 | 0.020385395537525355 |
