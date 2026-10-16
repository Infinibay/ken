# vp-cs-055 — class

¿Qué clase de buffer permite marcas anidadas, extrae el texto añadido desde la última marca retrocediendo el contador y devuelve texto vacío si no había marca o no se añadieron bytes?

**Pieza elegida:** `junit-platform-launcher/src/main/java/org/junit/platform/launcher/core/StreamInterceptor.java::StreamInterceptor`
**Pieza aceptable:** `junit-platform-launcher/src/main/java/org/junit/platform/launcher/core/StreamInterceptor.java::StreamInterceptor.RewindableByteArrayOutputStream` — posición2.

Owner representante elegido: `StreamInterceptor.consume`; puesto de owner1.
Owner representante aceptable: `StreamInterceptor.RewindableByteArrayOutputStream.rewind`; puesto de owner2.

**Interpretación del caso (hipótesis de dominio):** StreamInterceptor frente al buffer anidado RewindableByteArrayOutputStream; consumidor frente a estado/operaciones del buffer.

**Mecanismo numérico comprobado:** orden por `numeric_model_score`; score elegido=1.414968285154271; aceptable=0.11201247284537166; margen=1.3029558123088993.
Residuo de acumulación flotante=-1.1102230246251565e-15.

Los márgenes de árboles se agrupan por su primera rama divergente. Signo positivo favorece al elegido y negativo al aceptable. La suma más el residuo reproduce el margen; no son pesos lineales ni efectos causales aislados. Los caminos completos están en forest-pairs.jsonl.gz.

| Señal | Elegido | Aceptable | Diferencia de valor | Margen de árboles |
|---|---:|---:|---:|---:|
| `rrf` | 0.01639344262295082 | 0.016129032258064516 | 0.00026441036488630484 | 0.0 |
| `cosine_identity` | 0.0 | 0.0 | 0.0 | 0.0 |
| `cosine_behavior` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25f` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_body` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_documentation` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_identity` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_signature` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_path` | 0.0 | 0.0 | 0.0 | 0.0 |
| `role_match` | 1.0 | 1.0 | 0.0 | 0.0 |
| `class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `module` | 0.0 | 0.0 | 0.0 | 0.0 |
| `log_lines` | 2.1972245773362196 | 2.302585092994046 | -0.10536051565782634 | 0.0 |
| `name_overlap` | 0.0 | 0.0 | 0.0 | 0.0 |
| `body_overlap` | 0.0 | 0.0 | 0.0 | 0.0 |
| `is_exception` | 0.0 | 0.0 | 0.0 | 0.0 |
| `is_constructor` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_log_tokens` | 3.295836866004329 | 3.295836866004329 | 0.0 | 0.0 |
| `query_identifier` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_kind_class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_mean` | 0.08609005808830261 | 0.14008526504039764 | -0.05399520695209503 | 0.0 |
| `identity_min` | -0.046748679131269455 | 0.020832117646932602 | -0.06758079677820206 | 0.0 |
| `identity_p25` | 0.02523968368768692 | 0.07031324505805969 | -0.04507356137037277 | 0.0 |
| `identity_above50` | 0.0 | 0.038461538461538464 | -0.038461538461538464 | 0.0 |
| `identity_above70` | 0.0 | 0.038461538461538464 | -0.038461538461538464 | 0.0 |
| `identity_weighted` | 0.08405031604563151 | 0.12659737853824526 | -0.04254706249261375 | 0.0 |
| `identity_mean_cosine` | -0.009467715458814469 | 0.02426098296687587 | -0.03372869842569034 | 0.0 |
| `identity_log_words` | 1.9459101490553132 | 2.5649493574615367 | -0.6190392084062235 | 0.21458840108802116 |
| `signature_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_mean` | 0.025226473808288574 | 0.034893494099378586 | -0.009667020291090012 | 0.0 |
| `signature_min` | -0.06535226106643677 | -0.07037962228059769 | 0.005027361214160919 | 0.0 |
| `signature_p25` | -0.033672817051410675 | -0.005915114656090736 | -0.02775770239531994 | 0.16182186096089168 |
| `signature_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_weighted` | 0.022848092107261905 | 0.03172797288577678 | -0.008879880778514874 | 0.0 |
| `signature_mean_cosine` | 0.013235970687122478 | -0.01178202662631284 | 0.02501799731343532 | 0.0 |
| `signature_log_words` | 1.0986122886681098 | 1.0986122886681098 | 0.0 | 0.0 |
| `documentation_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_mean` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_min` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_p25` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_weighted` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_mean_cosine` | 0.0 | 0.0 | 0.0 | 0.0 |
| `documentation_log_words` | 0.0 | 0.0 | 0.0 | 0.0 |
| `body_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `body_mean` | 0.2206350415945053 | 0.22606261074543 | -0.005427569150924683 | 0.0 |
| `body_min` | 0.005934703629463911 | 0.052895061671733856 | -0.046960358042269945 | 0.0 |
| `body_p25` | 0.08102578669786453 | 0.1016339510679245 | -0.020608164370059967 | 0.0 |
| `body_above50` | 0.11538461538461539 | 0.11538461538461539 | 0.0 | 0.0 |
| `body_above70` | 0.07692307692307693 | 0.07692307692307693 | 0.0 | 0.0 |
| `body_weighted` | 0.21203665309782405 | 0.21541424755477645 | -0.003377594456952404 | 0.0 |
| `body_mean_cosine` | 0.04298892617279234 | -0.010027620315326589 | 0.05301654648811893 | 0.0 |
| `body_log_words` | 3.258096538021482 | 3.1780538303479458 | 0.08004270767353638 | 0.0 |
| `path_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `path_mean` | 0.11827488988637924 | 0.11827488988637924 | 0.0 | 0.0 |
| `path_min` | 0.03840281069278717 | 0.03840281069278717 | 0.0 | 0.0 |
| `path_p25` | 0.06782937794923782 | 0.06782937794923782 | 0.0 | 0.0 |
| `path_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `path_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `path_weighted` | 0.11409374706526947 | 0.11409374706526947 | 0.0 | 0.0 |
| `path_mean_cosine` | -0.06474524141416046 | -0.06474524141416046 | 0.0 | 0.0 |
| `path_log_words` | 2.5649493574615367 | 2.5649493574615367 | 0.0 | 0.0 |
| `all_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `all_mean` | 0.25000736117362976 | 0.26857441663742065 | -0.018567055463790894 | 0.0 |
| `all_min` | 0.048603348433971405 | 0.06674157828092575 | -0.018138229846954346 | 0.0 |
| `all_p25` | 0.12310770153999329 | 0.1305958330631256 | -0.007488131523132324 | 0.0 |
| `all_above50` | 0.11538461538461539 | 0.15384615384615385 | -0.038461538461538464 | 0.0 |
| `all_above70` | 0.07692307692307693 | 0.11538461538461539 | -0.038461538461538464 | 0.0 |
| `all_weighted` | 0.2414410536759365 | 0.2512354668164814 | -0.00979441314054491 | 0.0 |
| `all_mean_cosine` | 0.006073245050640393 | -0.012736817367367363 | 0.018810062418007756 | 0.0 |
| `all_log_words` | 3.6635616461296463 | 3.784189633918261 | -0.12062798778861472 | 0.0 |
| `rrf_relative` | 0.6024987175539354 | 0.591750072831234 | 0.010748644722701317 | 0.0 |
| `rrf_rank` | 0.07692307692307693 | 0.06666666666666667 | 0.010256410256410262 | 0.1677697702566637 |
| `cosine_identity_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `cosine_identity_rank` | 0.0026666666666666666 | 0.0026595744680851063 | 7.092198581560259e-06 | 0.0 |
| `cosine_behavior_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `cosine_behavior_rank` | 0.0024271844660194173 | 0.002421307506053269 | 5.8769599661483846e-06 | 0.0 |
| `bm25f_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25f_rank` | 0.00510204081632653 | 0.005050505050505051 | 5.153576582147927e-05 | 0.0 |
| `bm25_body_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_body_rank` | 0.00510204081632653 | 0.005050505050505051 | 5.153576582147927e-05 | 0.0 |
| `bm25_documentation_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_documentation_rank` | 0.030303030303030304 | 0.02857142857142857 | 0.0017316017316017333 | 0.0 |
| `bm25_identity_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_identity_rank` | 0.0070921985815602835 | 0.006993006993006993 | 9.919158855329051e-05 | 0.0 |
| `bm25_signature_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_signature_rank` | 0.006493506493506494 | 0.00641025641025641 | 8.32500832500839e-05 | 0.0 |
| `bm25_path_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_path_rank` | 0.023809523809523808 | 0.022727272727272728 | 0.0010822510822510803 | 0.0 |
| `expanded_identity_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_identity_stem` | 0.0 | 0.05555555555555555 | -0.05555555555555555 | 0.0 |
| `expanded_identity_mean` | 0.07627732306718826 | 0.16880150139331818 | -0.09252417832612991 | 0.0 |
| `expanded_identity_min` | -0.009157806634902954 | 0.028250206261873245 | -0.0374080128967762 | 0.06457467126247068 |
| `expanded_identity_p25` | 0.028080059215426445 | 0.08067584037780762 | -0.05259578116238117 | 0.0 |
| `expanded_identity_above50` | 0.0 | 0.05 | -0.05 | 0.0 |
| `expanded_identity_above70` | 0.0 | 0.05 | -0.05 | 0.0 |
| `expanded_identity_weighted` | 0.07841499527437996 | 0.17472663939799404 | -0.09631164412361408 | 0.028602523967858923 |
| `expanded_identity_mean_cosine` | 0.052588922918349504 | 0.1422951097189063 | -0.0897061868005568 | 0.0 |
| `expanded_identity_log_words` | 1.9459101490553132 | 2.5649493574615367 | -0.6190392084062235 | 0.0 |
| `expanded_signature_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_mean` | 0.060494981706142426 | 0.0909235030412674 | -0.03042852133512497 | 0.0 |
| `expanded_signature_min` | -0.03178207203745842 | -0.008023792877793312 | -0.023758279159665108 | 0.0 |
| `expanded_signature_p25` | 0.01862536184489727 | 0.042475588619709015 | -0.023850226774811745 | 0.0 |
| `expanded_signature_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_signature_weighted` | 0.06138608182519287 | 0.0978329945392493 | -0.03644691271405644 | 0.0 |
| `expanded_signature_mean_cosine` | 0.11763568313786135 | 0.18547702759030738 | -0.06784134445244602 | 0.0 |
| `expanded_signature_log_words` | 1.0986122886681098 | 1.0986122886681098 | 0.0 | 0.0 |
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
| `expanded_implementation_exact` | 0.05 | 0.05 | 0.0 | 0.0 |
| `expanded_implementation_stem` | 0.2222222222222222 | 0.16666666666666666 | 0.05555555555555555 | 0.010756204031681857 |
| `expanded_implementation_mean` | 0.3755679130554199 | 0.3714474141597748 | 0.004120498895645142 | 0.0 |
| `expanded_implementation_min` | 0.06025820970535278 | 0.08925583213567734 | -0.028997622430324554 | 0.0 |
| `expanded_implementation_p25` | 0.15754258632659912 | 0.149189755320549 | 0.00835283100605011 | 0.0 |
| `expanded_implementation_above50` | 0.3 | 0.3 | 0.0 | 0.0 |
| `expanded_implementation_above70` | 0.25 | 0.25 | 0.0 | 0.0 |
| `expanded_implementation_weighted` | 0.37253419825255357 | 0.36039991688731915 | 0.012134281365234423 | 0.0 |
| `expanded_implementation_mean_cosine` | 0.3939356412810092 | 0.3459488459329311 | 0.04798679534807809 | 0.0 |
| `expanded_implementation_log_words` | 3.2188758248682006 | 3.1354942159291497 | 0.08338160893905089 | 0.0 |
| `expanded_executable_exact` | 0.05 | 0.05 | 0.0 | 0.0 |
| `expanded_executable_stem` | 0.2222222222222222 | 0.16666666666666666 | 0.05555555555555555 | 0.0 |
| `expanded_executable_mean` | 0.3755679130554199 | 0.3714474141597748 | 0.004120498895645142 | 0.0 |
| `expanded_executable_min` | 0.06025820970535278 | 0.08925583213567734 | -0.028997622430324554 | 0.0 |
| `expanded_executable_p25` | 0.15754258632659912 | 0.149189755320549 | 0.00835283100605011 | 0.0 |
| `expanded_executable_above50` | 0.3 | 0.3 | 0.0 | 0.0 |
| `expanded_executable_above70` | 0.25 | 0.25 | 0.0 | 0.0 |
| `expanded_executable_weighted` | 0.37253419825255357 | 0.36039991688731915 | 0.012134281365234423 | 0.020705012851043904 |
| `expanded_executable_mean_cosine` | 0.3939356412810092 | 0.3459488459329311 | 0.04798679534807809 | 0.0 |
| `expanded_executable_log_words` | 3.2188758248682006 | 3.1354942159291497 | 0.08338160893905089 | 0.0 |
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
| `expanded_calls_exact` | 0.05 | 0.05 | 0.0 | 0.0 |
| `expanded_calls_stem` | 0.1111111111111111 | 0.1111111111111111 | 0.0 | 0.0 |
| `expanded_calls_mean` | 0.2951837182044983 | 0.2315608710050583 | 0.06362284719944 | 0.0 |
| `expanded_calls_min` | 0.022837191820144653 | 0.06256028264760971 | -0.03972309082746506 | 0.10444709004290846 |
| `expanded_calls_p25` | 0.12052635848522186 | 0.0956730768084526 | 0.024853281676769257 | 0.0 |
| `expanded_calls_above50` | 0.25 | 0.15 | 0.1 | 0.0 |
| `expanded_calls_above70` | 0.15 | 0.15 | 0.0 | 0.0 |
| `expanded_calls_weighted` | 0.2999983713907712 | 0.22367457008963426 | 0.07632380130113692 | 0.29204239177130226 |
| `expanded_calls_mean_cosine` | 0.37852996109700077 | 0.30242513751137756 | 0.0761048235856232 | 0.0 |
| `expanded_calls_log_words` | 2.833213344056216 | 2.6390573296152584 | 0.19415601444095776 | 0.0 |
| `expanded_returns_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_returns_stem` | 0.05555555555555555 | 0.05555555555555555 | 0.0 | 0.0 |
| `expanded_returns_mean` | 0.09315679222345352 | 0.205050989985466 | -0.11189419776201248 | 0.0 |
| `expanded_returns_min` | -0.0525892935693264 | 0.022081680595874786 | -0.07467097416520119 | 0.0 |
| `expanded_returns_p25` | 0.017282824963331223 | 0.08870111405849457 | -0.07141828909516335 | 0.0 |
| `expanded_returns_above50` | 0.05 | 0.1 | -0.05 | 0.0 |
| `expanded_returns_above70` | 0.05 | 0.1 | -0.05 | 0.0 |
| `expanded_returns_weighted` | 0.09005398867562044 | 0.20045923509608346 | -0.11040524642046302 | 0.056420149673330436 |
| `expanded_returns_mean_cosine` | 0.11939556393695326 | 0.15685015193962637 | -0.03745458800267311 | -0.06432820645203567 |
| `expanded_returns_log_words` | 1.0986122886681098 | 2.3978952727983707 | -1.2992829841302609 | 0.0 |
| `expanded_path_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_path_stem` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_path_mean` | 0.09817735850811005 | 0.09817735850811005 | 0.0 | 0.0 |
| `expanded_path_min` | 0.006677280180156231 | 0.006677280180156231 | 0.0 | 0.0 |
| `expanded_path_p25` | 0.05366167798638344 | 0.05366167798638344 | 0.0 | 0.0 |
| `expanded_path_above50` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_path_above70` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_path_weighted` | 0.09865922310623865 | 0.09865922310623865 | 0.0 | 0.0 |
| `expanded_path_mean_cosine` | -0.11288426070590543 | -0.11288426070590543 | 0.0 | 0.0 |
| `expanded_path_log_words` | 2.5649493574615367 | 2.5649493574615367 | 0.0 | 0.0 |
| `expanded_all_exact` | 0.05 | 0.05 | 0.0 | 0.0 |
| `expanded_all_stem` | 0.2222222222222222 | 0.2222222222222222 | 0.0 | 0.0 |
| `expanded_all_mean` | 0.3841959834098816 | 0.42193374037742615 | -0.037737756967544556 | 0.0 |
| `expanded_all_min` | 0.10417723655700684 | 0.10417723655700684 | 0.0 | 0.0 |
| `expanded_all_p25` | 0.1751459836959839 | 0.19671644270420074 | -0.021570459008216858 | -0.047834172474589105 |
| `expanded_all_above50` | 0.3 | 0.35 | -0.04999999999999999 | -0.13624011652033943 |
| `expanded_all_above70` | 0.25 | 0.3 | -0.04999999999999999 | 0.0 |
| `expanded_all_weighted` | 0.37856989620691295 | 0.41206083752978606 | -0.03349094132287311 | -0.17458215145236866 |
| `expanded_all_mean_cosine` | 0.2767682188853568 | 0.2510413934384917 | 0.02572682544686511 | 0.0 |
| `expanded_all_log_words` | 3.6635616461296463 | 3.784189633918261 | -0.12062798778861472 | 0.0 |
| `expanded_kind_function` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_method` | 1.0 | 1.0 | 0.0 | 0.0 |
| `expanded_kind_class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_struct` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_interface` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_enum` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_trait` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_type` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_module` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_constant` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_property` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_variable` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_kind_constructor` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_log_executable_lines` | 2.0794415416798357 | 2.1972245773362196 | -0.11778303565638382 | 0.0 |
| `expanded_log_comment_lines` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_log_owned_lines` | 2.1972245773362196 | 2.302585092994046 | -0.10536051565782634 | 0.0006488693765360695 |
| `expanded_log_regions` | 1.0986122886681098 | 1.0986122886681098 | 0.0 | 0.0 |
| `expanded_documentation_fraction` | 0.125 | 0.11111111111111116 | 0.01388888888888884 | 0.0 |
| `expanded_query_negation` | 1.0 | 1.0 | 0.0 | 0.0 |
| `expanded_query_test` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_return` | 0.6931471805599453 | 1.0986122886681098 | -0.4054651081081645 | 0.0 |
| `expanded_op_raise` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_throw` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_panic` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_if` | 0.6931471805599453 | 0.6931471805599453 | 0.0 | 0.0 |
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
| `code_original_raw` | 0.2756870985031128 | 0.24083338677883148 | 0.03485371172428131 | 0.0 |
| `code_original_to_max` | 0.0 | -0.03485371172428131 | 0.03485371172428131 | 0.0 |
| `code_original_range_relative` | 1.0 | 0.906008154369551 | 0.09399184563044904 | 0.0 |
| `code_original_reciprocal_rank` | 1.0 | 0.3333333333333333 | 0.6666666666666667 | 0.0 |
| `code_expanded_raw` | 0.29912105202674866 | 0.2974325716495514 | 0.0016884803771972656 | 0.0 |
| `code_expanded_to_max` | 0.0 | -0.0016884803771972656 | 0.0016884803771972656 | 0.0 |
| `code_expanded_range_relative` | 1.0 | 0.9960951028815916 | 0.003904897118408357 | 0.0 |
| `code_expanded_reciprocal_rank` | 1.0 | 0.5 | 0.5 | 0.0 |
| `view_contract_original_raw` | 0.1277899146080017 | 0.11098478734493256 | 0.016805127263069153 | 0.0 |
| `view_contract_original_to_max` | -0.08632348477840424 | -0.10312861204147339 | 0.016805127263069153 | 0.0 |
| `view_contract_original_range_relative` | 0.7282317495641933 | 0.6753249415691349 | 0.052906807995058425 | 0.0 |
| `view_contract_original_reciprocal_rank` | 0.010416666666666666 | 0.007142857142857143 | 0.0032738095238095235 | 0.0 |
| `view_contract_expanded_raw` | 0.11205790936946869 | 0.07220771908760071 | 0.03985019028186798 | 0.0 |
| `view_contract_expanded_to_max` | -0.14257128536701202 | -0.18242147564888 | 0.03985019028186798 | 0.0 |
| `view_contract_expanded_range_relative` | 0.6447341149002075 | 0.545433522319882 | 0.09930059258032553 | 0.0 |
| `view_contract_expanded_reciprocal_rank` | 0.0036363636363636364 | 0.002403846153846154 | 0.0012325174825174824 | 0.0 |
| `view_implementation_original_raw` | 0.2756870985031128 | 0.24083338677883148 | 0.03485371172428131 | 0.0 |
| `view_implementation_original_to_max` | 0.0 | -0.03485371172428131 | 0.03485371172428131 | 0.5068190253955601 |
| `view_implementation_original_range_relative` | 1.0 | 0.9046185029443875 | 0.0953814970556125 | 0.0 |
| `view_implementation_original_reciprocal_rank` | 1.0 | 0.3333333333333333 | 0.6666666666666667 | 0.04331753005399699 |
| `view_implementation_expanded_raw` | 0.29912105202674866 | 0.2974325716495514 | 0.0016884803771972656 | 0.0 |
| `view_implementation_expanded_to_max` | 0.0 | -0.0016884803771972656 | 0.0016884803771972656 | 0.0006003551803743321 |
| `view_implementation_expanded_range_relative` | 1.0 | 0.9960951028815916 | 0.003904897118408357 | 0.0 |
| `view_implementation_expanded_reciprocal_rank` | 1.0 | 0.5 | 0.5 | 0.05282660329559273 |

## Señales crudas de recuperación

Estos valores preceden al vector; por ejemplo BM25 pasa por log1p. No sumarlos al score del bosque.

| Señal | Elegido | Aceptable |
|---|---:|---:|
| `cosine_code` | 0.29912105202674866 | 0.2974325716495514 |
| `cosine_code_expanded` | 0.29912105202674866 | 0.2974325716495514 |
| `cosine_code_original` | 0.2756870985031128 | 0.24083338677883148 |
| `cosine_view_contract_expanded` | 0.11205790936946869 | 0.07220771908760071 |
| `cosine_view_contract_original` | 0.1277899146080017 | 0.11098478734493256 |
| `cosine_view_implementation_expanded` | 0.29912105202674866 | 0.2974325716495514 |
| `cosine_view_implementation_original` | 0.2756870985031128 | 0.24083338677883148 |
| `proposal_code` | 1.0 | 0.5 |
| `rrf` | 0.01639344262295082 | 0.016129032258064516 |
