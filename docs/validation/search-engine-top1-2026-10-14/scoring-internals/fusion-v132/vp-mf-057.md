# vp-mf-057: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which physical plugin file records the failing test for resuming a later session and removes earlier collected tests when resuming from the saved item?

Pieza elegida: `src/_pytest/cacheprovider.py:`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0006018295618680815. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-057.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-057.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/_pytest/cacheprovider.py: | False | 1 | 1 | 0.01256682073490389 | 7.986085891723633 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| src/_pytest/stepwise.py: | True | 2 | 7 | -3.287767344858821 | 8.035579681396484 | 1 | 0.007462686567164179 | 0.00819672131147541 | 0.01565940787863959 | 2 |
| testing/test_collection.py: | False | 6 | 2 | -2.0873101590372247 | 6.130821228027344 | 7 | 0.008064516129032258 | 0.007462686567164179 | 0.015527202696196438 | 3 |
| testing/test_terminal.py: | False | 7 | 6 | -3.182419834442268 | 7.319256782531738 | 3 | 0.007575757575757576 | 0.007936507936507936 | 0.015512265512265512 | 4 |
| src/_pytest/fixtures.py: | False | 4 | 4 | -2.7924623910648196 | 6.2447509765625 | 6 | 0.0078125 | 0.007575757575757576 | 0.015388257575757576 | 5 |
| src/_pytest/logging.py: | False | 3 | 5 | -3.1289494227492094 | 6.542801856994629 | 5 | 0.007692307692307693 | 0.007692307692307693 | 0.015384615384615385 | 6 |
| testing/test_cacheprovider.py: | False | 5 | 8 | -3.705732686647996 | 6.758217811584473 | 4 | 0.007352941176470588 | 0.0078125 | 0.015165441176470588 | 7 |
| src/_pytest/main.py: | False | 8 | 3 | -2.7437738482167164 | 4.500509738922119 | 10 | 0.007936507936507936 | 0.007142857142857143 | 0.015079365079365078 | 8 |
| testing/test_session.py: | False | 10 | 10 | -4.680505967023063 | 6.002633094787598 | 8 | 0.007142857142857143 | 0.007352941176470588 | 0.014495798319327732 | 9 |
| testing/deprecated_test.py: | False | 9 | 9 | -4.4249063875867005 | 4.982118606567383 | 9 | 0.007246376811594203 | 0.007246376811594203 | 0.014492753623188406 | 10 |
