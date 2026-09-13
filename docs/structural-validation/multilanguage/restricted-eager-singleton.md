# IR 1.43: distinguir Singleton eager de instancia compartida

La revisión corrige el falso positivo de intención de RxJS identificado en
[IR 1.42](class-expression-factories.md). Refuerza `singleton#eager-shared` y
conserva `singleton.shared_instance` como operación reutilizable de alcance
amplio. El [diseño](../../design/structural/restricted-eager-singleton.md) precedió
al código; los [contratos IR](../../structural-ir.md#construction-access-and-resolved-allocation-sites)
explican acceso, inventarios, conteos y límites.

## Verificación

La [verificación final](ir143-checks.json) pasa **5.340 tests en 240.65 s**,
y mypy en 102 archivos. Los 39 ejemplos KenQL de las guías parsean y los 34
de la guía IR se ejecutan contra fuentes. El wheel coincide byte a byte con
los módulos y TOML escaneados y pasa pruebas fuera del checkout, incluido roundtrip.

Se agregan 90 tests: 88 de acceso/construcción y dos ejemplos ejecutables de la
guía. Los tests anteriores de instancia compartida ahora distinguen la operación
amplia de la variante eager reforzada. El catálogo conserva 23 GoF, 44 variantes
listas, 33 variantes de diseño, 10 reglas modernas/web y ocho operaciones públicas.
La variante eager tiene cobertura Java/C#/TS; las clases JavaScript públicamente
construibles se siguen encontrando mediante `singleton.shared_instance`.

## Cambio y precisión

La variante eager requiere todos estos hechos, mediante KenQL en el TOML:

1. Inicialización de campo estático con su propia clase y accessor directo,
   reutilizando `singleton.shared_instance`.
2. Inventario soportado de constructores explícitos de instancia, con al menos
   uno y todos privados. Firmas de overloads TS no desaparecen por compartir nombre.
3. Un único sitio CALL ya resuelto a esa clase en el grafo analizado.

El IR nuevo es genérico: `CONSTRUCTOR_INVENTORY`, `RESOLVED_ALLOCATION_COUNT` y
atributos consultables de visibilidad/constructor. Los modificadores se leen de
tokens nativos, no del texto de comentarios, anotaciones ni parámetros-propiedad.
Los defaults Java/C#/TS se distinguen. Constructor estático C# no es constructor
de instancia; clase partial, primaria, record o con errores no certifica inventario.

La matriz usa exactamente las mismas 42 fuentes en ambas versiones, 14 por
lenguaje; compara el patrón canónico y comprueba además que la operación amplia
sigue encontrando las 42 instancias compartidas:

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| [1.42](restricted-eager-before.json) | 15 | 0 | 27 | 0 |
| [1.43](restricted-eager-after.json) | 15 | 27 | 0 | 0 |

Son **27 FP corregidos en una muestra controlada**, no una cifra de precisión
universal. Los positivos varían nombres, comentarios, overloads privados y
creaciones de otro tipo. Los negativos incluyen construcción pública/protected,
constructor ausente, private sólo en comentario/parámetro, otro factory/reset,
segundo campo inicializado y factory en clase anidada. Los casos de sintaxis
no se compilan ni prueban semántica de tipos; se evalúa la evidencia de fuente.

Pruebas adicionales cubren defaults, firmas con acceso mixto, atributos Java/C#,
modificadores C# combinados, interfaces, métodos llamados constructor, getters TS,
errores de parsing, referencias importadas TS y presupuestos con 100 clases.
Los aliases opacos se prueban como un límite conocido, no como ausencia global
de otras creaciones.

## Revisión externa

Los [testigos](restricted-eager-witnesses.json) registran fuentes y hashes,
commits, inventarios, conteos, visibilidad y pruebas de ambas consultas.

| Caso | Variante canónica | Operación compartida | Revisión |
|---|---|---|---|
| Pandovski / SingletonEager | Conservada | Conservada | Constructor privado y un sitio de creación |
| iluwatar / IvoryTower | Conservada | Conservada | Constructor privado con guardia y un sitio de creación |
| Commons IO / FileSystemProviders | Conservada | Conservada | Constructor privado parametrizado y campo INSTALLED |
| RxJS / Notification | Excluida | Conservada | Constructor público y tres sitios de creación resueltos |

RxJS tiene constructor público, `createNext`, `createError` y un valor estático
para COMPLETE. La normalización de aserciones TS sigue siendo correcta y se
conserva. El [único cambio en los escaneos comparables](ir143-production-changes.json)
es eliminar su clasificación canónica de Singleton. No se pierden los ejemplos
válidos revisados ni se oculta la evidencia útil de instancia compartida.

La [regresión GoF](ir143-corpus-regression.json) conserva exactamente todos los
matches anteriores: **73 presencias esperadas en 281 ejemplos**, 736 archivos
únicos, 745 ocurrencias y 6.463 consultas completas. Estas etiquetas de upstream
no son un oráculo independiente de TP/FN. Continúan las brechas y los FP de
intención de otros patrones descritos en auditorías anteriores.

Se repitieron alcances de Requests, Flask, RxJS, Commons IO, rust-log, la caché
de iluwatar, fmt y los alcances modernos de Requests, RxJS, rust-log y Cobra.
También los seis alcances de Lit y el archivo de mixins Pandovski de IR 1.42:
los cuatro factories de producción, tres fixtures JS y tres ejemplos TS permanecen.
Todos los resultados de consulta finalizan dentro del presupuesto. fmt conserva
677 diagnósticos; cero matches allí no demuestra TN ni soporte completo de macros.
Sólo se parsearon fuentes externas; no se importaron, compilaron ni ejecutaron.

## Rendimiento

Las [mediciones](restricted-eager-performance.json) comparan los mismos archivos:

| Archivo | Consulta 1.42, mediana ms | Consulta 1.43, mediana ms | Parseo/enlace 1.43, mediana ms |
|---|---:|---:|---:|
| pandovski/SingletonEager.java | 0.203 | 0.231 | 0.922 |
| java-patterns/IvoryTower.java | 0.213 | 0.234 | 1.513 |
| commons-io/FileSystemProviders.java | 0.241 | 0.292 | 8.748 |
| rxjs/notification.ts | 0.252 | 0.273 | 26.324 |

Los tres archivos Java conservan un match; RxJS pasa de uno a cero.
Singleton en el alcance completo de Commons IO termina con 1102 estados.
El JSON incluye p95 y costo separado de construir la vista.

Son mediciones de esta máquina: 30 muestras sobre índice y registro preparados,
diez de parseo/enlace y diez de proyección por archivo. No incluyen CLI, arranque
ni caché persistente. El conteo de sitios es un pase por hechos resueltos, seguido
de uno por clases; no dispara una búsqueda de todo el grafo por cada candidato.
La caché configurable, 500 MB por defecto, mantiene su contrato.

## Límites y trabajo pendiente

- Un sitio de definición puede ejecutarse varias veces. Los conteos no representan
  instancias runtime ni cierran el mundo de ALLOCATES_TYPE: aliases, reflexión,
  serialización, clonación y fuentes excluidas pueden crear objetos no contados.
- Private TS se verifica estáticamente. No se afirma una barrera runtime ni que
  los fixtures compilen. C# partial, primarios y records necesitan modelos propios.
- El almacenamiento no se prueba inmutable. Resets con nueva construcción directa
  añaden un sitio y se excluyen; un alias opaco, escritura de null o efectos ocultos
  no se convierten en garantías de permanencia.
- La variante lazy conserva su firma guardada y necesita una revisión separada.
  La query Singleton canónica incluye esa alternativa y no certifica unicidad
  global. Las formas JavaScript con guardias de constructor necesitan otra
  variante; no se simula constructor private inexistente en el lenguaje.

Una continuación debe revisar lazy y los mecanismos once/module-shared conservando
la distinción entre acceso compartido, restricciones de creación y concurrencia.
