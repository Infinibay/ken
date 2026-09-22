# Catálogo, cobertura y plan de migración

Diseño original 0.1; actualizado con la migración ejecutada del 14 de septiembre. [Índice](README.md).

El [plan técnico](implementation-plan.md) concreta las etapas en tareas con
dependencias y criterios de aceptación. La migración física de tablas, distinta
de migrar el catálogo, se define en [almacenamiento](storage-plan.md).
Los [benchmarks e índices](cache-index-plan.md) se incorporan desde las primeras
etapas; los pasos generales de este capítulo no los postergan hasta el catálogo.

## 1. Qué cambia y qué se conserva

KQL 2 es una versión nueva y explícita. Se conserva `kenql/1` sin reinterpretarlo;
la compatibilidad se ofrece por selección de dialecto. Los 33 TOML activos ya
usan el [perfil de grafo KQL 2](graph-queries.md): 138 consultas compiladas
directamente a operadores relacionales. Los ejemplos de manifiestos y etapas
posteriores de este capítulo siguen siendo propuestas, no estado implementado.
El texto ejecutable actual permanece inline en cada TOML; las variantes sólo
se justifican si representan algoritmos o contratos diferentes.

Cada concepto seguirá visible en su archivo. Propuesta de organización futura:

```text
patterns/
  builder.toml       # identidad, explicación, variantes, exports y capacidades
  builder.kql        # patrones/predicados/queries KQL 2 de ese concepto
  iterator.toml
  iterator.kql
```

Separar texto y metadatos evita escapes de bloques grandes en TOML. Un solo `.kql`
puede contener variantes del mismo concepto y operaciones públicas; bibliotecas
generales van en archivos propios. No generar detectores opacos dentro de Python.
Para distribución pequeña también se permite texto inline en TOML; no ambos
`source` y `query` en la misma entrada. La fuente canónica debe ser única.

Manifiesto futuro ilustrativo, **no el schema del catálogo actual**:

```toml
schema = "ken-pattern/2"
id = "gof.builder"
language = "kql/2"
source = "builder.kql"
entry = "Builder"
exports = ["Builder", "Configure", "Finish"]
status = "design"
tags = ["gof", "creational"]

[[variants]]
id = "mutable-product"
entry = "MutableProductBuilder"
claim = "Configura y entrega el mismo producto con procedencia preservada."
requires = ["value.identity", "effects.interval", "fields.instance"]
```

Rutas relativas al manifiesto; resolución confinada al paquete. Dependencias de
paquetes y versiones de modelos fijadas en lockfile. Un entry inexistente, source
duplicado o firma pública incompatible es error de carga. `status=design` no se
ejecuta ni se cuenta como cobertura. Metadata severidad no cambia semántica.

`entry` de detector debe ser una query sin parámetros o un patrón con sólo
parámetros out, proyectados como roles públicos. Un patrón con entradas pertenece
a exports/operaciones o debe envolverse con una query que las ligue; el loader
no inventa entradas ni genera un producto cartesiano de valores desconocidos.

## 2. Los 23 GoF como prueba del lenguaje

Cada fila requiere variantes, ejemplos positivos/negativos/unknown y un claim
preciso. La tabla no afirma que esos contratos ya estén implementados.

| Patrón | Relaciones/algoritmo que debe poder expresar | Variación que debe conservar | Contraejemplo que debe distinguir |
|---|---|---|---|
| Abstract Factory | Familia de slots y productos relacionados | Interfaces, objetos literales, structs de funciones | Diccionario de utilidades independientes |
| Builder | Configuración y procedencia del producto entregado | Mutable, inmutable, acumulador, consuming Rust | Configurar A y retornar B |
| Factory Method | Contrato sustituible y creación/retorno de producto | Override, función/closure según claim | Método con nombre create que devuelve constante |
| Prototype | Copia del receptor/estado y retorno correlacionado | Clone, copy constructor, derive, serialización | Copiar colección ajena |
| Singleton | Almacenamiento compartido, acceso, inicialización y unicidad acotada | Eager, lazy, módulos, Once/Lazy | Crear en cada acceso o sobrescribir el compartido |
| Adapter | Entrada/operación adaptada conectadas con salida | Objeto, función, estructural | Dos llamadas sin flujo entre ellas |
| Bridge | Abstracción e implementación varían conectadas | Composición, genéricos, traits | Tipos sin relación que comparten T |
| Composite | Contrato común y operación sobre hijos correlacionados | Jerarquías, enums, recursión funcional | Recorrer otros objetos o ignorar hijos |
| Decorator | Delegación conservada y responsabilidad adicional | Objetos, closures, wrappers | Pass-through si el claim exige responsabilidad |
| Facade | Superficie que coordina subsistemas diferentes | Clase, módulo, funciones | Dos métodos del mismo servicio sin coordinación |
| Flyweight | Lookup, miss, creación/publicación/retorno por misma clave | Map APIs, aliases locales, interning | Reemplazo incondicional del objeto compartido |
| Proxy | Delegación y política antes/después del acceso | Lazy, permisos, remoto | Bypass de guarda o decodificar otro valor |
| Chain of Responsibility | Condición de manejo o forwarding correlacionado | Links, pipeline, early return | Invocar todos sin decisión según claim |
| Command | Acción/receptor/payload conservados al ejecutar | Objetos, closures, colas | Ejecutar una acción distinta de la encolada |
| Interpreter | Operandos/contexto combinados en resultado | Árboles, enums, visitor, recursión | Ignorar un operando necesario |
| Iterator | Fuente, progreso/item, terminación/consumo por claim | Yield, async, callback Go, iter Rust | API homónima sin recorrido |
| Mediator | Comunicación mediante mismo coordinador | Eventos, referencias, callbacks | Colegas que usan coordinadores distintos |
| Memento | Estado guardado y restauración con independencia requerida | Copia selectiva, inmutable, encoding | Alias mutable que pierde estado histórico |
| Observer | Registro/baja y notificación de los listeners correctos | Eventos C#, buckets, snapshot, streams | Notificar otra colección o payload |
| State | Despacho por estado activo y transiciones | Objetos, enums, closures | Cambiar campo ajeno al despacho |
| Strategy | Política suministrada/seleccionada gobierna algoritmo | Interfaces, funciones, templates/traits | Parámetro recibido pero política constante |
| Template Method | Esqueleto y hooks sustituibles conectados | Herencia, funciones, traits | Hooks llamados sin participar del algoritmo |
| Visitor | Dispatch correlacionado con elemento/visitante | Double dispatch, overload, match, genéricos | Pasar otro elemento o invocar otro visitante |

Forma estructural e implementación fuerte se publican como claims distintos.
No exigir concurrencia segura a todo Singleton si esa variante no la promete.
No exigir payload a todo Observer ni copia profunda a cualquier Memento.

## 3. Patrones modernos y web

Migrar los diez conceptos actuales: Dependency Injection, Dispatch Table,
Continuation Wrapper, Adapted Continuation Wrapper, Batch Work Queue,
Unit of Work, Exception Retry, Subclass Factory, Cache-Aside y Read-Through Cache.

| Familia de extensión | Contratos que ejercitan el lenguaje |
|---|---|
| DI / composición | Input → almacenamiento → uso; retención, shadowing y sustitución |
| Middleware/interceptor | Continuación, request/response, argumentos, orden y exclusividad |
| Routing/dispatch | Clave → handler → invocación; registro sobrescrito y aliases de clave |
| Repository / Unit of Work | Entidades/cambios/recursos; separado de garantía transaccional |
| Transaction / outbox | Estado de recursos, commit/rollback, atomicidad y publicación |
| Retry / circuit breaker | Transiciones, contador/tiempo, excepciones, callbacks y finally |
| Cache / memoization | Clave, miss/hit, procedencia, invalidación, TTL y concurrencia por claim |
| Async worker / producer-consumer | Enqueue/dequeue, contexto, task, entrega/agotamiento |
| CQRS / event sourcing | Roles de escritura/lectura/eventos y persistencia; nombres no bastan |
| Resource management | Acquire/release, scope, RAII/defer/finally, escapes y cancelación |

Outbox, circuit breaker, CQRS, etc. son casos de diseño futuros, no nuevas reglas
implementadas por este trabajo. Propiedades distribuidas pueden depender de
configuración externa/protocolos que el código local no acredita: unknown.

## 4. Secuencia futura de implementación

No comenzar con todos los selectores y 33 traducciones a la vez. Cada etapa tiene
criterio de salida, sin convertir un subconjunto en soporte total del lenguaje.

1. **Congelar revisión del diseño y corpus de conformidad.** Resolver comentarios
   con IDs D/C estables; obtener ejemplos por capacidades. Salida: no contradicción
   entre gramática, ejemplos, tipo de cada rol y resultados esperados.
2. **AST, parser, resolución y tipos.** Versión explícita, diagnósticos por span,
   scopes, imports, contratos de firmas y rechazo de capacidades ausentes. Salida:
   todos los casos léxicos/de errores y snapshots AST, sin escanear código.
3. **Núcleo relacional acíclico.** Selectores, joins, predicados, use, negación
   con cobertura, agregaciones; traducción estructural explicable. Salida: pequeños
   grafos con oráculos y comparación contra fragmentos equivalentes de KQL 1.
4. **Recursión positiva y modelos.** SCC, universos finitos, estratificación,
   memoización, estados y presupuestos. Salida: ciclos, cadenas >32, negación
   incompleta, parametrización y determinismo de resultados.
5. **BODY ordenado y adjacent.** Identidad de ocurrencias, regiones, llamadas,
   resultados, ramas, loops/continue y excepciones. Salida: C08–C23 y control nativo.
6. **Intervalos y efectos.** Alias/heap/escapes, incertidumbre, todos los caminos,
   salidas/suspensión, preservación y contraejemplos. Salida: ningún hueco del IR
   se interpreta como pureza; conformance de preservación y presupuesto.
7. **Iteración, flujo configurable y concurrencia.** Contratos separados por
   capacidades; activar lenguajes/modelos sólo con contraste correspondiente.
8. **Migrar bibliotecas y catálogo.** Primero Lookup, Factory/Product Flow,
   Builder, Memento y Observer; luego los demás. Conservar cada oráculo y claims.
   Las diferencias intencionales deben documentarse, no cambiar expectativas para
   que pase una query equivocada.
9. **Rendimiento y distribución.** Corpus real congelado, caché/incremental,
   memoria y errores de carga. Sólo entonces evaluar Python/Rust por profiling.
10. **Convivencia y eventual deprecación.** Publicar adaptador KQL 1 para el
    subconjunto traducible y diagnósticos del resto. No retirar el dialecto anterior
    sin migración validada, documentación y decisión explícita de versión.

## 5. Conteo y criterios de salida

Separar estados por fila: `specified`, `parser-supported`, `ir-supported`,
`query-tested`, `corpus-validated`, `unsupported`. No usar un booleano global
«lenguaje soportado». La unidad es capacidad × lenguaje × perfil × variante.

Manifiesto futuro de fixtures: ID estable, requirement IDs, lenguaje/versión,
fuente/hash, query/hash, modelo/perfil, roles esperados, resultado lógico,
completitud, diagnósticos y justificación. Expectativa = positivo, negativo,
unknown o error; TP/TN/FP/FN se calculan después. No pedir un FP como éxito esperado.

Cada variante/lenguaje anunciado exige positivo, negativo próximo y ruido válido;
si depende de inferencia parcial, unknown explícito. Edge cases de bindings,
control y modelos se comparten, sin sustituir los específicos del patrón.
Los tests deben verificar bindings/ubicaciones y no sólo «hay algún match».

Performance: misma revisión de fuentes, misma query/claim, perfiles y modelos.
Comparar extracción, frío/caliente, invalidación y RSS; explicar diferencias de
resultados antes de celebrar velocidad. Budgets agotados no mejoran recall ni
tiempos completos. Un benchmark de KQL 1 vs 2 requerirá implementar ambos lados;
esta documentación no contiene mediciones que todavía no existen.
