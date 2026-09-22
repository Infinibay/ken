# Contratos de conformidad y revisión

Contratos del diseño 0.1. [Índice](README.md).
Existe una implementación parcial. El [registro de los 96 contratos](conformance-status.json)
mantiene evidencia, pendientes y conteos separados: `case` significa un caso
enfocado probado, **no** todos los lenguajes/variantes; `partial` conserva las
obligaciones faltantes y `pending` no tiene cierre acreditado. Consultar también
el [estado del motor](implementation-status.md). No inferir conformidad completa
del número total de tests ni del soporte sintáctico.

## Oráculos

`P`: contrato satisfecho y bindings correctos. `N`: contrato refutado con cobertura
del ámbito. `U`: evidencia insuficiente. `E`: error de compilación/carga o evaluación
de la query, con fase explícita. `I`: ejecución incompleta por recursos/cancelación, distinta de U semántica.
Cada prueba deberá fijar perfil, lenguaje/modelo y universo. Una P en un perfil
de alcanzabilidad abstracta no acredita ejecución runtime concreta.

Los IDs son permanentes. Al implementar se enlazan a fixtures; no se reemplaza
esta lista por un conteo de tests que no diga qué contrato verifica.

## Gramática, identidad y modelo

| ID | Caso | Resultado |
|---|---|---|
| C001 | Archivo con versión kql/2, imports resueltos y patrón Worker tipado | P |
| C002 | Mismo texto enviado al parser kenql/1 | E, versión incompatible |
| C003 | Propiedad inexistente o no aplicable al selector | E, span y schema esperado |
| C004 | Entrada in omitida o no ligada en use | E |
| C005 | Salida out ya ligada | P sólo si misma identidad |
| C006 | Dos bindings homónimos en scopes diferentes se intentan unificar | N |
| C007 | Dos capturas distintas seleccionan el mismo campo, sin desigualdad | P permitido |
| C008 | Lo anterior con where a != b | N |
| C009 | Un rol sólo existe en una rama y se usa después | E |
| C010 | Variable capturada dentro de not exists/optional escapa | E |
| C011 | Macro/named pattern reutilizado dos veces con internos homónimos | P sin captura accidental |
| C012 | `type:string` frente a TypeScript any o unknown declarados | N si tipos conocidos distintos |
| C013 | `type:string` frente a tipo no inferido | U |
| C014 | `type_status:unknown` frente a tipo no inferido | P, sin inferir que sea string |
| C015 | `fields exact` con campo adicional | N |
| C016 | `fields exact` con inventario incompleto | U |
| C017 | Argumento `1 + f()` consultado como Binding con nombre propio | E de tipo, no binding inventado |
| C018 | Pack dinámico no resuelto pedido como argumento efectivo 0 | U |
| C019 | family iterable sobre array y generador modelados | P en ambos, sin deducir eager |
| C020 | Método `next` sin contrato/protocolo de iteración | N/U según obligación, no P por nombre |

## BODY e intervalos

| ID | Caso | Resultado |
|---|---|---|
| C021 | Declaración → logging → asignación; BODY normal | P con orden válido |
| C022 | Mismo programa con adjacent entre declaración y asignación | N |
| C023 | Sólo comentarios y saltos entre anclas adjacent | P |
| C024 | `pass`/sentencia vacía explícita entre anclas adjacent | N |
| C025 | Adjacent al comienzo/final o sin ancla siguiente del bloque | E |
| C026 | Un solo nodo satisface ambas anclas para fingir adyacencia | N |
| C027 | Gap seguido por where y luego assignment | P; where no mueve el extremo |
| C028 | Asignación al binding protegido en el ancla final, fuera del intervalo | P |
| C029 | Misma asignación dentro del intervalo | N |
| C030 | Escritura del mismo valor durante forbid write | N |
| C031 | Escritura del mismo valor durante preserve binding, igualdad acreditada | P |
| C032 | Modificar y restaurar dentro de preserve binding/state | N |
| C033 | Llamada externa con posible acceso al objeto protegido | U |
| C034 | Logging modelado que no accede al objeto protegido | P para preservación, no garantía de terminación |
| C035 | Llamada prohibida sólo desde helper dentro del intervalo | N con through:transitive; P con direct si no hay llamada directa |
| C036 | Método inicial recursa dentro de ancla excluida del intervalo | P para prohibición posterior |
| C037 | No existe camino entre anclas | N, no verdad universal vacía |
| C038 | Un camino conserva binding y otro lo modifica | N para all; P para witness válido y etiquetado |
| C039 | Rama con throw antes del extremo final | Preservación all de conectores puede P; must_reach N/U |
| C040 | Cuerpo de closure no invocada contiene escritura | No cuenta como efecto ejecutado del intervalo |
| C041 | Closure invocada y captura alias protegido | N/U según resolución del efecto |
| C042 | Anclas mezcladas entre iteraciones distintas sin contexto suficiente | U |
| C043 | Rama A produce valor, rama B lo consume sin camino compatible | N |
| C044 | Return de valor de otra invocación al mismo factory | N |
| C045 | Fragmentos de dos matches se mezclan por salidas compatibles | N |

## Control, tipos y efectos nativos

| ID | Caso | Resultado |
|---|---|---|
| C046 | For C con continue llega a update antes de condition | P para CFG normalizado correcto |
| C047 | Lowering de for a while saltea update en continue | Falla del frontend; no aceptar equivalencia |
| C048 | Break de loop interior frente a break etiquetado exterior | Destinos distintos obligatorios |
| C049 | Finally retorna y sustituye return/continue pendiente | N para contrato que depende de salida original |
| C050 | Try termina por catch recuperado y se pide else nativo | N |
| C051 | Excepción en else intenta entrar a catch hermano | N |
| C052 | Filtro catch falso selecciona otro handler | Orden y guardas preservados |
| C053 | Rust binding mutable después de move o durante borrow incompatible | No P de writable_at sin análisis que lo permita |
| C054 | JS const de lista con push | P de binding preservado, N de contenido preservado |
| C055 | Copia superficial de lista cuyos hijos se modifican | P shallow si slots constantes; N reachable |
| C056 | Sobrecarga + con efecto/throw | No deducir pureza de operador ni aritmética normal |
| C057 | Identificador público Python consultado como enforcement de acceso | U/N según perfil; sólo convención acreditada |
| C058 | Import dentro de callable y export estático de módulo | Owners y efectos diferentes |
| C059 | Class/closure expression define body que no se ejecuta aún | contains P, executes_in no P automático |
| C060 | Default de parámetro con efecto al definir función | Efecto pertenece a fase de definición según lenguaje |

## Iteración, estados y concurrencia

| ID | Caso | Resultado |
|---|---|---|
| C061 | Map transforma item y alimenta output | P para produces/output_of |
| C062 | Callback map usa constante/otra variable en vez del item exigido | N |
| C063 | Filter conserva elementos seleccionados por predicado | P para selección, no transformación arbitraria |
| C064 | LINQ Select interpretado como filter por nombre | Falla de modelo; N a esa interpretación |
| C065 | Pipeline lazy construido sin consumidor | P defined; N/U consumed según cierre |
| C066 | Generador con yield léxico inalcanzable | P syntax/generator shape; no P producción |
| C067 | Async generator sin await adicional | P para forma generadora válida |
| C068 | Callback Go ignora false de yield y sigue | N para variante stop-on-false |
| C069 | For y map paralelos cumplen recorrido pero distinto orden | P recorrido; N/U preserves_order |
| C070 | Excepción/early exit impide cubrir todos los elementos | No P de exhausts/totalidad por ser map |
| C071 | Transición de lock A combinada con release de B | N |
| C072 | Acquire conocido, llamada desconocida, uso protegido | U si puede alterar recurso/estado |
| C073 | Escritura concurrente sin happens-before modelado | U/N de preservación shared, no P local promovido |
| C074 | Operación llamada join sin API/protocolo resuelto | No P de sincronización |
| C075 | Sanitización HTML aplicada a sink SQL | N/U como barrera de SQL |
| C076 | Guardar referencia mutable como Memento histórico | N cuando se demuestra mutación que rompe snapshot |

## Recursión, agregaciones, cobertura y caché

| ID | Caso | Resultado |
|---|---|---|
| C077 | Cadena de llamadas de longitud 100, presupuesto suficiente | P alcanzabilidad, sin límite 32 |
| C078 | SCC positiva con ciclo y semilla | Punto fijo termina, sin duplicados |
| C079 | SCC positiva sin semilla | Vacío y warning; no inventa solución |
| C080 | Recursión a través de not o agregado | E en revisión 0.1 |
| C081 | Generación no acotada de strings/números dentro de SCC | E |
| C082 | Relación incompleta negada | U |
| C083 | Count exacto sobre universo incompleto | U; at_least puede P con testigos suficientes |
| C084 | Sum de valores repetidos versus sum_by eventos | Resultados distintos según semántica publicada |
| C085 | Min/max/avg vacío | Option.none, no 0 |
| C086 | División por cero en cálculo de query | E de evaluación, diagnóstico; no fila silenciosamente eliminada |
| C087 | Timeout/cancelación con cero matches hasta ese momento | I, nunca no_match confirmado |
| C088 | Misma query fría/caliente y mismo modelo | Mismos bindings, modalidades y completitud |
| C089 | Cambio de callee/modelo/archivo nuevo afecta negación | Invalidación transitiva, no negativo cacheado viejo |
| C090 | Resultado previo parcial reutilizado como completo | Falla del motor, prohibido |
| C091 | Cache 0 | Sin retención entre queries; resultados semánticos iguales |
| C092 | Caché excede presupuesto 500 MB | Evicción/no retención; reportar bytes, no degradar semántica |
| C093 | Limit de presentación corta filas | results_truncated separado de complete |
| C094 | Evidencia opcional ausente | No elimina match obligatorio |
| C095 | Predicado de posibilidad acreditado | P de pertenencia al modelo, no ejecución segura |
| C096 | Lenguaje soporta sintaxis pero carece de análisis requerido | U/capability_missing explícito, no P por omisión |

## Familias de fixtures por lenguaje

Los casos portables deben instanciarse al menos en Python, JavaScript, TypeScript,
Java, C#, Go, Rust, C++ y PHP cuando el frontend/capacidad exista; Ruby se registra
por separado hasta acreditar soporte. No inventar `catch when` en un lenguaje
sin filtros, borrow Rust en Java ni constructor de clase en Go. Se usa `not_applicable`
con justificación, nunca como test pasado. El universo de soporte no se deduce de
esta lista de aspiraciones.

Para cada caso positivo: renombrar, intercalar operación independiente, cambiar
forma nativa equivalente y añadir shadowing inocuo. Para cada negativo: romper una
sola obligación y conservar las demás. Añadir casos que producen unknown por
análisis incompleto, distintos de negativos completos.

Fixtures de KQL 1 y el catálogo existente se reutilizan como fuentes y oráculos
revisados. No heredar `xfail` automáticamente: una diferencia puede ser un bug
viejo, una obligación nueva o un límite explícito del IR.

## Revisión documental de esta propuesta

Antes de implementación se debe comprobar: todos los roles tienen tipo/ámbito;
todos los operadores tienen precedencia/contexto; las anclas de ejemplos son
inequívocas; los imports de ejemplos distinguen biblioteca hipotética y existente;
las extensiones del modelo aparecen en gramática; los enlaces internos resuelven.

La validación documental sólo prueba consistencia de archivos/ejemplos en el
nivel revisado. No prueba que el lenguaje pueda parsearse ni que sus análisis
sean correctos o rápidos: eso corresponde a las etapas de [migración](migration.md).

Revisión documental inicial del 14 de septiembre de 2026: ocho capítulos Markdown y una
gramática de 111 producciones; enlaces locales verificados, fences equilibrados,
sin producciones referenciadas pero indefinidas ni definiciones duplicadas, y
96 IDs C001–C096 únicos/en orden. `git diff --check` sin errores. No se implementó
un parser para realizar estas comprobaciones, ni se ejecutaron los 96 contratos.

Ampliación documental del mismo día: doce capítulos Markdown tras añadir los
cuatro planes técnicos. Verificados 60 enlaces locales dentro de esos capítulos,
fences equilibrados, dependencias de las 17 tareas, 14 IDs de índices y 10 IDs de
benchmarks, sin errores; `git diff --check` también pasa. Esta comprobación no
ejecuta las migraciones propuestas ni mide su rendimiento.
