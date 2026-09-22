# Corrección del catálogo GoF y moderno — IR 1.77

Se revisaron y modificaron los **33 TOML: 23 GoF y 10 modernos**. Esta revisión
fortalece la correlación entre evidencias, excluye implementación demostrablemente
inalcanzable y conserva variantes nativas. La especificación operativa está en
[IR 1.77](../../structural-ir.md#catalog-precision-contracts-ir-177) y
[KenQL](../../structural-queries.md#evidencia-de-implementación-desde-ir-177).

## Resultados medidos y alcance

| Matriz de 2.312 casos | IR 1.76 | IR 1.77 |
|---|---:|---:|
| TP | 1.358 | 1.399 |
| TN | 860 | 912 |
| FP | 52 | 0 |
| FN | 42 | 1 |

Son **93 discrepancias corregidas: 52 FP y 41 FN**. El único desacuerdo de esta
matriz que continúa es `directed/abstract-factory-object-literals` (TypeScript).
No significa precisión perfecta sobre repositorios arbitrarios ni completar
todos los contratos algorítmicos históricos.

La matriz contiene 412 combinaciones anunciadas de variante/lenguaje, cinco
familias mínimas por combinación (2.060 casos) y 252 casos dirigidos. Hay ocho
lenguajes en ese ámbito. Ruby existe en el frontend, pero estos TOML no anuncian
esa cobertura. Una variante moderna, Unit of Work transaccional, permanece en
`design`: no se cuenta como negativo probado.

* [Cobertura actual por celda](COVERAGE.md), con IDs estables y positivos/negativos.
* [Resultados actuales y hashes](matrix-results.json).
* [Fuentes y ámbito](../../../tests/structural/catalog_matrix/seeds.json).
* [Pendientes y 93 casos resueltos](../../../tests/structural/catalog_matrix/known_failures.json).
* [Auditoría anterior completa](../catalog-adversarial-2026-09-14/README.md),
  conservada como baseline histórico, con contraejemplos y causas por variante.

No se cambiaron negativos legítimos a positivos. Se corrigieron siete seeds
positivos inválidos o demasiado débiles: Bridge Go tenía tipos independientes,
Decorator C++ sólo reenviaba la llamada y cinco Facade componían funciones
identidad locales sin frontera de servicios. Las nuevas fuentes tienen
respectivamente composición explícita, responsabilidad adicional y servicios
distintos. Cambian 28 hashes de los 2.312 casos derivados (el negativo inerte no
cambia). Por eso la comparación no debe describirse como un corpus de bytes
completamente idéntico. También se corrigieron tests históricos que consideraban
inválido un generador asíncrono sin `await` y un alias de base ahora representable.

## Cambios y límites por GoF

Las consultas usan `[execution:possible]` en la evidencia de implementación que
corresponde. Se conserva la sintaxis original para búsquedas de código muerto y
el contrato lexical de generadores vacíos. Las siguientes mejoras se agregan a
ese cambio común; los límites son trabajo pendiente o contratos más fuertes,
no afirmaciones de que cada variante sea incorrecta.

| TOML | Corrección aplicada | Límite relevante / siguiente mejora |
|---|---|---|
| Abstract Factory | Los slots de productos pertenecen al mismo contrato; no mezclar interfaces independientes | FN de objetos literales: faltan miembros de registro → claves → callables. Añadir esas relaciones, familias de productos correlacionadas y contraste con diccionario de utilidades |
| Factory Method | El rol público `factory` identifica la implementación concreta que construye el producto, consistente con sus usos | Retorno/procedencia de clientes y extensiones dinámicas requieren evidencia adicional |
| Builder | La entrada y el estado deben alimentar la construcción devuelta; soporta inicializadores nombrados Go/Rust | Inmutabilidad profunda, escapes y estado temporal entre llamadas no están demostrados |
| Prototype | La copia se devuelve; conserva casts Java/C# como operaciones; C++ exige copia de campos y excluye cuerpos que sólo lanzan | Derive/Clone y APIs de copia siguen teniendo límites de resolución y copia profunda |
| Singleton | Caminos CFG tolerantes a ruido; inventario de escrituras; `updateAndGet` debe devolver el valor anterior presente y crear sólo en ausencia | Un sitio de escritura no garantiza una ejecución; publicación/thread safety y APIs de terceros permanecen incompletos |
| Adapter | Ambos accesos indexados provienen del request, no de arrays constantes | Adaptaciones de entrada/salida y métodos homónimos necesitan contratos específicos de conversión |
| Bridge | Abstracción y refinamiento se conectan por herencia/composición; compartir el nombre `T` deja de ser evidencia | La relación genérica no prueba todas las sustituciones ni retención del implementador inyectado |
| Composite | Slot, contrato y llamada sobre hijos corresponden a la misma operación | Agregación del resultado, propagación de argumentos y rebinding del hijo siguen siendo refinamientos pendientes; tipo de elemento recibido por parámetro no siempre se propaga al campo |
| Decorator | Exige responsabilidad adicional: llamada, macro estándar Rust o transformación binaria del resultado | No toda llamada adicional es una responsabilidad útil; transparencia y proveniencia exacta del resultado requieren un contrato más fuerte |
| Facade | Correlación de flujo y frontera entre tipos de servicio o módulos diferentes | La intención de simplificar una API y servicios no resueltos no se deducen sólo de la forma; un pipeline similar puede compartir estructura |
| Flyweight | Misma clave y pool, condición de ausencia con polaridad, inserción en esa rama y retorno; excluye reemplazo incondicional | Igualdad semántica de claves, aliases, sobrecargas y concurrencia permanecen fuera del modelo |
| Proxy | Resultado del transporte alimenta la decodificación; creación diferida realmente almacenada; guardas con rechazo temprano | La totalidad de caminos sin bypass, identidad de APIs remotas y efectos ocultos no están demostrados |
| Chain of Responsibility | Distingue rechazo/manejo temprano de forwarding y conecta sus caminos | Misma petición, devolución del resultado y exclusividad son operaciones fuertes aún pendientes |
| Command | Ejecución/contexto pertenece a la invocación del elemento de la cola identificada | Estado del receptor después de rebinding, payload capturado y comandos objeto con contexto necesitan variantes/flujo temporal |
| Interpreter | Excluye lecturas y delegaciones inalcanzables | Falta probar combinación de todos los operandos, contexto y procedencia final del resultado |
| Iterator | Async yield no exige await adicional; callback Go detiene cuando yield devuelve false; conserva generadores vacíos válidos | Progreso numérico, agotamiento y procedencia del elemento requieren contratos adicionales |
| Mediator | Receptor y argumento `self` pertenecen a la misma llamada | Instancias distintas del mismo tipo y preservación de payload necesitan roles de instancia |
| Memento | Snapshot devuelto procede del encoder; restauración decodifica el snapshot recibido | Aliases mutables, copia profunda, serialización correcta y persistencia del snapshot no están probados |
| Observer | El payload se pasa en la invocación de la iteración sobre el bucket del evento | Notificaciones sin payload siguen siendo válidas; un contrato de entrega debe explicitarlo |
| State | Excluye mutaciones y delegaciones inalcanzables | Estado activo al despachar, contexto y evento exigen procedencia temporal del heap |
| Strategy | Variante C++ estática une `P::apply` al dueño léxico del parámetro, sin necesitar un campo ficticio | No resuelve todas las instanciaciones/constraints del template ni intención de la política |
| Template Method | Evidencia ejecutable; el descarte Rust ya no invalida los summaries de composición | Orden/propagación de resultados de hooks y todas las sustituciones siguen siendo contratos más fuertes |
| Visitor | Overloads corresponden a elementos de tipos distintos e incluyen el elemento actual | Reasignación previa del visitante y forwarding de resultados requieren análisis adicional; un visitor void es válido |

## Cambios y límites por patrón moderno

| TOML | Corrección aplicada | Límite relevante / siguiente mejora |
|---|---|---|
| Dependency Injection | Un único write explícito al campo en el método inyector y parámetro sin reasignar; conserva suministro condicional y variante de retención más estricta | No prueba orden entre métodos, descriptor/setter ni retención en todos los caminos |
| Dispatch Table | Inventario de escrituras sobre el mismo contenedor/índice rechaza handler sobrescrito | Otras claves pueden ser aliases; registros condicionales repetidos legítimos pueden quedar fuera; no acredita routing HTTP |
| Continuation Wrapper | La continuación capturada no tiene escrituras explícitas | No prueba exactly-once, argumentos, orden ni mutaciones ocultas |
| Adapted Continuation Wrapper | Continuación sin rebinding; rechaza adapter local resuelto cuyo resultado es escalar demostrado | Un adaptador externo, decorado o virtual conserva resultado `unknown`: sigue siendo un candidato, no prueba de callability |
| Batch Work Queue | La iteración conserva el binding de entrada de la colección; rechaza reset/clear previo | No prueba FIFO, aliases, entrega única, finalización o éxito de cada comando |
| Unit of Work | El coordinador no reemplaza/limpia explícitamente el campo leído por los workers antes de delegar | API de persistencia por forma; no prueba transacción, commit/rollback ni integridad del changeset. Variante transaccional sigue en diseño |
| Exception Retry | Un finally con salida explícita no puede prestar un continue que será anulado | `no-explicit-override` no garantiza ausencia de excepciones implícitas, idempotencia, backoff o progreso |
| Subclass Factory | `BASE_INPUT` permite aliases locales únicos y anteriores, conservando relación con el parámetro | Aliases condicionales/clobbers y cambios dinámicos de base quedan fuera; no prueba MRO/compatibilidad |
| Cache-Aside | Caminos CFG de hasta 32 pasos conservan lookup/miss/load/write/return con ruido probado de 20 sentencias | APIs por forma, Optional conserva límites de procedencia; más distancia, aliases, TTL e invalidación requieren más análisis |
| Read-Through Cache | Mismo ajuste de caminos y evidencia de implementación ejecutable | Construcción no prueba propiedad exclusiva; no resuelve TTL, evicción, concurrencia ni pureza |

## Validación del IR y de las expectativas

Los tests nuevos de revisión independiente cubren salidas en ocho lenguajes,
declaraciones/valores por defecto tras return, hoisting JS/TS, descartes Rust con
efectos, destructuring y bindings de loops/with/except, aliases de bases,
calificación de templates, `undefined` con shadowing y resultados escalares bajo
decoradores, dispatch virtual o ejecución dinámica.

La revisión detectó una expansión cartesiana entre cada método y cada campo.
Se reemplazó por pares de llamadas resueltas y campos realmente leídos por sus
targets: en el contraste de 200 campos y 200 métodos, **96.026 → 16.026 hechos**.
El test verifica tamaño determinista, sin umbrales temporales frágiles.

Los snippets se parsean con Tree-sitter; Python además valida sintaxis con
`compile`, sin ejecutar los programas. No equivale a compilar/typecheckear todos
los lenguajes. La matriz comprueba finalización y errores antes de considerar
un desacuerdo conocido; un nuevo FP/FN o un presupuesto agotado falla. Corregir
el único xfail exige retirar su entrada exacta, no cambiar el oráculo.

## Reproducción

```bash
.venv/bin/python -m pytest tests/structural -q --tb=short
PYTHONPATH=. .venv/bin/python -m examples.bench.audit_catalog_matrix \
  --output docs/structural-validation/catalog-corrections-2026-09-14
```

Los resultados finales de la suite y la comparación de rendimiento se registran
en `validation.json` y `performance.json` junto a este reporte. Deben leerse con
sus hashes, alcance y presupuestos; los matches de repositorios sin oráculos
manuales no se contabilizan automáticamente como TP.
