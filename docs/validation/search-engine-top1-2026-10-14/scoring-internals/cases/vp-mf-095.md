# vp-mf-095 — file

¿Qué archivo contiene la entrada de consola que usa el código del resultado como salida del proceso y otra entrada que recibe explícitamente los flujos de salida y error?

**Pieza elegida:** `platform-tests/src/processStarter/java/org/junit/platform/tests/process/ProcessStarter.java`
**Pieza aceptable:** `junit-platform-console/src/main/java/org/junit/platform/console/ConsoleLauncher.java` — posición73.

Owner representante elegido: `ProcessStarter.forwardAndCaptureOutput`; puesto de owner1.
Owner representante aceptable: `ConsoleLauncher.run`; puesto de owner131.

**Interpretación del caso (hipótesis de dominio):** Helper ProcessStarter frente al entrypoint ConsoleLauncher. Aceptable en posición73, fuera del top10.

**Mecanismo numérico comprobado:** orden por `numeric_model_score`; score elegido=-3.994068481510007; aceptable=-7.23793404472298; margen=3.243865563212973.
Residuo de acumulación flotante=3.1086244689504383e-15.

Los márgenes de árboles se agrupan por su primera rama divergente. Signo positivo favorece al elegido y negativo al aceptable. La suma más el residuo reproduce el margen; no son pesos lineales ni efectos causales aislados. Los caminos completos están en forest-pairs.jsonl.gz.

| Señal | Elegido | Aceptable | Diferencia de valor | Margen de árboles |
|---|---:|---:|---:|---:|
| `rrf` | 0.02832415420928403 | 0.003703703703703704 | 0.024620450505580323 | 0.04025496631074327 |
| `cosine_identity` | 0.505810022354126 | 0.29566776752471924 | 0.21014225482940674 | 0.0 |
| `cosine_behavior` | 0.5437089204788208 | 0.3080858290195465 | 0.2356230914592743 | 0.0 |
| `bm25f` | 3.053667400653478 | 0.0 | 3.053667400653478 | 0.0 |
| `bm25_body` | 2.8635200059071613 | 0.0 | 2.8635200059071613 | 0.0 |
| `bm25_documentation` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_identity` | 2.3989853860653865 | 0.0 | 2.3989853860653865 | 0.0 |
| `bm25_signature` | 2.8556270766972576 | 0.0 | 2.8556270766972576 | 0.0 |
| `bm25_path` | 1.744025763380916 | 0.0 | 1.744025763380916 | 0.0 |
| `role_match` | 0.0 | 1.0 | -1.0 | -0.17168912747021012 |
| `class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `module` | 0.0 | 0.0 | 0.0 | 0.0 |
| `log_lines` | 2.772588722239781 | 1.791759469228055 | 0.9808292530117262 | 0.0 |
| `name_overlap` | 0.0 | 0.0 | 0.0 | 0.0 |
| `body_overlap` | 0.0 | 0.0 | 0.0 | 0.0 |
| `is_exception` | 0.0 | 0.0 | 0.0 | 0.0 |
| `is_constructor` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_log_tokens` | 3.044522437723423 | 3.044522437723423 | 0.0 | 0.0 |
| `query_identifier` | 0.0 | 0.0 | 0.0 | 0.0 |
| `query_kind_class` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `identity_mean` | 0.13282372057437897 | 0.12796607613563538 | 0.004857644438743591 | 0.0 |
| `identity_min` | 0.007939936593174934 | 0.02802811749279499 | -0.020088180899620056 | 0.0 |
| `identity_p25` | 0.07395745813846588 | 0.07912090420722961 | -0.005163446068763733 | 0.0 |
| `identity_above50` | 0.05 | 0.0 | 0.05 | 0.0 |
| `identity_above70` | 0.05 | 0.0 | 0.05 | 0.0 |
| `identity_weighted` | 0.1347121794011516 | 0.12962221242316643 | 0.005089966977985166 | 0.0 |
| `identity_mean_cosine` | 0.12146663067588359 | 0.15266631148113788 | -0.031199680805254287 | 0.0 |
| `identity_log_words` | 2.302585092994046 | 1.9459101490553132 | 0.35667494393873267 | 0.0 |
| `signature_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `signature_mean` | 0.20354866981506348 | 0.1903311014175415 | 0.013217568397521973 | 0.0 |
| `signature_min` | 0.06800076365470886 | 0.05433698743581772 | 0.013663776218891144 | 0.0 |
| `signature_p25` | 0.10447686910629272 | 0.11096307635307312 | -0.0064862072467803955 | 0.0 |
| `signature_above50` | 0.1 | 0.05 | 0.05 | 0.0 |
| `signature_above70` | 0.05 | 0.0 | 0.05 | 0.0 |
| `signature_weighted` | 0.20903350482480748 | 0.18204193505393046 | 0.026991569770877022 | 0.0 |
| `signature_mean_cosine` | 0.15157266824192234 | 0.1463276754501988 | 0.005244992791723524 | 0.0 |
| `signature_log_words` | 3.2188758248682006 | 3.044522437723423 | 0.17435338714477755 | 0.0 |
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
| `body_mean` | 0.27136367559432983 | 0.21374726295471191 | 0.05761641263961792 | 0.0 |
| `body_min` | 0.10559321194887161 | 0.10235201567411423 | 0.0032411962747573853 | 0.0 |
| `body_p25` | 0.1621512770652771 | 0.14138925075531006 | 0.02076202630996704 | 0.0 |
| `body_above50` | 0.15 | 0.05 | 0.09999999999999999 | 0.0 |
| `body_above70` | 0.05 | 0.0 | 0.05 | 0.0 |
| `body_weighted` | 0.2676855338423122 | 0.20707788383694986 | 0.060607650005362335 | 0.0 |
| `body_mean_cosine` | 0.15561892682294723 | 0.14414373268718647 | 0.011475194135760758 | 0.0 |
| `body_log_words` | 4.060443010546419 | 3.6109179126442243 | 0.44952509790219475 | 0.0 |
| `path_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `path_mean` | 0.16451603174209595 | 0.16307023167610168 | 0.0014458000659942627 | 0.0 |
| `path_min` | 0.07357410341501236 | 0.08171568810939789 | -0.008141584694385529 | 0.0 |
| `path_p25` | 0.10741543769836426 | 0.11870899796485901 | -0.011293560266494751 | 0.0 |
| `path_above50` | 0.05 | 0.0 | 0.05 | 0.0 |
| `path_above70` | 0.05 | 0.0 | 0.05 | 0.0 |
| `path_weighted` | 0.16770928648570727 | 0.1658656384305331 | 0.001843648055174174 | 0.0 |
| `path_mean_cosine` | 0.06606400845708954 | 0.1325254502972344 | -0.06646144184014485 | 0.0 |
| `path_log_words` | 2.3978952727983707 | 2.3978952727983707 | 0.0 | 0.0 |
| `all_exact` | 0.0 | 0.0 | 0.0 | 0.0 |
| `all_mean` | 0.2764367163181305 | 0.2406972348690033 | 0.0357394814491272 | 0.0 |
| `all_min` | 0.10559321194887161 | 0.11412124335765839 | -0.008528031408786774 | -0.03269545230715837 |
| `all_p25` | 0.179109126329422 | 0.1767537146806717 | 0.002355411648750305 | 0.0 |
| `all_above50` | 0.15 | 0.05 | 0.09999999999999999 | 0.0 |
| `all_above70` | 0.05 | 0.0 | 0.05 | 0.0 |
| `all_weighted` | 0.27310947578004496 | 0.2358920682481308 | 0.03721740753191416 | 0.0 |
| `all_mean_cosine` | 0.15386953467578338 | 0.1843578135843868 | -0.030488278908603422 | 0.0 |
| `all_log_words` | 4.23410650459726 | 3.871201010907891 | 0.36290549368936853 | 0.0 |
| `rrf_relative` | 1.0 | 0.07698656066628809 | 0.9230134393337119 | 0.530653031773076 |
| `rrf_rank` | 1.0 | 0.0026455026455026454 | 0.9973544973544973 | 1.3919678668074942 |
| `cosine_identity_relative` | 1.0 | 0.5845431178857056 | 0.41545688211429443 | 0.3256434876921222 |
| `cosine_identity_rank` | 1.0 | 0.01694915254237288 | 0.9830508474576272 | 0.0 |
| `cosine_behavior_relative` | 1.0 | 0.5666374367156395 | 0.4333625632843605 | 0.0 |
| `cosine_behavior_rank` | 1.0 | 0.010869565217391304 | 0.9891304347826086 | 0.022339200497483946 |
| `bm25f_relative` | 0.9422892232489922 | 0.0 | 0.9422892232489922 | -0.07009617374027396 |
| `bm25f_rank` | 0.0625 | 0.001968503937007874 | 0.06053149606299213 | 0.0 |
| `bm25_body_relative` | 0.9475261482452675 | 0.0 | 0.9475261482452675 | 0.0 |
| `bm25_body_rank` | 0.09090909090909091 | 0.001968503937007874 | 0.08894058697208304 | 0.05063935503376649 |
| `bm25_documentation_relative` | 0.0 | 0.0 | 0.0 | 0.0 |
| `bm25_documentation_rank` | 0.05263157894736842 | 0.002570694087403599 | 0.05006088485996482 | 0.0 |
| `bm25_identity_relative` | 0.9609740898754571 | 0.0 | 0.9609740898754571 | 0.0 |
| `bm25_identity_rank` | 0.125 | 0.00234192037470726 | 0.12265807962529274 | 0.007678287782961424 |
| `bm25_signature_relative` | 0.9922987870457769 | 0.0 | 0.9922987870457769 | -0.010431429048704888 |
| `bm25_signature_rank` | 0.5 | 0.0020920502092050207 | 0.497907949790795 | 0.0 |
| `bm25_path_relative` | 0.7842742215963314 | 0.0 | 0.7842742215963314 | -0.12390404084349345 |
| `bm25_path_rank` | 0.01818181818181818 | 0.0025252525252525255 | 0.015656565656565657 | 0.0 |
| `expanded_identity_exact` | 0.125 | 0.0625 | 0.0625 | 0.0 |
| `expanded_identity_stem` | 0.125 | 0.0625 | 0.0625 | 0.0 |
| `expanded_identity_mean` | 0.2575782537460327 | 0.16758114099502563 | 0.08999711275100708 | 0.0 |
| `expanded_identity_min` | 0.06192215159535408 | -0.033356133848428726 | 0.0952782854437828 | 0.0 |
| `expanded_identity_p25` | 0.1181487888097763 | 0.0781460553407669 | 0.0400027334690094 | 0.04664227338501073 |
| `expanded_identity_above50` | 0.125 | 0.0625 | 0.0625 | 0.0 |
| `expanded_identity_above70` | 0.125 | 0.0625 | 0.0625 | 0.0 |
| `expanded_identity_weighted` | 0.21190471182613776 | 0.12402244035178636 | 0.0878822714743514 | 0.0027850441908964753 |
| `expanded_identity_mean_cosine` | 0.49479409006588915 | 0.25312890599767707 | 0.24166518406821208 | 0.0 |
| `expanded_identity_log_words` | 2.302585092994046 | 1.9459101490553132 | 0.35667494393873267 | 0.0 |
| `expanded_signature_exact` | 0.1875 | 0.0625 | 0.125 | 0.0 |
| `expanded_signature_stem` | 0.1875 | 0.0625 | 0.125 | 0.0 |
| `expanded_signature_mean` | 0.33496156334877014 | 0.26055097579956055 | 0.0744105875492096 | 0.0 |
| `expanded_signature_min` | 0.09345568716526031 | 0.08708681911230087 | 0.006368868052959442 | 0.0 |
| `expanded_signature_p25` | 0.1126723363995552 | 0.12852434813976288 | -0.015852011740207672 | 0.0 |
| `expanded_signature_above50` | 0.1875 | 0.125 | 0.0625 | 0.0 |
| `expanded_signature_above70` | 0.1875 | 0.0625 | 0.125 | -0.03150949415261324 |
| `expanded_signature_weighted` | 0.25801486431755194 | 0.20144062143379374 | 0.0565742428837582 | 0.0 |
| `expanded_signature_mean_cosine` | 0.46614122238256117 | 0.22289883840659575 | 0.24324238397596543 | 0.0 |
| `expanded_signature_log_words` | 3.2188758248682006 | 3.044522437723423 | 0.17435338714477755 | 0.0 |
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
| `expanded_implementation_exact` | 0.1875 | 0.0 | 0.1875 | 0.0 |
| `expanded_implementation_stem` | 0.1875 | 0.0 | 0.1875 | 0.0 |
| `expanded_implementation_mean` | 0.3745318353176117 | 0.20518091320991516 | 0.16935092210769653 | 0.05973660532860524 |
| `expanded_implementation_min` | 0.1381658911705017 | 0.07695498317480087 | 0.061210907995700836 | 0.0 |
| `expanded_implementation_p25` | 0.17126277089118958 | 0.12753704190254211 | 0.04372572898864746 | 0.0 |
| `expanded_implementation_above50` | 0.25 | 0.0625 | 0.1875 | 0.0 |
| `expanded_implementation_above70` | 0.1875 | 0.0 | 0.1875 | 0.0 |
| `expanded_implementation_weighted` | 0.3103072969508357 | 0.19254805117561946 | 0.11775924577521624 | 0.0 |
| `expanded_implementation_mean_cosine` | 0.40405744381939235 | 0.15029276021639318 | 0.2537646836029992 | 0.0 |
| `expanded_implementation_log_words` | 3.8918202981106265 | 3.091042453358316 | 0.8007778447523104 | 0.0 |
| `expanded_executable_exact` | 0.1875 | 0.0 | 0.1875 | 0.0 |
| `expanded_executable_stem` | 0.1875 | 0.0 | 0.1875 | 0.0 |
| `expanded_executable_mean` | 0.3745318353176117 | 0.20518091320991516 | 0.16935092210769653 | 0.011787583468309035 |
| `expanded_executable_min` | 0.1381658911705017 | 0.07695498317480087 | 0.061210907995700836 | 0.0 |
| `expanded_executable_p25` | 0.17126277089118958 | 0.12753704190254211 | 0.04372572898864746 | 0.0 |
| `expanded_executable_above50` | 0.25 | 0.0625 | 0.1875 | 0.0 |
| `expanded_executable_above70` | 0.1875 | 0.0 | 0.1875 | 0.0 |
| `expanded_executable_weighted` | 0.3103072969508357 | 0.19254805117561946 | 0.11775924577521624 | 0.0 |
| `expanded_executable_mean_cosine` | 0.40405744381939235 | 0.15029276021639318 | 0.2537646836029992 | 0.0 |
| `expanded_executable_log_words` | 3.8918202981106265 | 3.091042453358316 | 0.8007778447523104 | 0.0 |
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
| `expanded_calls_exact` | 0.125 | 0.0 | 0.125 | 0.0 |
| `expanded_calls_stem` | 0.125 | 0.0 | 0.125 | 0.07837341024176234 |
| `expanded_calls_mean` | 0.3064934015274048 | 0.1094604879617691 | 0.19703291356563568 | 0.0 |
| `expanded_calls_min` | 0.07998070120811462 | -0.023450622335076332 | 0.10343132354319096 | -0.04182192677242895 |
| `expanded_calls_p25` | 0.1574396938085556 | 0.07633418589830399 | 0.08110550791025162 | 0.0 |
| `expanded_calls_above50` | 0.125 | 0.0 | 0.125 | 0.0 |
| `expanded_calls_above70` | 0.125 | 0.0 | 0.125 | 0.0 |
| `expanded_calls_weighted` | 0.2568132314477699 | 0.10827837934347652 | 0.1485348521042934 | 0.0 |
| `expanded_calls_mean_cosine` | 0.38827486074718204 | 0.08885119155978477 | 0.29942366918739727 | 0.11190574608693858 |
| `expanded_calls_log_words` | 3.4339872044851463 | 1.9459101490553132 | 1.488077055429833 | 0.0 |
| `expanded_returns_exact` | 0.125 | 0.0 | 0.125 | 0.0 |
| `expanded_returns_stem` | 0.125 | 0.0 | 0.125 | 0.024768376776965372 |
| `expanded_returns_mean` | 0.3058205246925354 | 0.17593351006507874 | 0.12988701462745667 | 0.0 |
| `expanded_returns_min` | 0.07041823863983154 | 0.057830240577459335 | 0.012587998062372208 | 0.0 |
| `expanded_returns_p25` | 0.12634721398353577 | 0.08165805786848068 | 0.044689156115055084 | 0.0 |
| `expanded_returns_above50` | 0.1875 | 0.0625 | 0.125 | 0.0 |
| `expanded_returns_above70` | 0.125 | 0.0 | 0.125 | 0.0 |
| `expanded_returns_weighted` | 0.2549435971404152 | 0.1564447732382545 | 0.09849882390216069 | -0.011877712816080728 |
| `expanded_returns_mean_cosine` | 0.35617231531690036 | 0.2509247593413819 | 0.10524755597551844 | 0.0 |
| `expanded_returns_log_words` | 3.1780538303479458 | 2.0794415416798357 | 1.09861228866811 | 0.0 |
| `expanded_path_exact` | 0.0625 | 0.0625 | 0.0 | 0.0 |
| `expanded_path_stem` | 0.0625 | 0.0625 | 0.0 | 0.0 |
| `expanded_path_mean` | 0.17143569886684418 | 0.17993441224098206 | -0.008498713374137878 | 0.0 |
| `expanded_path_min` | 0.03952861577272415 | 0.022687993943691254 | 0.016840621829032898 | 0.0 |
| `expanded_path_p25` | 0.09580084681510925 | 0.09281398355960846 | 0.0029868632555007935 | 0.0 |
| `expanded_path_above50` | 0.0625 | 0.0625 | 0.0 | 0.0 |
| `expanded_path_above70` | 0.0625 | 0.0625 | 0.0 | 0.0 |
| `expanded_path_weighted` | 0.1601209561408029 | 0.1332021701621253 | 0.026918785978677612 | 0.0 |
| `expanded_path_mean_cosine` | 0.2298292623928425 | 0.22756660029082063 | 0.002262662102021862 | 0.0 |
| `expanded_path_log_words` | 2.3978952727983707 | 2.3978952727983707 | 0.0 | 0.0 |
| `expanded_all_exact` | 0.1875 | 0.125 | 0.0625 | 0.0 |
| `expanded_all_stem` | 0.1875 | 0.125 | 0.0625 | 0.0 |
| `expanded_all_mean` | 0.3870350122451782 | 0.3315538167953491 | 0.0554811954498291 | 0.18042909201091412 |
| `expanded_all_min` | 0.14980106055736542 | 0.13215383887290955 | 0.01764722168445587 | 0.0 |
| `expanded_all_p25` | 0.17126277089118958 | 0.17946507036685944 | -0.00820229947566986 | 0.0 |
| `expanded_all_above50` | 0.25 | 0.1875 | 0.0625 | 0.0 |
| `expanded_all_above70` | 0.1875 | 0.125 | 0.0625 | 0.0 |
| `expanded_all_weighted` | 0.3154422642652241 | 0.2599475253738762 | 0.05549473889134787 | 0.03135444862423172 |
| `expanded_all_mean_cosine` | 0.45458114590375165 | 0.26486042053685316 | 0.1897207253668985 | 0.0 |
| `expanded_all_log_words` | 4.23410650459726 | 3.871201010907891 | 0.36290549368936853 | 0.0 |
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
| `expanded_log_executable_lines` | 2.6390573296152584 | 1.3862943611198906 | 1.2527629684953678 | 0.0 |
| `expanded_log_comment_lines` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_log_owned_lines` | 2.772588722239781 | 1.791759469228055 | 0.9808292530117262 | -0.0006488693765360695 |
| `expanded_log_regions` | 1.0986122886681098 | 1.0986122886681098 | 0.0 | 0.0 |
| `expanded_documentation_fraction` | 0.1333333333333333 | 0.4 | -0.2666666666666667 | 0.0 |
| `expanded_query_negation` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_query_test` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_return` | 1.0986122886681098 | 0.6931471805599453 | 0.4054651081081645 | 0.0 |
| `expanded_op_raise` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_throw` | 0.6931471805599453 | 0.0 | 0.6931471805599453 | 0.0 |
| `expanded_op_panic` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_if` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_else` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_try` | 0.6931471805599453 | 0.0 | 0.6931471805599453 | 0.0 |
| `expanded_op_catch` | 0.6931471805599453 | 0.0 | 0.6931471805599453 | 0.0 |
| `expanded_op_except` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_for` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_while` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_match` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_switch` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_await` | 0.0 | 0.0 | 0.0 | 0.0 |
| `expanded_op_yield` | 0.0 | 0.0 | 0.0 | 0.0 |
| `code_original_raw` | 0.2566142678260803 | 0.1976790577173233 | 0.05893521010875702 | 0.0 |
| `code_original_to_max` | -0.08301687240600586 | -0.14195208251476288 | 0.05893521010875702 | 0.020549164773538863 |
| `code_original_range_relative` | 0.7667213137578038 | 0.601112468361407 | 0.16560884539639686 | 0.0 |
| `code_original_reciprocal_rank` | 0.03225806451612903 | 0.004149377593360996 | 0.028108686922768036 | -0.048368960551702075 |
| `code_expanded_raw` | 0.36511510610580444 | 0.1619878113269806 | 0.20312729477882385 | 0.0 |
| `code_expanded_to_max` | -0.02935558557510376 | -0.2324828803539276 | 0.20312729477882385 | 0.06627664680400354 |
| `code_expanded_range_relative` | 0.9290124976553192 | 0.4378112822174815 | 0.49120121543783773 | 0.0 |
| `code_expanded_reciprocal_rank` | 0.5 | 0.002150537634408602 | 0.4978494623655914 | 0.05865452344188945 |
| `view_contract_original_raw` | 0.2464347630739212 | 0.17728129029273987 | 0.06915347278118134 | 0.0 |
| `view_contract_original_to_max` | -0.05225934088230133 | -0.12141281366348267 | 0.06915347278118134 | 0.0 |
| `view_contract_original_range_relative` | 0.8442836503005504 | 0.6382281170939939 | 0.20605553320655656 | 0.0 |
| `view_contract_original_reciprocal_rank` | 0.027777777777777776 | 0.0037735849056603774 | 0.0240041928721174 | -0.027903040150546555 |
| `view_contract_expanded_raw` | 0.3654848635196686 | 0.15368112921714783 | 0.21180373430252075 | -0.029688732281110575 |
| `view_contract_expanded_to_max` | -0.003487139940261841 | -0.2152908742427826 | 0.21180373430252075 | 0.0 |
| `view_contract_expanded_range_relative` | 0.9915592433815243 | 0.47888014166539894 | 0.5126791017161254 | 0.0 |
| `view_contract_expanded_reciprocal_rank` | 0.5 | 0.002145922746781116 | 0.4978540772532189 | 0.0 |
| `view_implementation_original_raw` | 0.2566142678260803 | 0.1976790577173233 | 0.05893521010875702 | 0.0 |
| `view_implementation_original_to_max` | -0.08301687240600586 | -0.14195208251476288 | 0.05893521010875702 | 0.0 |
| `view_implementation_original_range_relative` | 0.7667213137578038 | 0.601112468361407 | 0.16560884539639686 | -0.02274194437299129 |
| `view_implementation_original_reciprocal_rank` | 0.03225806451612903 | 0.0041841004184100415 | 0.02807396409771899 | 0.0 |
| `view_implementation_expanded_raw` | 0.36511510610580444 | 0.1619878113269806 | 0.20312729477882385 | 0.10494645940819172 |
| `view_implementation_expanded_to_max` | -0.029355555772781372 | -0.23248285055160522 | 0.20312729477882385 | 0.32971941303905555 |
| `view_implementation_expanded_range_relative` | 0.9290125646072097 | 0.4378113137695791 | 0.4912012508376306 | 0.011244338431524545 |
| `view_implementation_expanded_reciprocal_rank` | 0.5 | 0.0021413276231263384 | 0.49785867237687365 | 0.3588931451873357 |

## Señales crudas de recuperación

Estos valores preceden al vector; por ejemplo BM25 pasa por log1p. No sumarlos al score del bosque.

| Señal | Elegido | Aceptable |
|---|---:|---:|
| `bm25_body` | 16.523099919600426 | ausente |
| `bm25_documentation` | 0.0 | ausente |
| `bm25_identity` | 10.011997784220924 | ausente |
| `bm25_path` | 4.720325808976902 | ausente |
| `bm25_signature` | 16.38533572910443 | ausente |
| `bm25f` | 20.19292502309304 | ausente |
| `cosine_behavior` | 0.5437089204788208 | 0.3080858290195465 |
| `cosine_code` | 0.36511510610580444 | 0.1976790577173233 |
| `cosine_code_expanded` | 0.36511510610580444 | 0.1619878113269806 |
| `cosine_code_original` | 0.2566142678260803 | 0.1976790577173233 |
| `cosine_identity` | 0.505810022354126 | 0.29566776752471924 |
| `cosine_view_contract_expanded` | 0.3654848635196686 | 0.15368112921714783 |
| `cosine_view_contract_original` | 0.2464347630739212 | 0.17728129029273987 |
| `cosine_view_implementation_expanded` | 0.36511510610580444 | 0.1619878113269806 |
| `cosine_view_implementation_original` | 0.2566142678260803 | 0.1976790577173233 |
| `proposal_code` | 0.5 | ausente |
| `proposal_expanded` | 1.0 | 0.009345794392523364 |
| `proposal_static` | 0.045454545454545456 | 0.004761904761904762 |
| `rrf` | 0.02832415420928403 | 0.003703703703703704 |
