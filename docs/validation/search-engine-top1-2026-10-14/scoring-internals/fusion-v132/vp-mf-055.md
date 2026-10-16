# vp-mf-055: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which physical benchmark file simulates dependency resolution by filtering candidate versions against constraints and taking the highest remaining version?

Pieza elegida: `src/packaging/ranges.py:`.
Aceptable en top10: sí, puesto final3.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0003607503607503601. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-055.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-055.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/packaging/ranges.py: | False | 1 | 1 | -1.4900778484592752 | 6.662242889404297 | 3 | 0.00819672131147541 | 0.007936507936507936 | 0.016133229247983348 | 1 |
| tests/test_ranges.py: | False | 5 | 4 | -4.486505312254839 | 7.764463901519775 | 2 | 0.0078125 | 0.008064516129032258 | 0.015877016129032258 | 2 |
| benchmarks/resolver.py: | True | 4 | 6 | -4.583942951279655 | 7.982632160186768 | 1 | 0.007575757575757576 | 0.00819672131147541 | 0.015772478887232988 | 3 |
| tests/property/test_specifier_implied.py: | False | 6 | 3 | -4.4186890941289905 | 6.539003849029541 | 4 | 0.007936507936507936 | 0.0078125 | 0.015749007936507936 | 4 |
| tests/property/test_specifier_comparison.py: | False | 7 | 2 | -3.972058560159786 | 6.289614677429199 | 6 | 0.008064516129032258 | 0.007575757575757576 | 0.015640273704789834 | 5 |
| src/packaging/_ranges.py: | False | 2 | 5 | -4.494483226573781 | 5.074434280395508 | 9 | 0.007692307692307693 | 0.007246376811594203 | 0.014938684503901897 | 6 |
| tests/property/strategies.py: | False | 10 | 9 | -5.020839111162792 | 6.3431077003479 | 5 | 0.007246376811594203 | 0.007692307692307693 | 0.014938684503901897 | 7 |
| benchmarks/version.py: | False | 3 | 8 | -4.789577393289116 | 5.8572998046875 | 7 | 0.007352941176470588 | 0.007462686567164179 | 0.014815627743634766 | 8 |
| tests/property/test_specifier_matching.py: | False | 8 | 7 | -4.758595840976333 | 4.892967700958252 | 10 | 0.007462686567164179 | 0.007142857142857143 | 0.014605543710021322 | 9 |
| src/packaging/pylock.py: | False | 9 | 10 | -5.35454220488483 | 5.355319499969482 | 8 | 0.007142857142857143 | 0.007352941176470588 | 0.014495798319327732 | 10 |
