# Contratos del catálogo con IR 1.47

Auditoría de los **33 TOML activos GoF y modernos**, incluyendo consultas raíz,
variantes ejecutables, operaciones públicas, dependencias y proyección del IR.
No incluye como objetivos las reglas de bugs construidas en Python ni las queries
históricas del namespace `legacy.gof`.

Resultado reproducible: **262 tests pasan**, sin xfail, en 1,65 s de pytest. Ese
tiempo corresponde a esta matriz controlada; no es un benchmark de repositorios.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
```

[Test de auditoría](../../../tests/structural/test_catalog_ir_contracts.py).

## Inventario del snapshot auditado

| Categoría | Raíces TOML | Variantes ready | Variantes design | Operaciones ready |
| --- | ---: | ---: | ---: | ---: |
| GoF | 23 | 44 | 33 | 12 |
| Modernos | 10 | 12 | 1 | 3 |
| Total | 33 | 56 | 34 | 15 |

Hay **104 definiciones ejecutables**: 33 raíces + 56 variantes + 15 operaciones.
El registro expone 194 nombres al incluir prefijos GoF y nombres históricos; no
son 194 algoritmos distintos. Las variantes `design` son metadata visible que no
se registra como query disponible.

Las tres raíces modernas sin tabla `variants` (`adapted-continuation-wrapper`,
`continuation-wrapper`, `read-through-cache`) contienen consultas ejecutables.
No tener variantes no significa tener una implementación vacía. A la inversa,
una raíz GoF ejecutable no significa que estén implementadas todas sus formas por
lenguaje: quedan 33 variantes GoF declaradas como diseño.

## Qué se comprobó

1. **Todos los TOML:** ID, query raíz no vacía, exports, unicidad de IDs y estados
   de variantes/operaciones. Lo leído del archivo coincide con lo cargado por el
   registro; ningún `ready` carece de query y ningún `design` queda activado.
2. **Las 104 definiciones activas:** validación del motor y ejecución sobre un
   grafo inerte no vacío. No producen matches vacíos de evidencia por mera
   existencia de una clase sin colaboración.
3. **Dependencias y ABI de roles:** 76 referencias directas de named queries,
   exports compatibles, ausencia de ciclos y de roles positivamente no ligados.
   Las queries activas no dependen de `legacy.gof`.
4. **Relaciones/selectores:** 121 nombres de relación usados por las consultas y
   18 atributos de selector aceptados por el parser/motor del snapshot. Se validan
   incluso cuando el primer join no tiene filas, para no ocultar errores en una
   rama o dependencia no alcanzada durante evaluación.
5. **Fuentes reales de los fixtures:** 79 casos positivos: 23 GoF × Python/Java/TS
   y una fuente Python por cada raíz moderna. Cada caso ejecuta raíz, variantes
   y operaciones de su familia; no sólo parsea el texto de la query.
6. **Round trips JSON:** fuente enlazada → serialización/restauración → querygraph,
   y querygraph → serialización/restauración. Matches, bindings, estado, unknown y
   evidencia se conservan; se excluyen tiempos y contadores internos del motor.
7. **Raíces GoF:** el grafo de dependencias alcanza todas sus variantes ready y
   ninguna design. En los fixtures, la raíz corta y `gof.<id>` tienen los mismos
   bindings. Esto protege contra desalinear el TOML raíz y la unión canónica.
8. **Las 15 operaciones públicas:** todas tienen al menos una integración positiva.
   Las seis promociones nuevas se comparan además con sus queries originales de
   los ejercicios: 34 casos (17 positivos/17 negativos) conservan bindings,
   statuses y unknown. No se exige igualdad de wrappers de evidencia distintos.

Las operaciones promovidas comparadas son `factory-method.client_flow`,
`builder.directed_state`, `bridge.returned_primitive`, `strategy.consumed_policy`,
`template-method.dependent_steps` y `singleton.observed_lazy_use`. El positivo de
uso Singleton se valida en Java/TS: la composición classmethod Python sigue siendo
un gap documentado en su ejercicio.

## Alcance de la cobertura positiva

La matriz raíz activa **33 de las 56 variantes ready**. Las otras 23 se ejecutan,
validan y atraviesan roundtrip en esta matriz, pero no encuentran un positivo en
esos 79 ejemplos base. Esto **no significa que carezcan de tests**: muchas tienen
matrices específicas, y las operaciones comparadas agregan ejemplos de varias.
No sumar esas ejecuciones sin match como true negatives ni como prueba semántica
positiva de la variante.

Variantes sin positivo en la matriz raíz base:

- GoF: `bridge#refined-composition`, `builder#director`, `builder#stored-product`,
  `command#retained-contract`, `command#stored-closure`, `command#retained-object`,
  `command#queued-object`, `composite#recursive-nominal`,
  `iterator#external-cursor`, `iterator#generator`, `iterator#delegated-cursor`,
  `memento#accessor-snapshot`, `observer#map-key-registry`,
  `observer#snapshot-registry`, `prototype#field-copy`, `prototype#derived-clone`,
  `singleton#eager-shared`, `state#context-transition`, `strategy#strategy-callable`.
- Modernas: `architecture.cache-aside#java-optional`,
  `architecture.dependency-injection#callable-input`,
  `architecture.dispatch-table#adapted`, `resilience.exception-retry#handler-fallthrough`.

La variante moderna opt-in `architecture.dependency-injection#retained-object`
sí tiene positivo en el fixture base; no se la agrega automáticamente a la raíz.
A diferencia del namespace canónico GoF, las raíces modernas conservan la selección
explícita de variantes de su TOML.

## Placeholders y obligaciones no ejecutables

No se encontraron queries raíz/ready vacías o “por implementar”. Sí hay **30
variantes ready con `missing_capability = "unknown"`**. Eso es metadata residual;
no impide ejecutar sus consultas y tampoco demuestra que estén completos sus
requisitos semánticos. Las listas `requires` y los textos `graph_requirements`
no se convierten automáticamente en restricciones del motor.

Cambio recomendado: separar en el esquema metadata de **contrato deseado**,
**garantías realmente exigidas por la query** y **limitaciones conocidas**. Un
`graph_requirements` que dice “combina resultados” mientras la query sólo pide
una llamada recursiva no debe presentarse como cobertura implementada.

La nueva capa de instrucciones IR (`choose`, `short_circuit`, `iterate`, memoria,
valores, efectos) no sustituyó por sí sola el matcher. Este catálogo se ejecuta
contra el **grafo de consultas derivado de la fuente**. Los tests comprueban esa
interfaz IR 1.47; no prueban que todas las búsquedas usen directamente los nuevos
opcodes o expresen cualquier variante de un algoritmo.

## Riesgos semánticos concretos pendientes

| Consulta / familia | Evidencia actual y cambio necesario |
| --- | --- |
| `state#state-object` / `state#context-transition` | `WRITES` y `ASSIGNED_FROM`, o una captura en constructor, no describen necesariamente el estado/contexto activo al dispatch. Se necesitan valores actuales y efectos entre métodos. |
| `prototype#explicit-copy` | Pasar un campo al constructor no prueba que se conserve. Componer transferencias/resúmenes de copia, sin imponer copia profunda o una única forma de constructor. |
| `interpreter#expression-objects` | Un hijo recibe contexto, pero no se verifica el consumo de resultados ni todos los operandos. Separar firma recursiva y contrato específico de evaluación. |
| `flyweight#explicit-interning` | Pool, binding de clave y construcción están correlacionados; faltan valor temporal de clave, miss-only y contrato de estado intrínseco/extrínseco. |
| `singleton.lazy_instance` | Adyacencia CFG rechaza aritmética independiente. Reemplazarla por secuencias con preservación de estado, no por caminos arbitrarios que admitan resets. |
| `architecture.dependency-injection#object-assignment` | La raíz conserva una firma más amplia basada en asignaciones. El refinamiento `retained-object` es opt-in; no atribuir a la raíz automáticamente sus garantías. |
| Wrappers y variantes cache/Optional | Argumentos, retornos y ownership léxico no prueban exactamente una llamada, identidad de API o estabilidad temporal de todo el heap. Necesitan modelos y contratos de uso adicionales. |

`VALUE` **no es una relación obsoleta**: `ARGUMENT → VALUE` sigue siendo parte
normal de la proyección del grafo. La pregunta es si ese valor representa el
origen requerido en ese punto y se conserva la identidad de la llamada. Tampoco
borrar globalmente `WRITES` o `ASSIGNED_FROM` es una migración correcta: sirven para
firmas amplias, pero deben complementarse para afirmar orden o valor final.

No se detectaron exports sin binding positivo ni dependencias con roles inválidos.
Eso es una propiedad sintáctica/de interfaz: todavía puede haber evidencia
**semánticamente mal correlacionada** entre invocaciones, momentos o propietarios.
Los ejercicios por patrón y sus xfail explícitos son el lugar donde se documentan
esos contraejemplos; pasar esta auditoría no los convierte en aciertos.

## Reproducibilidad y siguientes pasos

El test es dinámico sobre todos los TOML cargados y exige un positivo para cada
operación pública nueva. Si se cambia el catálogo durante la ejecución, comprueba
que archivo y registro coincidan; volver a ejecutar tras congelar esos cambios.
El digest del catálogo y la lista de archivos auditados se consignan abajo.

No se modificó ningún TOML ni el motor desde esta auditoría. Las correcciones de
reglas y las métricas de corpus externo pertenecen a sus revisiones específicas;
este resultado no reemplaza benchmarks ni una matriz de precisión/recall humana.

SHA-256 agregado de paths y contenido de los 33 TOML: `be8809f4a1bc71251ad0d9ce91f14dee4b27f9e29196a3250e23c0db76e93cfb`.

| Raíz | Ready | Design | Operaciones |
| --- | ---: | ---: | ---: |
| [abstract-factory](../../../src/ken/structural/patterns/abstract-factory.toml) | 1 | 2 | 0 |
| [adapter](../../../src/ken/structural/patterns/adapter.toml) | 1 | 2 | 0 |
| [bridge](../../../src/ken/structural/patterns/bridge.toml) | 2 | 1 | 1 |
| [builder](../../../src/ken/structural/patterns/builder.toml) | 3 | 2 | 1 |
| [chain-of-responsibility](../../../src/ken/structural/patterns/chain-of-responsibility.toml) | 1 | 1 | 0 |
| [command](../../../src/ken/structural/patterns/command.toml) | 5 | 1 | 1 |
| [composite](../../../src/ken/structural/patterns/composite.toml) | 2 | 2 | 0 |
| [decorator](../../../src/ken/structural/patterns/decorator.toml) | 1 | 1 | 0 |
| [facade](../../../src/ken/structural/patterns/facade.toml) | 1 | 1 | 0 |
| [factory-method](../../../src/ken/structural/patterns/factory-method.toml) | 1 | 1 | 1 |
| [flyweight](../../../src/ken/structural/patterns/flyweight.toml) | 1 | 1 | 0 |
| [interpreter](../../../src/ken/structural/patterns/interpreter.toml) | 1 | 1 | 0 |
| [iterator](../../../src/ken/structural/patterns/iterator.toml) | 6 | 2 | 1 |
| [mediator](../../../src/ken/structural/patterns/mediator.toml) | 1 | 1 | 0 |
| [memento](../../../src/ken/structural/patterns/memento.toml) | 2 | 1 | 0 |
| [observer](../../../src/ken/structural/patterns/observer.toml) | 3 | 2 | 0 |
| [prototype](../../../src/ken/structural/patterns/prototype.toml) | 3 | 1 | 1 |
| [proxy](../../../src/ken/structural/patterns/proxy.toml) | 1 | 2 | 0 |
| [singleton](../../../src/ken/structural/patterns/singleton.toml) | 2 | 2 | 3 |
| [state](../../../src/ken/structural/patterns/state.toml) | 2 | 1 | 0 |
| [strategy](../../../src/ken/structural/patterns/strategy.toml) | 2 | 1 | 2 |
| [template-method](../../../src/ken/structural/patterns/template-method.toml) | 1 | 2 | 1 |
| [visitor](../../../src/ken/structural/patterns/visitor.toml) | 1 | 2 | 0 |
| [architecture.adapted-continuation-wrapper](../../../src/ken/structural/modern_patterns/adapted-continuation-wrapper.toml) | 0 | 0 | 0 |
| [architecture.batch-work-queue](../../../src/ken/structural/modern_patterns/batch-work-queue.toml) | 1 | 0 | 1 |
| [architecture.cache-aside](../../../src/ken/structural/modern_patterns/cache-aside.toml) | 2 | 0 | 0 |
| [architecture.continuation-wrapper](../../../src/ken/structural/modern_patterns/continuation-wrapper.toml) | 0 | 0 | 0 |
| [architecture.dependency-injection](../../../src/ken/structural/modern_patterns/dependency-injection.toml) | 3 | 0 | 0 |
| [architecture.dispatch-table](../../../src/ken/structural/modern_patterns/dispatch-table.toml) | 2 | 0 | 0 |
| [resilience.exception-retry](../../../src/ken/structural/modern_patterns/exception-retry.toml) | 2 | 0 | 0 |
| [architecture.read-through-cache](../../../src/ken/structural/modern_patterns/read-through-cache.toml) | 0 | 0 | 1 |
| [architecture.subclass-factory](../../../src/ken/structural/modern_patterns/subclass-factory.toml) | 1 | 0 | 0 |
| [persistence.unit-of-work](../../../src/ken/structural/modern_patterns/unit-of-work.toml) | 1 | 1 | 1 |
