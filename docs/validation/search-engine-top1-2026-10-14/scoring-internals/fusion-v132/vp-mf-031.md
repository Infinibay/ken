# vp-mf-031: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which importable module supplies a list-compatible container backed by multiple sublists for insertion-heavy workloads and another list that moves useful items towards the front?

Pieza elegida: `tests/test_listutils.py:tests.test_listutils`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.00012400793650793607. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tests/test_listutils.py:tests.test_listutils | False | 3 | 3 | -3.2310663650485725 | 8.580317497253418 | 1 | 0.007936507936507936 | 0.00819672131147541 | 0.016133229247983348 | 1 |
| boltons/listutils.py:boltons.listutils | True | 1 | 1 | 3.0599200601137833 | 6.927835464477539 | 4 | 0.00819672131147541 | 0.0078125 | 0.016009221311475412 | 2 |
| boltons/urlutils.py:boltons.urlutils | False | 5 | 7 | -5.109440677917602 | 7.221229553222656 | 2 | 0.007462686567164179 | 0.008064516129032258 | 0.015527202696196438 | 3 |
| boltons/dictutils.py:boltons.dictutils | False | 6 | 6 | -5.006337073443325 | 7.200537204742432 | 3 | 0.007575757575757576 | 0.007936507936507936 | 0.015512265512265512 | 4 |
| boltons/iterutils.py:boltons.iterutils | False | 8 | 4 | -4.319306106144501 | 5.501533508300781 | 5 | 0.0078125 | 0.007692307692307693 | 0.015504807692307693 | 5 |
| boltons/namedutils.py:boltons.namedutils | False | 2 | 2 | -2.067557592228935 | 3.6413679122924805 | 8 | 0.008064516129032258 | 0.007352941176470588 | 0.015417457305502846 | 6 |
| boltons/strutils.py:boltons.strutils | False | 4 | 5 | -4.770393719110007 | 4.631656646728516 | 6 | 0.007692307692307693 | 0.007575757575757576 | 0.015268065268065269 | 7 |
| boltons/tableutils.py:boltons.tableutils | False | 7 | 9 | -5.408202587782312 | 4.369056224822998 | 7 | 0.007246376811594203 | 0.007462686567164179 | 0.014709063378758382 | 8 |
| boltons/funcutils.py:boltons.funcutils | False | 10 | 8 | -5.164153216701389 | 3.5606212615966797 | 9 | 0.007352941176470588 | 0.007246376811594203 | 0.01459931798806479 | 9 |
| boltons/statsutils.py:boltons.statsutils | False | 9 | 10 | -5.4433166002391715 | 3.0339972972869873 | 10 | 0.007142857142857143 | 0.007142857142857143 | 0.014285714285714285 | 10 |
