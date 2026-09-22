# Consultas KQL 2 sobre el grafo semántico

Estado ejecutable, 14 de septiembre de 2026. Este perfil permite consultar los
hechos semánticos del IR 1.77. Los 23 GoF y 10 patrones modernos del catálogo
utilizan este perfil. No convierte una firma estructural en prueba de intención.

## Relaciones, capturas y contexto

```kql2
language "kql/2";
module examples.delegation;

pattern delegates(out GraphTerm $unit, out GraphTerm $dependency,
                  out GraphTerm $operation) {
    edge HAS_FIELD($unit, $dependency);
    edge HAS_METHOD($unit, $operation);
    edge HAS_CALL($operation, $call) { execution: "possible"; };
    edge RECEIVER($call, $dependency);
}
query results {
    use delegates(unit: $unit, dependency: $field, operation: $method);
    select $unit, $field, $method;
}
```

`edge RELATION(subject, object)` es un join sobre una relación del IR, no una
llamada al código fuente. Sus extremos pueden ser capturas, literales, `_` o una
lista finita de literales. Las capturas conservan identidad entre cláusulas.
`GraphTerm` es un término del grafo: puede identificar una declaración, operación,
valor o literal. No equivale al tipo fuente `any` ni borra la distinción entre
binding, valor y objeto; esa distinción la establece la relación consultada.

```kql2
language "kql/2";
module examples.parameters;
query results {
    edge ENTITY($parameter, "PARAMETER") {
        receiver: false;
        position: 0;
        name: /^filter/i;
        language: ["python", "typescript"];
    };
    select $parameter;
}
```

Los filtros entre llaves pertenecen al **hecho**. Se aplican juntos al mismo
registro, conservando su contexto y evidencia. Admiten literales, listas y regex
regulares; no enlazan capturas. Un atributo ausente no satisface un filtro.
`false` y `0` son valores válidos. `"a|b"` es un literal; usar `["a", "b"]`
para alternativas. El perfil actual rechaza listas cuyos elementos contienen `|`;
se pueden expresar mediante `either` con literales exactos.

El compilador comprueba los nombres de relaciones contra el vocabulario del IR.
Los atributos contextuales pueden variar por relación y frontend; sus contratos
están en [la referencia IR](../../structural-ir.md). No todos están tipados aún
por un schema estático de atributos, por lo que un nombre de atributo erróneo
puede producir cero coincidencias. Escribir tests positivos para cada consulta.

## Alternativas y composición

```kql2
language "kql/2";
module examples.produced;
pattern produced(out GraphTerm $factory, out GraphTerm $product) {
    either {
        edge RETURNS_NEW($factory, $product);
    } or {
        edge RETURNS_NEW_SELF($factory, $product);
    }
}
query results {
    use produced(factory: $factory, product: $product);
    select $factory, $product;
}
```

Cada llamada elige sus alternativas independientemente. Un rol que sale de una
alternativa debe quedar ligado en todas sus ramas. Los roles privados de un
patrón no se mezclan con los del llamador. Los parámetros `in GraphTerm` exigen
una captura ligada antes de `use`; los `out GraphTerm` también pueden recibirse
ligados, actuando como restricciones correlacionadas. Se permiten omisiones de
outputs no usados. Las dependencias recursivas entre patrones se rechazan; la
recursión de predicados del otro perfil conserva su motor de punto fijo.

`bind $public = $existing;` crea un alias de una captura ligada, en el nivel
superior del patrón/query. Debe ser un nombre nuevo. El compilador elimina el
alias y conecta sus restricciones directamente al rol original, incluso si el
llamador liga primero el alias. No es una asignación en el programa analizado.

Las bibliotecas `ken.catalog.*` se cargan desde los TOML empaquetados. Por ejemplo:

```kql2
language "kql/2";
module examples.builders;
import ken.catalog.builder;
query results {
    use ken.catalog.builder.detect(builder: $builder);
    select $builder;
}
```

Los contenidos exactos de las bibliotecas participan en la invalidación de la
caché. Las consultas de módulos importados no se ejecutan automáticamente.

## Recorridos y conteos

```kql2
language "kql/2";
module examples.flow;
query results {
    edge HAS_OPERATION($owner, $entry);
    walk CFG_NEXT($entry, $exit) { min: 1; max: 6; } as $path;
    select $owner, $entry, $exit, $path;
}
```

Los límites son inclusivos y satisfacen `0 <= min <= max <= 32`. Un recorrido de
longitud cero relaciona un nodo consigo mismo. Se conservan estados por
profundidad y modalidad para no perder ciclos que satisfagan el límite inferior.
Se devuelve un testigo por extremos/modalidad, no todos los caminos. `$path`
contiene una cadena JSON con los IDs del testigo. Encontrar un camino **no prueba**
una propiedad sobre todos los caminos ni reemplaza `preserve`.

```kql2
language "kql/2";
module examples.multiple_methods;
query results {
    edge ENTITY($unit, "CLASS");
    tally distinct $method >= 2 {
        edge HAS_METHOD($unit, $method);
    };
    select $unit;
}
```

`tally distinct` es una restricción existencial de cardinalidad, no una colección
materializada que se exporta. Correlaciona roles exteriores y mantiene locales sus
testigos. Los comparadores son `==`, `>=`, `>`, `<=`, `<`. Los límites inferiores
pueden probarse con suficientes testigos ciertos. Igualdad y límites superiores
requieren cobertura cerrada del dominio; de lo contrario conservan
`cardinality:open_world`. La falta de prueba no cuenta como un negativo confirmado.

`where` admite comparaciones entre roles, atributos de entidad/operación o literales,
unidas con `and`. La igualdad de dos roles compara identidades. Un atributo
desconocido conserva `attribute:missing`. Los valores del grafo son términos;
no se convierten implícitamente a números para aritmética de tipos fuente.

## Ejecución y límites

```text
KQL 2 → lexer/parser KQL 2 → resolver de módulos → validación
      → plan de operadores relacionales → planificación de joins → FactIndex
```

El ejecutor de operaciones está en `structural/relational.py`, separado del
parser KenQL 1. Ambos compiladores pueden producir esos operadores. KQL 2 no se
imprime como KenQL 1, no entra en su parser y no genera código Python ejecutable.
Las alternativas, llamadas y conteos se mantienen agrupados; no se distribuye
el producto cartesiano de todas las combinaciones al compilar.

El planificador elige índices por relación/extremos/atributos y reordena los joins
según su selectividad. Respeta las fronteras de composición, conteo y recorridos.
Los planes compartidos del catálogo son inmutables; los resultados intermedios,
presupuestos y memoización por argumentos pertenecen a cada ejecución.

El servicio KQL 2 puede retener en SQLite la vista normalizada completa del grafo
como artefacto JSON con checksum, manifest y versión de implementación. Al
reabrir reconstruye los índices en RAM sin volver a parsear ni enlazar fuentes.
La caché es descartable: deshabilitarla o exceder la cuota no elimina hechos del
análisis. Se reutiliza schema 6; esta migración no necesita destruir tablas.

**Límite actual:** este perfil ejecuta joins sobre `FactIndex` en memoria; no
convierte toda la query en SQL ni garantiza un presupuesto global de RAM/spill.
El otro perfil KQL 2 mantiene sus scans indexados en SQLite. Mezclar selectores
de entidad/BODY y cláusulas `edge` en una misma consulta todavía se rechaza.
También se rechazan aquí `order`, `limit`, agregados calculados, `when` y negación
general; sus implementaciones del perfil estructural no se trasladan de manera
implícita al grafo. El API de ejecución sí tiene presupuestos y cancelación.

`execution: "possible"` pide operaciones no demostradas inalcanzables; no prueba
que se ejecuten. Una arista `modality: "may"` mantiene incertidumbre salvo que
se admita explícitamente esa modalidad. Timeout o agotamiento de presupuesto
producen `complete=false`. Esta extensión conserva las capacidades y carencias
del IR: no completa heap/alias, efectos transitivos o concurrencia por sí sola.


## Contratos del catálogo añadidos en IR 1.78

Cada nombre siguiente es una operación pública (`named_rule`) y un módulo
`ken.catalog.<patrón>.<operación>` con `pattern detect`. Los guiones del nombre
del patrón se escriben como `_` en el módulo.

| Operación | Restricción adicional |
|---|---|
| `adapter.input_conversion` / `adapter.output_conversion` | La computación consume el parámetro recibido / el resultado delegado |
| `visitor.result_forwarding` / `decorator.result_forwarding` | El retorno conserva el resultado de la llamada seleccionada |
| `bridge.injected_returned_primitive` | Se retiene el backend recibido y se retorna su resultado |
| `command.captured_payload` | El argumento de trabajo procede del campo capturado por el constructor |
| `mediator.event_delivery` / `observer.event_delivery` | El argumento entregado procede del evento recibido |
| `interpreter.binary_result` | Dos hijos reciben el mismo contexto y sus resultados contribuyen al retorno |
| `state.event_transition` | Se entrega el evento y no hay reemplazo explícito previo del estado/contexto |
| `flyweight.stable_intrinsic` | El campo intrínseco recibe la clave y tiene una única escritura explícita, en el constructor |
| `proxy.single_guarded_dispatch` | Hay un solo sitio de despacho de la operación y satisface la consulta de guarda |
| `chain-of-responsibility.single_exclusive_handler` | Un retorno directo reenvía y otro procesa localmente; un único sitio de cada despacho |
| `composite.additive_aggregate` | Se suma el resultado del hijo al acumulador retornado, con inventario cerrado de escrituras |
| `iterator.advancing_element` | Se retorna el elemento leído y se incrementa su índice con la expresión `index + 1` |

Son contratos de fuente acotados. Los dos contratos `single_*` no cubren múltiples
sitios equivalentes; el del Iterator no demuestra terminación; el de Composite
no cubre folds arbitrarios; los de copia/flujo no prueban efectos ocultos.
La variante `interpreter#context-free-binary` admite evaluaciones sin parámetro de
contexto cuando el retorno consume los resultados de dos hijos nominales.
Véanse los [hechos y límites del IR](../../structural-ir.md#read-site-contracts-ir-178)
y el [reporte de validación](../../structural-validation/xfail-second-review-2026-09-14/README.md).
