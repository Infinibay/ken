# vp-cs-044: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which method populates a caller-supplied map from a CSV record, returns that same map unchanged if no header mapping exists and skips header indexes at or above the available field count?

Pieza elegida: `src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord.get`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0005164264939185627. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-cs-044.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord.get | False | 1 | 1 | 4.3680425286148985 | 8.810738563537598 | 1 | 0.00819672131147541 | 0.00819672131147541 | 0.01639344262295082 | 1 |
| src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord.putIn | True | 4 | 4 | 1.4555405051925983 | 8.746500015258789 | 2 | 0.0078125 | 0.008064516129032258 | 0.015877016129032258 | 2 |
| src/main/java/org/apache/commons/csv/CSVParser.java:CSVParser.getHeaderMap | False | 3 | 3 | 2.473134283396488 | 8.00539779663086 | 4 | 0.007936507936507936 | 0.0078125 | 0.015749007936507936 | 3 |
| src/main/java/org/apache/commons/csv/CSVParser.java:CSVParser.createHeaders | False | 2 | 2 | 3.732152223392683 | 7.494195461273193 | 6 | 0.008064516129032258 | 0.007575757575757576 | 0.015640273704789834 | 4 |
| src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord.isMapped | False | 6 | 6 | -1.528644824498343 | 7.921348571777344 | 5 | 0.007575757575757576 | 0.007692307692307693 | 0.015268065268065269 | 5 |
| src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord.getHeaderMapRaw | False | 5 | 5 | -1.1108459801417905 | 7.232407569885254 | 7 | 0.007692307692307693 | 0.007462686567164179 | 0.015154994259471873 | 6 |
| src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord.isConsistent | False | 10 | 10 | -2.0545742284561457 | 8.118881225585938 | 3 | 0.007142857142857143 | 0.007936507936507936 | 0.015079365079365078 | 7 |
| src/test/java/org/apache/commons/csv/CSVParserTest.java:CSVParserTest.testProvidedHeaderAuto | False | 7 | 7 | -1.6923526117629284 | 7.0865888595581055 | 8 | 0.007462686567164179 | 0.007352941176470588 | 0.014815627743634766 | 8 |
| src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord.toMap | False | 8 | 8 | -1.7892966056693715 | 5.97667932510376 | 10 | 0.007352941176470588 | 0.007142857142857143 | 0.014495798319327732 | 9 |
| src/test/java/org/apache/commons/csv/CSVParserTest.java:CSVParserTest.testProvidedHeader | False | 9 | 9 | -1.8750119180113485 | 7.045977592468262 | 9 | 0.007246376811594203 | 0.007246376811594203 | 0.014492753623188406 | 10 |
