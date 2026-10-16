# vp-mf-095: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> ¿Qué archivo contiene la entrada de consola que usa el código del resultado como salida del proceso y otra entrada que recibe explícitamente los flujos de salida y error?

Pieza elegida: `platform-tests/src/processStarter/java/org/junit/platform/tests/process/OutputFiles.java:`.
Aceptable en top10: no; esta etapa no le calculó un score.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

[Explicación del bosque previo: cases](../cases/vp-mf-095.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| platform-tests/src/processStarter/java/org/junit/platform/tests/process/OutputFiles.java: | False | 7 | 1 | 1.6221361077953755 | 7.149786949157715 | 1 | 0.00819672131147541 | 0.00819672131147541 | 0.01639344262295082 | 1 |
| platform-tests/src/processStarter/java/org/junit/platform/tests/process/WatchedProcess.java: | False | 2 | 3 | 0.9983737078547017 | 6.143622398376465 | 4 | 0.007936507936507936 | 0.0078125 | 0.015749007936507936 | 2 |
| junit-platform-console/src/main/java/org/junit/platform/console/options/TestConsoleOutputOptions.java: | False | 5 | 2 | 1.433869168606189 | 5.036701202392578 | 9 | 0.008064516129032258 | 0.007246376811594203 | 0.015310892940626462 | 3 |
| platform-tests/src/test/java/org/junit/platform/console/ConsoleLauncherIntegrationTests.java: | False | 6 | 6 | -0.507141641038773 | 5.598888874053955 | 5 | 0.007575757575757576 | 0.007692307692307693 | 0.015268065268065269 | 4 |
| junit-platform-launcher/src/main/java/org/junit/platform/launcher/core/StreamInterceptingTestExecutionListener.java: | False | 10 | 10 | -2.3421543964543643 | 6.647464752197266 | 2 | 0.007142857142857143 | 0.008064516129032258 | 0.0152073732718894 | 5 |
| platform-tooling-support-tests/src/test/java/platform/tooling/support/tests/KotlinCoroutinesTests.java: | False | 9 | 9 | -1.5694581427643284 | 6.191625595092773 | 3 | 0.007246376811594203 | 0.007936507936507936 | 0.01518288474810214 | 6 |
| platform-tests/src/processStarter/java/org/junit/platform/tests/process/ProcessStarter.java: | False | 1 | 5 | 0.45229112792964027 | 5.524576663970947 | 7 | 0.007692307692307693 | 0.007462686567164179 | 0.015154994259471873 | 7 |
| platform-tests/src/test/java/org/junit/platform/console/ConsoleDetailsTests.java: | False | 8 | 7 | -0.9675062904648262 | 5.578168869018555 | 6 | 0.007462686567164179 | 0.007575757575757576 | 0.015038444142921756 | 8 |
| junit-platform-console/src/main/java/org/junit/platform/console/options/TestConsoleOutputOptionsMixin.java: | False | 3 | 4 | 0.7702002616882397 | 4.810442924499512 | 10 | 0.0078125 | 0.007142857142857143 | 0.014955357142857142 | 9 |
| platform-tooling-support-tests/src/test/java/platform/tooling/support/tests/StandaloneTests.java: | False | 4 | 8 | -1.3717652518280314 | 5.30753231048584 | 8 | 0.007352941176470588 | 0.007352941176470588 | 0.014705882352941176 | 10 |
