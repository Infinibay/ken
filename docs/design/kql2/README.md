# KQL 2: definición del lenguaje

**Estado: propuesta normativa de diseño, revisión 0.1, 14 de septiembre de 2026.**
Existe una implementación experimental parcial: consultar el
[estado y uso ejecutable](implementation-status.md). La especificación completa
sigue siendo el objetivo; los ejemplos que usan capacidades pendientes no son
ejecutables aún. El catálogo activo de 33 TOML usa KQL 2 sobre el [grafo semántico](graph-queries.md).
KenQL 1 sigue disponible para consultas guardadas e identificadores históricos.

El backend optativo [`exploration`](exploration-engine.md) compila consultas
sintácticas a recorridos sobre AST persistidos en FlatBuffers. Incluye ejemplos
ejecutables y mediciones; el catálogo semántico conserva su backend actual.

## Decisión

Rediseñar el lenguaje de consultas desde su semántica. Conservar los extractores,
el grafo, los datos de validación y las consultas anteriores como referencias de
migración, sin obligar al nuevo lenguaje a reproducir sus limitaciones.

KQL 2 describe conjuntos de coincidencias sobre un programa. No genera ni ejecuta
ese programa. Una búsqueda de arquitectura, un patrón GoF y una regla de bugs usan
el mismo lenguaje. La clasificación y severidad son metadatos del catálogo.

El diseño combina tres formas que compilan al mismo modelo:

1. **Predicados y consultas tipadas:** relaciones, composición, recursión,
   cuantificación, cálculos y agregaciones.
2. **Patrones estructurales anidados:** tipos, campos, funciones, firmas y módulos.
3. **Patrones de comportamiento:** instrucciones relevantes, flujo, intervalos
   protegidos, iteraciones y estados de protocolos.

Se adopta minúscula para palabras reservadas. `pattern` define un concepto;
`class $subject` captura una declaración del programa. Se descarta la repetición
`define CLASS`, `define FIELDS`, `define BODY`: no añade una distinción semántica.
Los grupos `fields` y `parameters` se conservan para restricciones de conjunto.

## Lectura y autoridad

| Documento | Qué fija |
|---|---|
| [Estado de implementación](implementation-status.md) | Capacidades ejecutables, pendientes y acceso experimental |
| [Engine de exploración](exploration-engine.md) | Backend FlatBuffers, compilación de recorridos, capacidades, CLI y mediciones |
| [Consultas sobre el grafo](graph-queries.md) | Perfil ejecutable del catálogo, relaciones, contexto, recorridos y cardinalidad |
| [AST común y contextos](common-ast.md) | Arquitectura central, almacenamiento parcial, ámbitos y disponibilidad por anidación |
| [Lenguaje](language.md) | Escritura, tipos, ámbitos, selectores, firmas, predicados y consultas |
| [Valores y usos](value-usages.md) | Capturas internas, consumidores por ocurrencia, filtros e inventarios abiertos |
| [Modelo del programa](code-model.md) | Variables, familias/traits, capacidades por punto, expresiones, métodos y normalización de control |
| [Comportamiento](behavior.md) | BODY, intervalos, efectos, caminos, iteración y concurrencia |
| [Contrato IR y evaluación](ir-and-evaluation.md) | Evidencia requerida, incertidumbre, recursión, planificación y caché |
| [Bibliotecas y ejemplos](examples.md) | Composición, flujo configurable, algoritmos y variantes nativas |
| [Catálogo y migración](migration.md) | Archivos, los 23 GoF, patrones modernos y etapas de implementación futura |
| [Conformidad](conformance.md) | Casos positivos, negativos, desconocidos y errores que deben probarse |
| [Gramática](grammar.ebnf) | Estructura sintáctica del núcleo; las restricciones contextuales están en las secciones anteriores |
| [Plan de implementación](implementation-plan.md) | Etapas, dependencias y aceptación para parser, store, optimizador, búsqueda, caché e índices |
| [Almacenamiento y migraciones](storage-plan.md) | Tablas tipadas, snapshots, publicación, up/down y recuperación |
| [Parser y ejecución](query-engine-plan.md) | Compilación, operadores, planificación, BODY y evaluación diferencial |
| [Caché, índices y performance](cache-index-plan.md) | Presupuesto compartido de 500 MB, invalidación, 14 accesos y 10 familias de benchmarks |
| [Auditoría de rendimiento](performance-audit-2026-09-20.md) | Siete diagramas del recorrido real y mediciones de parser, planificación, joins y BODY |
| [Objetivo: 100 archivos en menos de 5 s](latency-target-5s.md) | Índice preparado, optimizaciones incorporadas y gate de aceptación todavía pendiente |
| [Segunda ronda de optimización](join-optimization-2026-09-20.md) | Joins por propiedades, dependencias correlacionadas, lecturas locales y mediciones A/B |
| [Evidencia diferida](late-materialization-2026-09-21.md) | Separación entre búsqueda y construcción de pruebas, atributos proyectados y cierre del inventario |
| [Interfaces del runtime](runtime-interfaces-2026-09-21.md) | Modelo independiente, contratos de operadores y almacenamiento, perfilado y proyección de resultados |
| [Accesos selectivos](selective-access-2026-09-21.md) | Selección por cardinalidad, índices de operaciones y límites de la proyección de BODY |
| [Requisitos previos de BODY](body-prerequisites-2026-09-21.md) | Inventarios compartidos con el evaluador, poda antes de joins y coste de explorar dominios |

Los capítulos de lenguaje, modelo, comportamiento y evaluación definen el contrato objetivo. La gramática no
autoriza por sí sola combinaciones prohibidas por tipos o ámbitos. Los ejemplos
de fragmentos se identifican como tales. Una implementación parcial debe rechazar
capacidades no disponibles; no puede aceptar el texto y omitir obligaciones.

La [guía operativa de KQL 1](../../structural-queries.md) sigue siendo la autoridad
sobre la sintaxis KQL 1; el perfil del catálogo actual se documenta en [consultas sobre el grafo](graph-queries.md). El [diseño anterior](../structural/query-language.md)
queda como antecedente para sintaxis; sus ejemplos no definen KQL 2. El
[IR operativo](../../structural-ir.md) y el [núcleo de instrucciones propuesto](../structural/instruction-ir.md)
aportan contratos útiles, con las carencias enumeradas en esta especificación.

## Decisiones que no deben reinterpretarse al implementar

| ID | Decisión |
|---|---|
| D01 | Una captura es una identidad del IR, nunca una coincidencia por nombre implícita. |
| D02 | Binding, valor, objeto, lugar de memoria, tipo y operación son tipos diferentes. |
| D03 | El orden estructural no importa; BODY tiene orden y contexto de control. |
| D04 | BODY permite instrucciones intermedias por defecto; sus efectos se restringen explícitamente. |
| D05 | `gap until next` termina antes de la siguiente instrucción anclable del mismo bloque. |
| D06 | Las restricciones de intervalo usan todos los caminos conectores por defecto. No acreditan terminación. |
| D07 | No hay negación por ausencia de hechos en un dominio incompleto. |
| D08 | `any` de tipos fuente no significa información desconocida ni comodín de búsqueda. |
| D09 | Las bibliotecas de patrones publican roles y fragmentos correlacionados, con higiene. |
| D10 | Los ciclos de predicados positivos tienen punto fijo; negación y agregaciones se estratifican. |
| D11 | Map, filter, loops y generadores comparten contratos parciales, no equivalencia automática. |
| D12 | Cuerpo léxico, ejecución posible, consumo y concurrencia son dimensiones explícitas. |
| D13 | Un timeout produce análisis incompleto, nunca un negativo confirmado. |
| D14 | Los modelos semánticos pertenecen a bibliotecas versionadas; no se infieren por el nombre de una API. |
| D15 | No se promete decidir equivalencia de programas, intención GoF o ausencia universal de bugs. |
| D16 | `adjacent;` prohíbe instrucciones intermedias entre dos anclas; el default permite intercalación. |

## Alcance del reinicio

Se reemplaza el diseño de KQL, no se elimina el trabajo anterior. Primero se
implementará en paralelo como `kql/2`, con selección explícita por archivo.
No habrá conversión silenciosa de semántica ni reinterpretación de TOML actuales.
Los pasos, criterios de salida y trabajo pendiente están en [migración](migration.md).

La implementación posterior se registra por separado en el estado enlazado. No
cierra las correcciones, validaciones o benchmarks pendientes de IR 1.77.
