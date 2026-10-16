# vp-cs-041: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which class for parsed CSV records declares that it is iterable over strings, provides indexed access to stored fields and marks its originating parser as nonserialized state?

Pieza elegida: `src/main/java/org/apache/commons/csv/CSVParser.java:CSVParser`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.0. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-cs-041.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-cs-041.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| src/main/java/org/apache/commons/csv/CSVParser.java:CSVParser | False | 1 | 1 | 3.270463592048486 | 8.90343952178955 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| src/main/java/org/apache/commons/csv/CSVRecord.java:CSVRecord | True | 2 | 2 | 1.4513316727460235 | 9.34813117980957 | 1 | 0.008064516129032258 | 0.00819672131147541 | 0.01626123744050767 | 2 |
| src/main/java/org/apache/commons/csv/CSVParser.java:CSVParser.CSVRecordIterator | False | 3 | 3 | -2.1161814167754307 | 8.353466033935547 | 5 | 0.007936507936507936 | 0.007692307692307693 | 0.01562881562881563 | 3 |
| src/test/java/org/apache/commons/csv/CSVRecordTest.java:CSVRecordTest | False | 5 | 5 | -3.9596407414142645 | 8.892293930053711 | 3 | 0.007692307692307693 | 0.007936507936507936 | 0.01562881562881563 | 4 |
| src/main/java/org/apache/commons/csv/CSVFormat.java:CSVFormat | False | 4 | 4 | -2.9306061577550486 | 7.753166198730469 | 6 | 0.0078125 | 0.007575757575757576 | 0.015388257575757576 | 5 |
| src/test/java/org/apache/commons/csv/CSVParserTest.java:CSVParserTest | False | 7 | 6 | -4.93882767833791 | 8.378464698791504 | 4 | 0.007575757575757576 | 0.0078125 | 0.015388257575757576 | 6 |
| src/test/java/org/apache/commons/csv/CSVPrinterTest.java:CSVPrinterTest | False | 10 | 7 | -4.94577944725271 | 6.845587730407715 | 10 | 0.007462686567164179 | 0.007142857142857143 | 0.014605543710021322 | 7 |
| src/main/java/org/apache/commons/csv/CSVPrinter.java:CSVPrinter | False | 8 | 10 | -5.4285132949109975 | 7.739755630493164 | 7 | 0.007142857142857143 | 0.007462686567164179 | 0.014605543710021322 | 8 |
| src/main/java/org/apache/commons/csv/CSVParser.java:CSVParser.Builder | False | 6 | 8 | -5.080242777099244 | 7.085381031036377 | 9 | 0.007352941176470588 | 0.007246376811594203 | 0.01459931798806479 | 9 |
| src/test/java/org/apache/commons/csv/PerformanceTest.java:PerformanceTest | False | 9 | 9 | -5.224878673321145 | 7.113065719604492 | 8 | 0.007246376811594203 | 0.007352941176470588 | 0.01459931798806479 | 10 |
