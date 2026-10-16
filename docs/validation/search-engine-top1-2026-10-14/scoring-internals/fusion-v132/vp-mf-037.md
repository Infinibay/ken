# vp-mf-037: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> ¿Qué módulo importable contiene las definiciones del decorador moderno que usa slots por defecto y de la API para declarar campos?

Pieza elegida: `typing_tests/pyrefly.py:typing_tests.pyrefly`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-037.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-037.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| typing_tests/pyrefly.py:typing_tests.pyrefly | False | 1 | 1 | -1.3529852505858038 | 6.426947593688965 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| src/attr/_next_gen.py:attr._next_gen | True | 2 | 2 | -1.910982556805473 | 7.268632411956787 | 1 | 0.008064516129032258 | 0.00819672131147541 | 0.01626123744050767 | 2 |
| src/attr/__init__.py:attr | False | 4 | 3 | -3.272468880896734 | 6.051624298095703 | 5 | 0.007936507936507936 | 0.007692307692307693 | 0.01562881562881563 | 3 |
| tests/test_functional.py:tests.test_functional | False | 7 | 5 | -4.732226044684668 | 6.092838287353516 | 4 | 0.007692307692307693 | 0.0078125 | 0.015504807692307693 | 4 |
| src/attrs/__init__.pyi:attrs | False | 3 | 4 | -3.393089754248389 | 6.043916702270508 | 6 | 0.0078125 | 0.007575757575757576 | 0.015388257575757576 | 5 |
| src/attr/_make.py:attr._make | False | 5 | 8 | -5.087820195049775 | 6.3281660079956055 | 3 | 0.007352941176470588 | 0.007936507936507936 | 0.015289449112978524 | 6 |
| src/attrs/__init__.py:attrs | False | 8 | 6 | -4.766965682322672 | 5.816005706787109 | 7 | 0.007575757575757576 | 0.007462686567164179 | 0.015038444142921756 | 7 |
| tests/conftest.py:tests.conftest | False | 6 | 7 | -4.816685909162021 | 5.616201400756836 | 8 | 0.007462686567164179 | 0.007352941176470588 | 0.014815627743634766 | 8 |
| src/attr/_funcs.py:attr._funcs | False | 9 | 9 | -5.200081239419819 | 5.0433220863342285 | 9 | 0.007246376811594203 | 0.007246376811594203 | 0.014492753623188406 | 9 |
| tests/test_slots.py:tests.test_slots | False | 10 | 10 | -5.3149989883685524 | 5.015079021453857 | 10 | 0.007142857142857143 | 0.007142857142857143 | 0.014285714285714285 | 10 |
