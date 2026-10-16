Se revisaron los 26 fallos recuperables del reranker original en desarrollo nuevo: 169/200 aciertos top1, 31 fallos totales y 5 referencias fuera de top10. El denominador y las referencias expuestas 147 permanecen intactos.

La reconstrucción pasa: 260 card_text originales (los 10 candidatos de las 26 consultas) coinciden con los input_hashes de 158; para los 26 símbolos correctos, también coincide el hash del control de tokens de documento. Se usaron SourceCatalog/build_card/card_text congelados 155, la query expandida capturada y el tokenizer publicado SHA 28c5e078…b86db35 con only_second512. No se usaron los textos mejorados de sintaxis 162 como si fueran los originales.

Ninguna tarjeta correcta se trunca a 512: los pares completos ocupan 123–471 tokens. La información que falta ya había quedado fuera del card o pertenece a otro contexto fuente. Esto descarta truncation512 como explicación mecánica de estos 26 inputs, sin demostrar la causa del ranking.

La lectura semántica separa 13 casos con operaciones centrales visibles, 11 parciales y 2 con operaciones decisivas ausentes aunque quede documentación relacionada. Dentro de los parciales, 2 pierden lógica durante construcción/ownership y 9 necesitan helper/binding/fixture fuera de la tarjeta. Sumados los 2 ausentes, hay 4 pérdidas materiales de proyección previas al tokenizer.

| ID, sufijo symdev-20261016- | Visibilidad | Evidencia / límite principal |
|---|---|---|
|001|VISIBLE|src/_pytest/monkeypatch.py:73–78; NONE|
|002|VISIBLE|src/_pytest/monkeypatch.py:94–100; NONE|
|003|PARTIAL|src/_pytest/monkeypatch.py:104–110; OFF_CARD_LOCAL_HELPER_CONTEXT|
|008|VISIBLE|src/_pytest/monkeypatch.py:314–317; NONE|
|014|PARTIAL|src/_pytest/mark/expression.py:142–149; OFF_CARD_LOCAL_HELPER_CONTEXT|
|015|VISIBLE|src/_pytest/mark/expression.py:152–158; NONE|
|018|PARTIAL|src/_pytest/mark/expression.py:185–189; OFF_CARD_LOCAL_HELPER_CONTEXT|
|025|VISIBLE|src/_pytest/assertion/util.py:85–99; NONE|
|042|PARTIAL|lib/vocabularies/applicator/additionalItems.ts:37–45; LEXICAL_CHILD_EXCLUDED_BEFORE_TOKENIZATION|
|047|PARTIAL|lib/vocabularies/applicator/dependencies.ts:99–107; OFF_CARD_LOCAL_HELPER_CONTEXT|
|053|VISIBLE|lib/vocabularies/dynamic/dynamicRef.ts:32–38; NONE|
|067|PARTIAL|lib/vocabularies/validation/const.ts:20–23; OFF_CARD_BINDING_CONTEXT|
|070|PARTIAL|lib/vocabularies/validation/enum.ts:46–49; OFF_CARD_ENCLOSING_BINDING_CONTEXT|
|093|VISIBLE|junit-platform-commons/src/main/java/org/junit/platform/commons/util/CloseablePath.java:108–110; NONE|
|098|VISIBLE|junit-platform-engine/src/main/java/org/junit/platform/engine/support/hierarchical/LockManager.java:80–86; NONE|
|102|VISIBLE|junit-platform-engine/src/main/java/org/junit/platform/engine/support/hierarchical/SingleLock.java:87–87; NONE|
|109|PARTIAL|junit-jupiter-engine/src/main/java/org/junit/jupiter/engine/execution/ParameterResolutionUtils.java:128–151; OFF_CARD_LOCAL_HELPER_CONTEXT|
|115|PARTIAL|junit-platform-commons/src/main/java/org/junit/platform/commons/support/conversion/FallbackStringToObjectConverter.java:96–100; OFF_CARD_LOCAL_HELPER_CONTEXT|
|134|PARTIAL|tests/test_pylock_select.py:143–159; OFF_CARD_FIXTURE_VALUE|
|140|PARTIAL|tests/test_pylock_select.py:429–435; LEXICAL_CHILD_AND_CARD_WINDOW_SELECTION|
|146|VISIBLE|tests/test_errors.py:103–110; NONE|
|152|VISIBLE|tests/test_listutils.py:66–71; NONE|
|156|VISIBLE|tests/test_listutils.py:213–222; NONE|
|168|ABSENT|tests/test_make.py:1747–1750; LEXICAL_CHILD_EXCLUSION_AND_CARD_WINDOW_SELECTION|
|172|ABSENT|tests/test_make.py:1043–1045; LEXICAL_CHILD_EXCLUSION_AND_CARD_WINDOW_SELECTION|
|196|VISIBLE|src/test/java/org/apache/commons/csv/ExtendedBufferedReaderTest.java:82–88; NONE|

Ejemplos de disponibilidad perdida, sin proponer ajustes por caso: 042 conserva las guardas pero excluye validateItems 48–53; 140 conserva las aserciones pero pierde el callback 418–420 y el contexto parametrizado 392–408; 168 sólo muestra documentación y @attr.define, dejando fuera Attribute/multiplicación 1752–1754 y montaje/aserción 1757–1765; 172 omite definición y aserciones 1048–1055. Son citas fuente físicas verificadas; no anclas nuevas ni cambios a Gold.

Los contextos ausentes se distinguen de una referencia errónea: por ejemplo, 003 llama annotated_getattr pero la comprobación real está en 93–100; 115 invoca la fábrica pero su cache está en computeIfAbsent 103–108; 134 nombra _py312_linux pero su valor 3.12 vive en 41–59. El JSON aporta citas literales de la operación visible y del contexto que no recibió el modelo. No se exige el cuerpo de todo helper indiscriminadamente ni se infiere su comportamiento sólo por nombre.

No se encontró un error definitivo de referencia en estos 26; tampoco se hizo una búsqueda exhaustiva de alternativas por todo el corpus. Las 13 operaciones centrales visibles siguen siendo fallos de ordenamiento: esta revisión de disponibilidad no prueba por qué el modelo los cometió. La muestra está condicionada a fallos expuestos y no certifica generalización, aceptación ni suficiencia de toda respuesta.

No se cargaron pesos/modelos, no hubo sesiones ONNX ni fitting, no se consultó A186 y no se abrió reserva o Gold de aceptación. No se modificó código, productor, etiqueta ni receta fija.

[Informe con citas y hashes](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/reference-card-visibility-v190.json).
