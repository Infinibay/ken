# vp-mf-065: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which physical source file adapts heterogeneous in-memory data into tables and provides both console-text and HTML renderings?

Pieza elegida: `misc/table_html_app.py:`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-065.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-065.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| misc/table_html_app.py: | False | 1 | 1 | 1.4504543159759626 | 5.177783489227295 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| boltons/tableutils.py: | True | 2 | 2 | 0.4365103835682789 | 7.444003105163574 | 1 | 0.008064516129032258 | 0.00819672131147541 | 0.01626123744050767 | 2 |
| CHANGELOG.md: | False | 3 | 3 | -3.984088993390402 | 4.9966020584106445 | 3 | 0.007936507936507936 | 0.007936507936507936 | 0.015873015873015872 | 3 |
| boltons/ecoutils.py: | False | 9 | 6 | -5.085975150747013 | 3.8939735889434814 | 4 | 0.007575757575757576 | 0.0078125 | 0.015388257575757576 | 4 |
| boltons/tbutils.py: | False | 10 | 4 | -4.212673513087091 | 2.8930699825286865 | 8 | 0.0078125 | 0.007352941176470588 | 0.015165441176470588 | 5 |
| docs/ioutils.rst: | False | 6 | 5 | -5.020055265729444 | 3.5016257762908936 | 7 | 0.007692307692307693 | 0.007462686567164179 | 0.015154994259471873 | 6 |
| boltons/ioutils.py: | False | 5 | 7 | -5.167139444167615 | 3.648343324661255 | 5 | 0.007462686567164179 | 0.007692307692307693 | 0.015154994259471873 | 7 |
| boltons/strutils.py: | False | 4 | 8 | -5.400385129012707 | 3.579291343688965 | 6 | 0.007352941176470588 | 0.007575757575757576 | 0.014928698752228164 | 8 |
| boltons/cacheutils.py: | False | 8 | 9 | -5.507637277726314 | 1.7468032836914062 | 10 | 0.007246376811594203 | 0.007142857142857143 | 0.014389233954451346 | 9 |
| boltons/statsutils.py: | False | 7 | 10 | -5.510422716058794 | 2.235851764678955 | 9 | 0.007142857142857143 | 0.007246376811594203 | 0.014389233954451346 | 10 |
