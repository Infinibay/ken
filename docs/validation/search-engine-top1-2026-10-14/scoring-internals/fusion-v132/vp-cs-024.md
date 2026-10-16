# vp-cs-024: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> ¿Dónde se compone una conversión que mezcla funciones ordinarias con convertidores que necesitan instancia y campo, pasa ese contexto sólo a los convertidores que lo admiten e infiere las anotaciones desde el primero y el último?

Pieza elegida: `src/attr/_make.py:Converter.__init__`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-cs-024.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/attr/_make.py:Converter.__init__ | False | 1 | 1 | 3.0602894032910473 | 8.243124008178711 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| src/attr/_make.py:pipe | True | 2 | 2 | 2.476388989496707 | 8.818075180053711 | 1 | 0.008064516129032258 | 0.00819672131147541 | 0.01626123744050767 | 2 |
| src/attr/converters.py:optional | False | 3 | 3 | 0.21988289778773093 | 7.615753173828125 | 3 | 0.007936507936507936 | 0.007936507936507936 | 0.015873015873015872 | 3 |
| tests/test_converters.py:TestConverter.test_annotations_if_last_in_pipe | False | 4 | 4 | -4.24614470638449 | 6.725978851318359 | 5 | 0.0078125 | 0.007692307692307693 | 0.015504807692307693 | 4 |
| src/attr/__init__.pyi:Converter.__init__ | False | 7 | 7 | -5.029760888054363 | 7.042840003967285 | 4 | 0.007462686567164179 | 0.0078125 | 0.01527518656716418 | 5 |
| src/attr/__init__.pyi:Converter.__init__ | False | 5 | 5 | -4.354108279159993 | 6.6717119216918945 | 6 | 0.007692307692307693 | 0.007575757575757576 | 0.015268065268065269 | 6 |
| src/attr/__init__.pyi:Converter.__init__ | False | 6 | 6 | -4.5316186359585275 | 5.4651947021484375 | 9 | 0.007575757575757576 | 0.007246376811594203 | 0.01482213438735178 | 7 |
| tests/test_converters.py:TestConverter.test_annotations_if_last_in_pipe.wrapped | False | 9 | 9 | -5.647911664785888 | 6.600780487060547 | 7 | 0.007246376811594203 | 0.007462686567164179 | 0.014709063378758382 | 8 |
| src/attr/_make.py:Converter.__getstate__ | False | 8 | 8 | -5.122801405354151 | 6.2411041259765625 | 8 | 0.007352941176470588 | 0.007352941176470588 | 0.014705882352941176 | 9 |
| src/attr/__init__.pyi:Converter.__init__ | False | 10 | 10 | -5.6919696816714795 | 4.650491714477539 | 10 | 0.007142857142857143 | 0.007142857142857143 | 0.014285714285714285 | 10 |
