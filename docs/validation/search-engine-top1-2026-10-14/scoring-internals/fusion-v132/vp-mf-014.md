# vp-mf-014: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which importable module discovers executable examples in Python modules and text files and provides a fixture for adding names to their execution namespace?

Pieza elegida: `src/_pytest/pathlib.py:_pytest.pathlib`.
Aceptable en top10: no; esta etapa no le calculó un score.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

[Explicación del bosque previo: cases](../cases/vp-mf-014.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/_pytest/pathlib.py:_pytest.pathlib | False | 1 | 1 | 1.7103320255369587 | 5.979776382446289 | 6 | 0.00819672131147541 | 0.007575757575757576 | 0.015772478887232988 | 1 |
| src/_pytest/python.py:_pytest.python | False | 3 | 4 | -3.012169004894323 | 6.0532379150390625 | 5 | 0.0078125 | 0.007692307692307693 | 0.015504807692307693 | 2 |
| testing/test_pathlib.py:testing.test_pathlib | False | 5 | 8 | -4.033159377721709 | 6.917649269104004 | 2 | 0.007352941176470588 | 0.008064516129032258 | 0.015417457305502846 | 3 |
| src/_pytest/fixtures.py:_pytest.fixtures | False | 7 | 7 | -3.9819220620244704 | 6.514365196228027 | 3 | 0.007462686567164179 | 0.007936507936507936 | 0.015399194503672116 | 4 |
| testing/python/fixtures.py:testing.python.fixtures | False | 10 | 6 | -3.4656298181749285 | 6.5043721199035645 | 4 | 0.007575757575757576 | 0.0078125 | 0.015388257575757576 | 5 |
| doc/en/example/assertion/failure_demo.py:doc.en.example.assertion.failure_demo | False | 8 | 10 | -5.133978046128881 | 6.975438117980957 | 1 | 0.007142857142857143 | 0.00819672131147541 | 0.015339578454332554 | 6 |
| src/_pytest/_py/path.py:_pytest._py.path | False | 2 | 2 | -2.200177229891107 | 5.344104766845703 | 9 | 0.008064516129032258 | 0.007246376811594203 | 0.015310892940626462 | 7 |
| src/_pytest/config/__init__.py:_pytest.config | False | 4 | 3 | -2.712446591573224 | 5.500591278076172 | 8 | 0.007936507936507936 | 0.007352941176470588 | 0.015289449112978524 | 8 |
| testing/acceptance_test.py:testing.acceptance_test | False | 6 | 5 | -3.41246832813059 | 5.872450828552246 | 7 | 0.007692307692307693 | 0.007462686567164179 | 0.015154994259471873 | 9 |
| src/_pytest/outcomes.py:_pytest.outcomes | False | 9 | 9 | -4.989744184294914 | 4.772144317626953 | 10 | 0.007246376811594203 | 0.007142857142857143 | 0.014389233954451346 | 10 |
