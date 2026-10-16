# vp-cs-078: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which class documents set algebra over accepted package versions and a matching-prerelease-policy requirement for binary set operations, while preventing direct construction in favor of factories?

Pieza elegida: `tests/test_ranges.py:TestSetRelations`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.00011981094658910368. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tests/test_ranges.py:TestSetRelations | False | 2 | 2 | -2.9970569196357997 | 9.27365493774414 | 2 | 0.008064516129032258 | 0.008064516129032258 | 0.016129032258064516 | 1 |
| src/packaging/ranges.py:VersionRange | True | 1 | 1 | 2.9819577668747637 | 8.893479347229004 | 4 | 0.00819672131147541 | 0.0078125 | 0.016009221311475412 | 2 |
| tests/test_ranges.py:TestPrereleaseRegion | False | 3 | 5 | -4.565288026228088 | 9.723644256591797 | 1 | 0.007692307692307693 | 0.00819672131147541 | 0.015889029003783105 | 3 |
| tests/test_ranges.py:TestSetAlgebra | False | 6 | 4 | -4.517716323741894 | 9.22590446472168 | 3 | 0.0078125 | 0.007936507936507936 | 0.015749007936507936 | 4 |
| src/packaging/specifiers.py:Specifier | False | 8 | 3 | -4.200468232340665 | 7.760077953338623 | 7 | 0.007936507936507936 | 0.007462686567164179 | 0.015399194503672116 | 5 |
| src/packaging/specifiers.py:SpecifierSet | False | 5 | 7 | -4.935709638231533 | 8.231551170349121 | 5 | 0.007462686567164179 | 0.007692307692307693 | 0.015154994259471873 | 6 |
| tests/test_specifiers.py:TestSpecifierSetToRangeEquivalence | False | 9 | 6 | -4.771198020214643 | 7.427011966705322 | 8 | 0.007575757575757576 | 0.007352941176470588 | 0.014928698752228164 | 7 |
| src/packaging/specifiers.py:BaseSpecifier | False | 10 | 9 | -5.073124786802679 | 7.7811079025268555 | 6 | 0.007246376811594203 | 0.007575757575757576 | 0.01482213438735178 | 8 |
| src/packaging/requirements.py:Requirement | False | 7 | 8 | -5.065070808597587 | 5.695948600769043 | 9 | 0.007352941176470588 | 0.007246376811594203 | 0.01459931798806479 | 9 |
| src/packaging/pylock.py:Pylock | False | 4 | 10 | -5.443463059219482 | 4.5627241134643555 | 10 | 0.007142857142857143 | 0.007142857142857143 | 0.014285714285714285 | 10 |
