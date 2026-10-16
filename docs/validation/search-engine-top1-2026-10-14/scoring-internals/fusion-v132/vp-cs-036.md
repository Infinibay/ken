# vp-cs-036: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Where are percent escapes decoded to bytes, first UTF-8 encoding text input and preserving an invalid escape literally instead of failing?

Pieza elegida: `boltons/urlutils.py:unquote`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0003924185574106266. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-cs-036.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| boltons/urlutils.py:unquote | False | 1 | 1 | 3.382416229937375 | 9.770499229431152 | 1 | 0.00819672131147541 | 0.00819672131147541 | 0.01639344262295082 | 1 |
| boltons/urlutils.py:unquote_to_bytes | True | 3 | 3 | 3.0597503969428574 | 7.304409027099609 | 2 | 0.007936507936507936 | 0.008064516129032258 | 0.016001024065540194 | 2 |
| boltons/urlutils.py:URL.__init__ | False | 5 | 5 | 1.5692687843461475 | 7.210836410522461 | 3 | 0.007692307692307693 | 0.007936507936507936 | 0.01562881562881563 | 3 |
| boltons/urlutils.py:quote_path_part | False | 4 | 4 | 1.5830779895086786 | 5.297670364379883 | 6 | 0.0078125 | 0.007575757575757576 | 0.015388257575757576 | 4 |
| boltons/strutils.py:asciify | False | 2 | 2 | 3.1008372636254813 | 4.446314811706543 | 9 | 0.008064516129032258 | 0.007246376811594203 | 0.015310892940626462 | 5 |
| boltons/strutils.py:strip_ansi | False | 9 | 9 | -1.9068079755773675 | 6.542577743530273 | 4 | 0.007246376811594203 | 0.0078125 | 0.015058876811594204 | 6 |
| boltons/urlutils.py:quote_userinfo_part | False | 8 | 8 | -0.23581533098925972 | 5.917601585388184 | 5 | 0.007352941176470588 | 0.007692307692307693 | 0.015045248868778281 | 7 |
| boltons/urlutils.py:quote_query_part | False | 6 | 6 | 1.233322218343826 | 5.172394275665283 | 7 | 0.007575757575757576 | 0.007462686567164179 | 0.015038444142921756 | 8 |
| boltons/strutils.py:is_ascii | False | 7 | 7 | 0.2346806829990037 | 4.384622573852539 | 10 | 0.007462686567164179 | 0.007142857142857143 | 0.014605543710021322 | 9 |
| boltons/tbutils.py:ParsedException.from_string | False | 10 | 10 | -2.91137110733611 | 5.086989402770996 | 8 | 0.007142857142857143 | 0.007352941176470588 | 0.014495798319327732 | 10 |
