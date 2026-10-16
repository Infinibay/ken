# vp-mf-077: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which physical source file specializes the validator for JSON Schema draft 2020-12, enabling dynamic references and unevaluated tracking and registering that draft's vocabularies?

Pieza elegida: `lib/refs/json-schema-2020-12/meta/unevaluated.json:`.
Aceptable en top10: no; esta etapa no le calculó un score.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

[Explicación del bosque previo: cases](../cases/vp-mf-077.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lib/refs/json-schema-2020-12/meta/unevaluated.json: | False | 1 | 1 | 3.444868233739839 | 10.017545700073242 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| lib/refs/json-schema-2020-12/schema.json: | False | 3 | 3 | 0.23987409721651737 | 10.424200057983398 | 1 | 0.007936507936507936 | 0.00819672131147541 | 0.016133229247983348 | 2 |
| lib/refs/json-schema-2020-12/meta/validation.json: | False | 2 | 2 | 1.640327487605282 | 9.900044441223145 | 3 | 0.008064516129032258 | 0.007936507936507936 | 0.016001024065540194 | 3 |
| lib/refs/json-schema-2020-12/meta/content.json: | False | 6 | 6 | -2.281292937724516 | 9.579089164733887 | 4 | 0.007575757575757576 | 0.0078125 | 0.015388257575757576 | 4 |
| lib/refs/json-schema-2020-12/meta/applicator.json: | False | 5 | 5 | -2.254010376723203 | 9.547094345092773 | 5 | 0.007692307692307693 | 0.007692307692307693 | 0.015384615384615385 | 5 |
| lib/refs/json-schema-2020-12/meta/meta-data.json: | False | 4 | 4 | -1.7181384994232058 | 9.308212280273438 | 7 | 0.0078125 | 0.007462686567164179 | 0.01527518656716418 | 6 |
| lib/refs/json-schema-2020-12/meta/format-annotation.json: | False | 7 | 7 | -2.4668624614596575 | 9.162652969360352 | 8 | 0.007462686567164179 | 0.007352941176470588 | 0.014815627743634766 | 7 |
| lib/refs/json-schema-2020-12/meta/core.json: | False | 10 | 10 | -4.259749519678264 | 9.446708679199219 | 6 | 0.007142857142857143 | 0.007575757575757576 | 0.014718614718614718 | 8 |
| lib/refs/json-schema-2019-09/meta/validation.json: | False | 8 | 8 | -4.200621724084397 | 7.301052093505859 | 10 | 0.007352941176470588 | 0.007142857142857143 | 0.014495798319327732 | 9 |
| lib/refs/json-schema-2019-09/schema.json: | False | 9 | 9 | -4.223282028165383 | 7.68555212020874 | 9 | 0.007246376811594203 | 0.007246376811594203 | 0.014492753623188406 | 10 |
