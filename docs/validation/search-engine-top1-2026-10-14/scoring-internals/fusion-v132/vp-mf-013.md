# vp-mf-013: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> ¿Qué módulo importable conserva valores de caché entre sesiones de pruebas y registra los complementos para ejecutar primero los fallos previos o las pruebas nuevas?

Pieza elegida: `src/_pytest/config/__init__.py:_pytest.config`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.00023674242424242403. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-013.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-013.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/_pytest/config/__init__.py:_pytest.config | False | 1 | 1 | -0.37965570698015055 | 6.312235355377197 | 4 | 0.00819672131147541 | 0.0078125 | 0.016009221311475412 | 1 |
| src/_pytest/cacheprovider.py:_pytest.cacheprovider | True | 4 | 6 | -2.6933631397541458 | 7.151778221130371 | 1 | 0.007575757575757576 | 0.00819672131147541 | 0.015772478887232988 | 2 |
| testing/conftest.py:testing.conftest | False | 3 | 2 | -0.7099305762428162 | 5.141780853271484 | 8 | 0.008064516129032258 | 0.007352941176470588 | 0.015417457305502846 | 3 |
| testing/test_pluginmanager.py:testing.test_pluginmanager | False | 2 | 4 | -1.8711476531002829 | 5.607159614562988 | 6 | 0.0078125 | 0.007575757575757576 | 0.015388257575757576 | 4 |
| testing/test_cacheprovider.py:testing.test_cacheprovider | False | 10 | 8 | -3.7342368012562157 | 6.7822980880737305 | 3 | 0.007352941176470588 | 0.007936507936507936 | 0.015289449112978524 | 5 |
| testing/test_session.py:testing.test_session | False | 9 | 10 | -4.682471288246291 | 6.835505485534668 | 2 | 0.007142857142857143 | 0.008064516129032258 | 0.0152073732718894 | 6 |
| testing/example_scripts/issue_519.py:testing.example_scripts.issue_519 | False | 6 | 3 | -1.4396354762461991 | 5.077732086181641 | 9 | 0.007936507936507936 | 0.007246376811594203 | 0.01518288474810214 | 7 |
| testing/python/fixtures.py:testing.python.fixtures | False | 7 | 5 | -2.2567020014414596 | 5.471126556396484 | 7 | 0.007692307692307693 | 0.007462686567164179 | 0.015154994259471873 | 8 |
| src/_pytest/python.py:_pytest.python | False | 8 | 9 | -3.787044990192934 | 6.1484456062316895 | 5 | 0.007246376811594203 | 0.007692307692307693 | 0.014938684503901897 | 9 |
| src/_pytest/_py/path.py:_pytest._py.path | False | 5 | 7 | -2.748469353397312 | 3.5942955017089844 | 10 | 0.007462686567164179 | 0.007142857142857143 | 0.014605543710021322 | 10 |
