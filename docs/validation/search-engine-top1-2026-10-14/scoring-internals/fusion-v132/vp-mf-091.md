# vp-mf-091: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> Which physical Java source file declares temporary-directory injection for Path or File fields and parameters and documents that a local factory overrides a global factory?

Pieza elegida: `junit-jupiter-api/src/main/java/org/junit/jupiter/api/io/TempDirFactory.java:`.
Aceptable en top10: sí, puesto final2.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.00025201612903225784. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-091.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-091.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/io/TempDirFactory.java: | False | 2 | 1 | 4.389921974359778 | 8.42115592956543 | 2 | 0.00819672131147541 | 0.008064516129032258 | 0.01626123744050767 | 1 |
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/io/TempDir.java: | True | 5 | 4 | -0.4884647416224239 | 10.40423583984375 | 1 | 0.0078125 | 0.00819672131147541 | 0.016009221311475412 | 2 |
| junit-jupiter-engine/src/main/java/org/junit/jupiter/engine/extension/TempDirectory.java: | False | 1 | 2 | 1.3425414718823414 | 8.098845481872559 | 4 | 0.008064516129032258 | 0.0078125 | 0.015877016129032258 | 3 |
| junit-jupiter-engine/src/main/java/org/junit/jupiter/engine/config/DefaultJupiterConfiguration.java: | False | 3 | 3 | 1.3312271202356671 | 6.841731071472168 | 8 | 0.007936507936507936 | 0.007352941176470588 | 0.015289449112978524 | 4 |
| platform-tooling-support-tests/src/test/java/platform/tooling/support/tests/LocalMavenRepo.java: | False | 7 | 6 | -2.1462710499983273 | 6.922265529632568 | 6 | 0.007575757575757576 | 0.007575757575757576 | 0.015151515151515152 | 5 |
| documentation/src/test/java/example/TempDirectoryDemo.java: | False | 10 | 10 | -3.9101663708908796 | 8.360942840576172 | 3 | 0.007142857142857143 | 0.007936507936507936 | 0.015079365079365078 | 6 |
| jupiter-tests/src/test/java/org/junit/jupiter/engine/extension/TempDirectoryTests.java: | False | 6 | 8 | -3.447665125015522 | 6.941179275512695 | 5 | 0.007352941176470588 | 0.007692307692307693 | 0.015045248868778281 | 7 |
| jupiter-tests/src/test/java/org/junit/jupiter/engine/extension/CloseablePathTests.java: | False | 8 | 7 | -3.210808130526751 | 6.895560264587402 | 7 | 0.007462686567164179 | 0.007462686567164179 | 0.014925373134328358 | 8 |
| junit-platform-engine/src/main/java/org/junit/platform/engine/support/descriptor/UriSource.java: | False | 4 | 5 | -1.2665934389292883 | 5.996925354003906 | 10 | 0.007692307692307693 | 0.007142857142857143 | 0.014835164835164835 | 9 |
| junit-jupiter-engine/src/main/java/org/junit/jupiter/engine/config/CachingJupiterConfiguration.java: | False | 9 | 9 | -3.8207591142056008 | 6.611224174499512 | 9 | 0.007246376811594203 | 0.007246376811594203 | 0.014492753623188406 | 10 |
