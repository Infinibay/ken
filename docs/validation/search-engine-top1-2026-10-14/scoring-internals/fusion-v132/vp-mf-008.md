# vp-mf-008: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> ¿Qué módulo de implementación ofrece representaciones de objetos con límite de longitud y sustituye los fallos del método de representación por información de la excepción?

Pieza elegida: `src/_pytest/_code/code.py:_pytest._code.code`.
Aceptable en top10: sí, puesto final4.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.00034981343283582364. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-008.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-008.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/_pytest/_code/code.py:_pytest._code.code | False | 1 | 1 | 1.2257269514047027 | 5.730114459991455 | 4 | 0.00819672131147541 | 0.0078125 | 0.016009221311475412 | 1 |
| src/_pytest/python.py:_pytest.python | False | 3 | 3 | -2.2707900852751193 | 6.896831035614014 | 3 | 0.007936507936507936 | 0.007936507936507936 | 0.015873015873015872 | 2 |
| src/_pytest/nodes.py:_pytest.nodes | False | 2 | 2 | -0.7256319593899081 | 5.648466110229492 | 5 | 0.008064516129032258 | 0.007692307692307693 | 0.01575682382133995 | 3 |
| src/_pytest/_io/saferepr.py:_pytest._io.saferepr | True | 4 | 7 | -4.8884562109108005 | 8.383932113647461 | 1 | 0.007462686567164179 | 0.00819672131147541 | 0.01565940787863959 | 4 |
| src/_pytest/assertion/rewrite.py:_pytest.assertion.rewrite | False | 6 | 6 | -4.848736055345791 | 7.204290866851807 | 2 | 0.007575757575757576 | 0.008064516129032258 | 0.015640273704789834 | 5 |
| doc/en/example/nonpython/conftest.py:doc.en.example.nonpython.conftest | False | 8 | 4 | -4.718959002111502 | 4.881438255310059 | 8 | 0.0078125 | 0.007352941176470588 | 0.015165441176470588 | 6 |
| testing/code/test_excinfo.py:testing.code.test_excinfo | False | 7 | 5 | -4.786000889463748 | 5.000722885131836 | 7 | 0.007692307692307693 | 0.007462686567164179 | 0.015154994259471873 | 7 |
| src/_pytest/doctest.py:_pytest.doctest | False | 5 | 8 | -4.9617898496622646 | 5.416118621826172 | 6 | 0.007352941176470588 | 0.007575757575757576 | 0.014928698752228164 | 8 |
| src/_pytest/raises.py:_pytest.raises | False | 10 | 9 | -5.581362706316026 | 3.9458320140838623 | 10 | 0.007246376811594203 | 0.007142857142857143 | 0.014389233954451346 | 9 |
| src/_pytest/_io/pprint.py:_pytest._io.pprint | False | 9 | 10 | -5.727218194365717 | 4.770077705383301 | 9 | 0.007142857142857143 | 0.007246376811594203 | 0.014389233954451346 | 10 |
