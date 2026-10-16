# vp-mf-092: decisión final de la fusión

Valores de la ejecución completa v132; no se reutilizaron logits históricos.

> ¿Qué archivo Java declara la anotación que habilita una prueba sólo si una variable de entorno coincide con una regex y documenta que queda deshabilitada si la variable no existe?

Pieza elegida: `junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/EnabledIfEnvironmentVariableCondition.java:`.
Aceptable en top10: sí, puesto final4.

prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.

Margen RRF elegido−aceptable: 0.00034981343283582364. Es una diferencia ordinal exacta; los logits no se suman directamente al score.

[Explicación del bosque previo: cases](../cases/vp-mf-092.md).

[Explicación del bosque previo: piece-cases](../piece-cases/vp-mf-092.md).

| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/EnabledIfEnvironmentVariableCondition.java: | False | 1 | 1 | 4.514525335420602 | 10.06300163269043 | 4 | 0.00819672131147541 | 0.0078125 | 0.016009221311475412 | 1 |
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/DisabledIfEnvironmentVariableCondition.java: | False | 2 | 2 | 4.502284606349607 | 10.088517189025879 | 3 | 0.008064516129032258 | 0.007936507936507936 | 0.016001024065540194 | 2 |
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/DisabledIfEnvironmentVariable.java: | False | 5 | 5 | -3.1306816760393543 | 10.40963363647461 | 2 | 0.007692307692307693 | 0.008064516129032258 | 0.01575682382133995 | 3 |
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/EnabledIfEnvironmentVariable.java: | True | 6 | 7 | -3.1825002963306144 | 10.671537399291992 | 1 | 0.007462686567164179 | 0.00819672131147541 | 0.01565940787863959 | 4 |
| jupiter-tests/src/test/java/org/junit/jupiter/api/condition/EnabledIfEnvironmentVariableConditionTests.java: | False | 7 | 6 | -3.138511624676682 | 9.779825210571289 | 5 | 0.007575757575757576 | 0.007692307692307693 | 0.015268065268065269 | 5 |
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/DisabledIfSystemPropertyCondition.java: | False | 3 | 3 | 0.18067270328020604 | 8.787969589233398 | 9 | 0.007936507936507936 | 0.007246376811594203 | 0.01518288474810214 | 6 |
| junit-jupiter-api/src/main/java/org/junit/jupiter/api/condition/EnabledIfSystemPropertyCondition.java: | False | 4 | 4 | -2.8669295707439306 | 9.039113998413086 | 8 | 0.0078125 | 0.007352941176470588 | 0.015165441176470588 | 7 |
| jupiter-tests/src/test/java/org/junit/jupiter/api/condition/EnabledIfEnvironmentVariableIntegrationTests.java: | False | 8 | 9 | -3.7044942613076177 | 9.635452270507812 | 6 | 0.007246376811594203 | 0.007575757575757576 | 0.01482213438735178 | 8 |
| documentation/src/test/java/example/ConditionalTestExecutionDemo.java: | False | 10 | 10 | -4.480082216844015 | 9.556614875793457 | 7 | 0.007142857142857143 | 0.007462686567164179 | 0.014605543710021322 | 9 |
| jupiter-tests/src/templates/resources/test/org/junit/jupiter/api/condition/DisabledOnJreConditionTests.java.jte: | False | 9 | 8 | -3.5100358745775995 | 8.675039291381836 | 10 | 0.007352941176470588 | 0.007142857142857143 | 0.014495798319327732 | 10 |
