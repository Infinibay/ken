# vp-cs-037: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Where does a bounded read bridge multiple input files, advance to the next file after a short read, and join the pieces using the reader’s bytes-or-text joiner?

Pieza elegida: `boltons/ioutils.py:MultiFileReader.__init__`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-cs-037.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| boltons/ioutils.py:MultiFileReader.__init__ | False | 1 | 1 | 4.598256967876293 | 7.597865104675293 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| boltons/ioutils.py:MultiFileReader.read | True | 2 | 2 | 4.543972093880106 | 9.572099685668945 | 1 | 0.008064516129032258 | 0.00819672131147541 | 0.01626123744050767 | 2 |
| boltons/jsonutils.py:reverse_iter_lines | False | 5 | 5 | -2.0605680843354683 | 5.234766960144043 | 3 | 0.007692307692307693 | 0.007936507936507936 | 0.01562881562881563 | 3 |
| tests/test_ioutils.py:TestMultiFileReader.test_read_seek_bytes | False | 6 | 6 | -3.652866661150443 | 4.497922897338867 | 5 | 0.007575757575757576 | 0.007692307692307693 | 0.015268065268065269 | 4 |
| boltons/socketutils.py:BufferedSocket.recv_until | False | 3 | 3 | -0.4259955690607165 | 2.973863363265991 | 9 | 0.007936507936507936 | 0.007246376811594203 | 0.01518288474810214 | 5 |
| boltons/socketutils.py:BufferedSocket.recv_size | False | 4 | 4 | -1.667738299147363 | 3.0464224815368652 | 8 | 0.0078125 | 0.007352941176470588 | 0.015165441176470588 | 6 |
| tests/test_ioutils.py:TestMultiFileReader.test_no_mixed_bytes_and_text | False | 9 | 9 | -4.652284572730326 | 4.599449157714844 | 4 | 0.007246376811594203 | 0.0078125 | 0.015058876811594204 | 7 |
| tests/test_ioutils.py:TestMultiFileReader.test_read_seek_text | False | 8 | 8 | -4.172766204636056 | 4.224726676940918 | 6 | 0.007352941176470588 | 0.007575757575757576 | 0.014928698752228164 | 8 |
| boltons/ioutils.py:MultiFileReader.seek | False | 7 | 7 | -3.8397386660562542 | 3.385185956954956 | 7 | 0.007462686567164179 | 0.007462686567164179 | 0.014925373134328358 | 9 |
| boltons/socketutils.py:BufferedSocket.recv_close | False | 10 | 10 | -4.716318904717038 | 1.3998695611953735 | 10 | 0.007142857142857143 | 0.007142857142857143 | 0.014285714285714285 | 10 |
