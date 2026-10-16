# vp-cs-086: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Localizá packaging.pylock._toml_dict_factory y mostrá cómo omite entradas con None y cambia los guiones bajos de las claves por guiones para el diccionario de salida.

Pieza elegida: `src/packaging/pylock.py:Pylock.to_dict`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-cs-086.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/packaging/pylock.py:Pylock.to_dict | False | 1 | 1 | 1.283496660965592 | 8.884458541870117 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| src/packaging/pylock.py:_toml_dict_factory | True | 2 | 2 | 1.048735051150486 | 10.798036575317383 | 1 | 0.008064516129032258 | 0.00819672131147541 | 0.01626123744050767 | 2 |
| src/packaging/pylock.py:Pylock.from_dict | False | 3 | 3 | -1.1051118953405856 | 7.044414520263672 | 5 | 0.007936507936507936 | 0.007692307692307693 | 0.01562881562881563 | 3 |
| src/packaging/pylock.py:Package._from_dict | False | 4 | 4 | -2.4091334021473743 | 7.543081760406494 | 4 | 0.0078125 | 0.0078125 | 0.015625 | 4 |
| src/packaging/pylock.py:_get_object | False | 6 | 6 | -3.2171822004268535 | 8.353073120117188 | 3 | 0.007575757575757576 | 0.007936507936507936 | 0.015512265512265512 | 5 |
| src/packaging/pylock.py:Pylock.select | False | 5 | 5 | -2.9524648830982954 | 6.610423564910889 | 8 | 0.007692307692307693 | 0.007352941176470588 | 0.015045248868778281 | 6 |
| tests/test_pylock.py:test_toml_roundtrip | False | 9 | 9 | -3.589458873776216 | 6.759522438049316 | 6 | 0.007246376811594203 | 0.007575757575757576 | 0.01482213438735178 | 7 |
| src/packaging/pylock.py:Pylock._from_dict | False | 8 | 8 | -3.443627681929121 | 6.671317100524902 | 7 | 0.007352941176470588 | 0.007462686567164179 | 0.014815627743634766 | 8 |
| src/packaging/pylock.py:PackageSdist._from_dict | False | 7 | 7 | -3.4316641432959694 | 5.908809661865234 | 9 | 0.007462686567164179 | 0.007246376811594203 | 0.014709063378758382 | 9 |
| src/packaging/pylock.py:PackageWheel._from_dict | False | 10 | 10 | -4.0628624838116325 | 5.89520788192749 | 10 | 0.007142857142857143 | 0.007142857142857143 | 0.014285714285714285 | 10 |
