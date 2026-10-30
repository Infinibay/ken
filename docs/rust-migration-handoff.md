# Continuar y terminar la migración a Rust

Preferencia de ejecución vigente, indicada explícitamente por el usuario:
implementar bloques funcionales más grandes y separar bastante más las
validaciones. Al cerrar cada bloque, ejecutar una validación conjunta del alcance
afectado; evitar encadenar suites completas, Clippy, CI y replay después de cada
cambio pequeño o commit. Repetir comprobaciones puntuales cuando un fallo concreto
o un cambio posterior lo justifique. Agrupar la matriz amplia y los archivos de
evidencia en hitos. Esta instrucción sustituye la cadencia más frecuente de los
planes anteriores; conserva los criterios de corrección y las referencias
originales. Mantener el foco de implementación en Linux x86_64.

Actualización relacional del30/10: `ken-query` completa el otro backend KQL2 y
el coordinador puro `compile`. Leer la
[API](rust-migration.md#kql2-compilación-relacional-y-coordinación) y el
[plan](superpowers/plans/2026-10-29-rust-kql-relational-compiler.md).
`Program` es el nombre común; `IndexedProgram` sigue como alias compatible.
`CompiledQuery` contiene metadata y opcionalmente un `Arc<RelationalQuery>`.
`compile` valida profundidad96 de fuente y todas las bibliotecas, resuelve imports,
especializa modelos y decide backend; la preferencia puede forzar Relational.
Recibe bibliotecas explícitas: descubrimiento empaquetado queda en el host.

El lowering conserva selectores/requisitos/usos, relaciones semánticas, witnesses,
walk/count, scopes, aliases, patrones y BODY checking. No confundir compilación
con ejecución. Próximo núcleo: operadores relacionales/indexados sobre
QueryView/GraphIndex, sesiones y evaluación BODY; después KQL1 y superficies
CLI/MCP/config/cachés/catálogo. Python instalado sigue activo. M5 sigue abierto;
M6 y el resto de M7/M8, y la calificación SkylakeX/Intel, siguen pendientes.

Trampas de protocolo: `QuotedTerm` conserva token y literal decodificado; no es un
rol aunque empiece por `$`. Mapas se capturan como OrderedMap/items para conservar
orden. El alias final no visita AST/BodyPattern ni attrs de Edge. Los witnesses
privados se renombran por span de clause; parámetros de AST no se remapean. Las
alternativas intersectan bindings/tipos, sin filtrar aliases por intuición nueva.
El cache de patrones usa Arc y orden postorder. Al inlinear un forwarding corto,
el root nuevo conserva como definición el root original además del patrón hijo:
la exclusión original depende de identidad. No simplificar ese detalle.

SHA relacional: repr del File preparado, en streaming. Los presupuestos de trabajo
se comparten entre patrones/BODY y cobran metadata completa, expresiones, flags,
parámetros, copias de scopes y payload generado; candidatos de nombres
son locales por bloque para mantener sufijos entre alternativas. Las búsquedas de
exports tienen índice sin permitir mutación pública de sus items. Regex string de
initialized_with usa un comprobador de sintaxis nativo acotado, con flags/grupos/
referencias/recursión/lookaround/conjuntos/fuzzy y propiedades Unicode congeladas.
La primera aproximación con Onig se retiró: aceptaba escapes inválidos y rechazaba
flags válidos del paquete Python regex. No se añade dependencia ni se construyen
autómatas. Un ValueError original por regex inválido se convierte en diagnóstico
nativo controlado. Se conserva literalmente el patrón; matching sigue pendiente.

| Recurso en ken-query | Casos | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| relational-reference.json.gz |440/145 planes|121358|`c0899f8f0cab01ec1393935d3de70e85cd2fcac02ce5895f0a463b9fc1137d34`|
| compilation-reference.json.gz |34/13 programas|30544|`76f73dfcee0101816a76a4404b0661ec3439e364ed644bd5754a7bbb20a7aac8`|
| relational-capabilities.json |vocabulario original|5945|`b0d3a69e5e8eca927b034c704a5e916c7e9d5079ea5e008fbb8d42f18e262dc4`|
| relational-regex-reference.json.gz |127/78 válidos|1401|`809ff9aba2443c7ce1ebe7fe7c6880e4eff10f3f31a57e832fc17ee75d70a72b`|
| regex-properties.json |aliases/valores originales|29011|`2320628a29037e51df72191258fe09e69ea2539c6198ce597030007eb40a48ef`|

Pasaron39 raíces nativas, Clippy estricto y formato. Una revisión fresca final
identificó tres Important: gramática regex, payload sin cobrar y snapshots de
ámbitos cuadráticos. Todos tienen regresión roja→verde en una pasada; no hubo
Critical/Minor ni segunda revisión. Se preserva el ejemplo válido de4000 exports.
La sintaxis regex limita profundidad512 y trabajo de rescans; no acredita matching.

Observaciones nuevas una vez, contra original1066 autenticado antes/después.
No se repitieron parser/indexed/BODY/model/CPU/CI/global; público271/Best247 no
cambian. Crudos/scripts/workspace se conservan locales y sin seguimiento.

Actualización de compilación indexada del29/10: `ken-query` implementa
`compile_indexed`, `compile_indexed_branches`, `IndexedProgram` y `compile_body`.
La [API](rust-migration.md#kql2-compilación-indexada-y-comprobación-body) recibe
sintaxis ya resuelta/especializada. El primer entry equivale a `_compile`; el
segundo compone alternativas indexadas, mantiene el límite global y las huellas
originales. El dispatcher y el lowering relacional se completaron en el bloque descrito arriba.
Siguen operadores, sesiones, evaluación BODY y conexión KQL1/2 con CLI/MCP/config.

Scans/actions/BODY conservan el orden del pipeline; scopes de cuantificadores y
testigos `exists` son privados, y patrones generan roles higiénicos con el mismo
contador. Tipos de query se comprueban aparte de operandos de fuente. BODY separa
coordinación, operandos/condiciones, restricciones call/construct e intervalos.
Outputs retienen orden y usan un set auxiliar para pertenencia; resume indexa por
span completo los candidatos iguales, conservando el primer igual de Python sin
recorrer todo el prefijo de cada instrucción.

La huella indexada usa repr de **listas** para scans/filtros/acciones/optional/steps,
**tuplas** para proyección/orden/predicados y **dict** de enums en orden original.
No reemplazarlo por JSON ni convertir todos los Vec a la misma forma. Límites
enteros grandes usan RawValue y repr decimal exacto. `sha2` pasó de dependencia de
prueba a runtime con la misma versión ya fijada; no hay versión nueva en Cargo.lock.
`compile_body` conserva roles mutados antes de errores normales; los errores se
reenvuelven con el mismo source:start y código que `_compile`, no uniformemente
como unsupported_capability. Mantener distintas las reglas call y let-call:
receiver miembro y receiver_version sólo están admitidos en la primera.

Seguridad nativa: validación iterativa de topología y slots obligatorios antes de
indexar/remapear; profundidad512 y65536 unidades de trabajo además de los límites
originales de256 pasos/96 joins. El presupuesto cuenta registros AST y parámetros,
1 unidad adicional por64bytes de payload y entradas de mapas de BODY. Se cobra
antes de copiar expresiones/subárboles BODY/optional y se comparte entre cuerpos
anidados. Esto puede rechazar expansiones patológicas que Python terminaría tras
trabajo enorme. Tras256 pasos no se sigue reteniendo un plan que ya no puede
retornarse, pero se conservan bindings y diagnósticos posteriores de lowering
hasta error o presupuesto. Los fallos nativos de presupuesto conservan resource_limit. Tres AST manuales sin
select producían StopIteration original; el nativo retorna error estructurado.
No extender esas diferencias a diagnósticos de fuente normal.

Capturas nuevas, autenticadas antes/después contra original1066, consumen ASTs
preparados/expandidos aceptados sin repetir parser/bibliotecas/modelos. Casos nuevos
se observaron una vez. La primera invocación del script falló antes de observar
por falta de PYTHONPATH; se corrigió el wrapper. Luego un assert del adaptador
identificó los tres StopIteration ya journalizados: fixture finalizada del journal,
sin repetir esos casos. Crudos y workspace se conservan locales y sin seguimiento.

| Recurso en ken-query | Casos | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| indexed-reference.json.gz |534/285 planes|179905|`e04f6384a3fe04d4791c2bd84005fe1f6529f851e2ec0eba84bd32a96b80fb12`|
| body-check-reference.json.gz |670/374 planes|37959|`be4698f3a09e7fdf7c3812a4dd75162a516ca25e500046f0358c13387b8846d4`|
| capabilities.json |vocabulario original|8965|`743522d97fcfdba6c81aefda220954e9ec7330ac8e3ba4be8d2819728caff8ce`|

Pasaron25 raíces nativas agrupadas, incluyendo paridad completa, ramas/límite
privado, slots inválidos, cadenas/DAGs y30000 instrucciones BODY con10000 capturas
en pila normal. Clippy estricto y formato también pasaron. La revisión final
identificó cinco Important, todos con reproducción roja y corrección en una pasada:
materialización antes del límite, slicing de regex corrupto, captura de lectura
ante expected Call, span outer-let y recorrido cuadrático de restricciones gap.
Tests adicionales fijan error directo/envuelto, precedencia posterior a256 pasos,
intervalos y presupuestos compartidos de BODY/optional. La expansión rechazada
(512 cláusulas×512 usos) bajó de1839935 a134699 asignaciones;512 restricciones gap,
de271903 a6178. No hay Critical/Minor ni segunda revisión. No hay ejecución de consultas ni
aceptación global nueva; público271/Best247 no cambian. M5 permanece abierto,
igual que M6 y resto de M7/M8 y la calificación SkylakeX/Intel. Python instalado
sigue activo. Ver el [plan](superpowers/plans/2026-10-29-rust-kql-indexed-compiler.md).

Actualización KQL2 del29/10: `ken-query` implementa sintaxis y preparación puras.
Leer primero la [API](rust-migration.md#kql2-sintaxis-y-preparación-nativas) y el
[plan](superpowers/plans/2026-10-29-rust-kql-frontend.md). El recorrido público
original es `compile` → validación de profundidad compilable96 → bibliotecas →
modelos → selección de backend. La ruta relacional/graph conserva el árbol;
solamente la indexada expande alternativas128 antes de `_compile`. No confundir
`compile` con `_compile` ni aplicar expansión a ambas rutas.

`parse`/`parse_bytes` producen AST tipado; `resolve_libraries` recibe un mapa
inmutable módulo→File; `specialize_models` comprueba firmas y genera `@model` en
orden de primer uso; `expand_indexed_alternatives` genera `@variant` y detecta
recursión; `predicate_components` calcula SCC/estratificación iterativamente.
Los dos compiladores y el coordinador puro se añadieron en los bloques descritos
arriba; no hay ejecución BODY todavía. Siguen operadores sobre QueryView/GraphIndex,
sesiones, runtime BODY y conexión KQL1/2.

Trampas observadas: `dataclasses.asdict` pierde Expr frente a SourceExpr;
conservar `__class__` recursivo. Las identidades usan repr de dataclass/tuple,
no JSON. `dataclasses.replace` es superficial: evitar `..clone()` de árboles
recursivos que luego se descartan. Preservar orden de declaraciones/modelos y
los spans originales antes/después de consumir cada producción; `not in` tiene
un inicio de span original particular. Los argumentos de tipos y cadenas `else`
son iterativos; la recursión restante protege pilas pequeñas con stacker0.1.25,
ya presente en el lock. AST/ayudantes tienen techo512 además del anidamiento
configurado96. La única diferencia de diagnóstico aceptada es el token de corte
del agotamiento de pila original en `depth/type/600`: código/mensaje conservados,
span nativo válido. No extender esa excepción a casos normales.

Referencias nuevas contra original1066 autenticado antes/después; ninguna suite
original repetida. Las observaciones de expansión consumen AST ya capturado.
El adaptador de captura reanudó el journal tras fallar decodificando un AST profundo;
saltó todos los nombres ya observados y elevó recursión sólo para decodificar,
restaurando el valor original antes de observar. Crudos/scripts/workspace locales.

| Recurso en ken-query | Casos | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| frontend-reference.json.gz |574 +9 snapshots|141735|`4657e2d18f5bd423240353b877f8e9bfc3137aaaf255fe195b59e68fbf3d2b82`|
| regex-reference.json.gz |890|45453|`a6d503b427c339717c31b6754551c155fcf2ef2783ba91cc72f9c5fe7d1c7d1b`|
| expansion-reference.json.gz |227|85658|`b996a940cd6727775494fa26a62c3f37991bc722caa9f4293cc742a3504f470c`|
| unicode15.json |alpha/digit/assigned|19704|`19bd21e319937a520714e296186015a40332bad3965add40365224b710407d23`|

Validación del bloque:12 raíces nativas, Clippy estricto y formato. La revisión
final detectó un Important: copia profunda de todos los prefijos por cada cláusula
plana. Regresión primero roja:512 cláusulas, una alternativa,531997 asignaciones.
La reparación mueve prefijos y duplica sólo en bifurcaciones;3102 asignaciones
con una alternativa y5174 con dos. Un test allocator separado cuenta sólo durante
la API pública de expansión; no depende del reloj. Suite afectada12/12 tras la
única pasada de reparación; sin Critical/Minor ni segunda revisión.
Las pruebas de pila real se ejecutan en el hilo normal; sólo la lectura/comparación
de fixtures JSON profundas usa un hilo de prueba amplio. Público271/Best247 no
cambian; sin replay CPU/CI/modelos ni aceptación global. M5/M6 y resto de M7/M8
siguen abiertos, igual que SkylakeX/Intel. El Python instalado no se reemplaza.

Actualización de grafos ejecutables del29/10: se implementaron QueryView y
GraphValue en ken-program; publicación READY, diccionarios/valores por columnas,
overlays OPERATION, scans perezosos y vistas de fuente en ken-store; adquisición
de proyectos persistentes/temporales en ken-structural. Se reutiliza exactamente
el esquema15: no agregar índices a escondidas, schema::validate compara todo el
DDL. Las migraciones13/14 eliminaron role/start/end/member-key/operation-region;
los accesos globales correspondientes conservan ese compromiso de recorrido.
Las selecciones por un extremo correlacionan sus atributos y evitan un recorrido
global; kind/native_kind/owner usan índices reales. Count de relación usa el
inventario mantenido, no enumera los hechos.

IR de fuente→QueryView conserva entrada y metadatos opacos; normaliza ocurrencias,
retornos y slots. En la frontera original con sets, comparar hechos completos
como multiconjunto. Publicación→reader debe conservar exactamente el orden
recibido, evidencia y duplicados. Nunca pasar la fixture por serde Value antes
de decodificar StructuralIr: reordena entidades y pierde enteros grandes.
El codec coincide con286 firmas/IDs originales, floats aleatorios, negativos,
infinidades/NaN y contenedores. Tuple/set heredados mantienen tags; el set nativo
usa orden canónico, no repr por hash de CPython. Un surrogate aislado sobrevive en
IR RawValue pero SQLite lo rechaza, igual que el original. El nuevo normalizador
conserva familias escalares y distingue posiciones textuales de numéricas, con
igualdad exacta bool/int/float y enteros>2^53.

Las transacciones publican32768 registros del grafo como máximo y comprueban
cancelación y ownership cada512; incluye sintaxis y ambos inventarios. La sintaxis
legacy de grafos ya READY se prepara atómicamente con open_with_check y
checkpoints en lectura, construcción y recorrido. READY aparece sólo al final. Error→limpieza de la publicación
incompleta propia; lease ajeno activo→conflicto; lease abandonado→reconstrucción.
No hay API de resume por ordinal sin garantizar input ordenado idéntico. Owned
libera registros al escribirlos; borrowed copia uno por vez. El store posee el
pin durante su vida útil, incluso entre préstamos de GraphIndex. Su renovación de
lectura difiere SQLITE_BUSY_SNAPSHOT sólo con lease vigente; writers conservan
renovación estricta y las expiraciones reales no se ocultan. Scans admiten
rows_checked y un scope execution instala interrupción de VM cada1000 pasos sin
mezclar política de presupuesto KQL con almacenamiento.

ProjectAcquisition toma una manifest única, serializa con flock cancelable,
reutiliza el índice READY sin volver a parsear o enlazar y actualiza omisiones y
coverage del request. Ediciones invalidan la identidad. Si falla un frontend,
publica temporalmente y deja graph_key vacío; la siguiente adquisición puede
recuperarse. El índice ejecutable no consume la cuota opcional ArtifactCache.
El lock se libera antes de la evaluación; AcquiredProject posee store y reader
por préstamo. Config/env y el API CLI/MCP de estas bibliotecas siguen pendientes.

Referencias nuevas, observadas una vez contra original1066 con autenticación
antes/después, sin reparsear ni repetir linkers aceptados:

| Recurso | Casos | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| query-graph-reference.json.gz |79 normalizaciones,16 índices,286 valores|1622826|`730db94ed79125323cfe497fbef50503b6c62f8bba0c665f25ba8cf5695554a7`|
| query-graph-original.sqlite.gz |base interoperable|880673|`d3f667dd971d0470f3a31e06f30f7c83d87ef269c67ca98ab07054c5367570a4`|
| query-source-reference.json.gz |16 vistas/coverage/witnesses|30196|`5ac2bb971e5bda46b6417b227b0fe9185a6aa89ff0edcdf7698dabd18c0a58ed`|
| query-edge-reference.json.gz |13 familias/posiciones|2014|`955a923fe182646e8f7964c59dee4a38a58be72341a3b3e74391f5b343018fa8`|

La revisión final dejó tres Important, todos corregidos en una pasada: búsqueda
cuadrática del overlay OPERATION sin índice local_id; renovación de lectores con
snapshot WAL antiguo; sintaxis final sin checkpoints/lotes. Las regresiones
nativas fallaron primero. El trabajo SQL de publicación al duplicar1500→3000
operaciones pasó de44745→179490 ticks a105→210 (100 instrucciones/tick; medición
estructural, no benchmark de tiempo). Se acotaron además capacidades/relaciones,
se verificó rollback de sintaxis legacy y se corrigió overflow del ID overlay
i64::MIN. Sin nueva revisión repetida ni replay del original.

El cierre agrupa81 raíces:30 program,15 structural,30 store/pipeline y seis
syntax/frontend. Clippy estricto y formato cubren los tres paquetes afectados.
No se ejecutaron suites de vectores/modelos ni calificaciones globales.

Próximo núcleo: compilador, operadores, sesiones y evaluación BODY de KQL1/2.
La publicación/adquisición del grafo ejecutable ya tiene implementación nativa;
no volver a listarla como trabajo ausente. M5 permanece abierto; M6 y resto de
M7/M8 también. Público271/Best247 no cambian ni constituyen recibos nuevos. Sin
replay CPU/CI/modelos; SkylakeX/Intel conserva su pendiente histórico. Crudos y
workspace de query-graph quedan locales sin seguimiento. Ver
[API](rust-migration.md#grafos-ejecutables-para-consultas) y
[plan](superpowers/plans/2026-10-29-rust-query-graph.md).

Los apartados siguientes son registros de etapas anteriores.

Actualización de construcción del 29/10: nueva biblioteca `ken-structural` para
manifest de fuente confinada, unidades reutilizables y ensamblado completo con
`ProjectBuilder::{manifest,build,build_manifest}`. `ScanLimits` conserva2MB por
archivo y ningún límite implícito de cantidad. Usa core SourceFile/ProjectSources,
syntax lower_source, program link_project y store ArtifactCache, sin modelos.
Read_bounded controla crecimiento después de stat. El reporte mantiene archivos,
omisiones, diagnósticos, resolución, coverage_complete, graph_key y caché.
Manifest es una captura de bytes; build_manifest no vuelve a leerlos. Fallos de
frontend no cachean un proyecto parcial bajo la clave completa. Omisiones actuales
se conservan incluso con hit de grafo; cancelación se comprueba tras adquirirlo y
al completar. Las entradas IR cacheadas deben coincidir en ruta/lenguaje/view.

ArtifactCache es un memo JSON-zlib opcional y portable, con claves SHA256 de
longitudes big-endian de8bytes y tabla entries compatible con Python. Retención
LRU transaccional, cuota de páginas, errores→miss y presupuestos diminutos sin
crear archivos. Bases ajenas, page_size distinto o auto_vacuum no FULL quedan
intactas/deshabilitadas; FULL admite reducción de presupuesto. No usar esta cuota
como presupuesto del índice ejecutable ni como garantía global de memoria decoded.
El constructor recibe el cache/budget explícito: la conexión de configuración/env
Python y transport público sigue pendiente junto con el ejecutor KQL.

La identidad compilada cubre src/resources de los componentes nativos, manifiestos,
Cargo.lock, toolchain, gramáticas y el Ruff parser local. Paths relativos mantienen
identidad entre raíces equivalentes; nuevos inputs invalidan. El frontend externo
posee su revisión de unidades; el linker nativo posee independientemente la clave
de proyecto: key(native-project-graph/1,IMPLEMENTATION_FINGERPRINT,original_graph_key).
Esta es la única transformación explícita en la comparación de análisis original;
no se omiten campos. Las claves de unidades y el codec entries/JSON siguen iguales.

Referencia nueva observada una vez contra el original1066 autenticado:

| Recurso | Casos | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| project-build-reference.json.gz | 11 builds,4 manifests,6 claves | 70425 | `e925a0072a30650ecc99ad275a9fc7caa3d1a84ff6e819ade4fc5eacd3ef9997` |
| original-cache.sqlite | base interoperable | 20480 | `f01935d7c0cb70d02289b7b5ad87b819278933352c967dec5327985b988651db` |

La revisión dejó cinco Important y se corrigieron en una pasada con RED→GREEN:
recursos/parser/manifiestos omitidos del fingerprint; dependencia indebida de
frontend para invalidar resultados del linker; IR cacheado con identidad ajena;
check faltante tras hit de grafo y cuota incumplible con auto_vacuum NONE.
Doce raíces nuevas cubren esas regresiones y los escenarios funcionales. El test
del fingerprint ejecuta el verdadero programa de build en árboles temporales;
no modifica recursos de producción ni ejecuta Cargo dentro del test.
El materializador semántico se consolidó con el TypeRef/parse_type público ya
existente, que pasó639casos nuevos; se eliminaron315líneas duplicadas y los79
grafos completos siguen coincidiendo. No se agregó ninguna versión externa:
Cargo.lock sólo añade el paquete local y dependencias ya fijadas.

Validación de cierre:43 raíces del alcance afectado (12 de la biblioteca nueva,
ocho program/model,16 de lectura/recorrido/filtros,una integración de fuente
y seis de snapshots), Clippy estricto y formato pasaron tras las correcciones.
No equivalen a recibos globales de búsqueda.

Próximo núcleo: índice/publicación ejecutable y compilador/operadores/sesiones
KQL1/2; luego configuración/transports de estas bibliotecas. M5 sigue abierto,
igual que M6 y resto de M7/M8. Los inventarios público271/Best247 no cambian: no
seleccionan ken-structural y este bloque no agrega raíces a los paquetes que sí
seleccionan. Sus recibos antiguos no acreditan el nuevo servicio. Sin nuevas
matrices CPU/CI/modelos ni replay de originales aceptados; SkylakeX/Intel conserva
su pendiente anterior. Crudos `.ken/rust-migration/project-build` y workspace
`.superpowers/sdd/2026-10-29-rust-project-build` quedan locales sin seguimiento.
Ver [plan](superpowers/plans/2026-10-29-rust-project-build.md) y
[API](rust-migration.md#construcción-desde-archivos-y-caché-de-ir).

Los apartados siguientes registran etapas anteriores y sus pendientes históricos.

Actualización posterior del 29/10: `ken_program::project::link_project`,
`link_project_with_check`, `link_project_owned` y
`link_project_owned_with_check` implementan el ensamblado semántico completo del
linker original. Los APIs nominales conservan su contrato. Nuevos módulos internos
`semantic` separan resúmenes/defaults/publicación, tipos, colecciones, miembros y
contratos, bindings, transferencias, inventarios y efectos; el acceso indexado al
IR posee identidad y hechos, sin policy de análisis. No hay dependencia del parser
ni runtime Python en ken-program; no se agregaron versiones de dependencias.

Orden original conservado: sequential_returns → resúmenes de retornos/argumentos →
defaults de campos → metadatos de parámetros/base dispatch/SAM Java →
ENTITY/OPERATION/HAS_OPERATION → annotation_types → CFG/contexts/normal_completion →
collection_snapshots/lifecycle → nominal_roots/member_access → structural_contracts →
eventos C# → call_bindings → field/member transfers → binding_writes → Optional Java →
concurrencia Python → resolved_allocations → explicit_write_inventory → value_contracts.
Cancelación antes de copiar y en las fronteras originales; entradas prestadas
inmutables en éxito/fallo. Transferencia evita copiar unidades desechables.

Referencias nuevas observadas una vez, con autenticación antes/después del árbol
original1066. El colector de la cola del linker conserva su AST desde la línea647
y reconstruye sólo los locales nominales desde hechos congelados:

| Recurso | Casos | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| project-semantics-reference.json.gz | 79 | 1007022 | `f50c367a4a8c2391c40a928e1dfcec0dcb3931e35b4bc17b09aa70ca3bda8479` |
| annotation-types-reference.json.gz | 639 | 159570 | `f91717f82cfebaeaeb8b947b64332169b4bc314286e90d2d4f333c6a5b454428` |
| argument-summary-reference.json | 5 | 26486 | `aca57c277d07cf8b2b4f3b071083653b755a743de642036377d75e0c7450784a` |

53 casos consumen IR nominal/orígenes ya capturados, sin repetir sus originales;
26 fuentes nuevas recorren todo el linker original y luego fuente→linker nativo→
AST→snapshot/reapertura. Los checkpoints de esos26 también coinciden. Cada proyecto
se publica por separado: todos tienen ruta IR `<project>` y no son unidades
coexistentes de un snapshot. Comparar todo el grafo y evidencia como multiconjunto
de hechos para admitir el orden de sets Python; conservar ENTITY attrs opacos y
normalizar sólo las direcciones efímeras block_scope donde ya hay identidad estable.

Correcciones halladas durante implementación: firmas compartidas Go deben tomar
su evidencia del primer owner de HAS_METHOD, no del menor ID ordenado; los hashes
de tipos usan JSON Python con espacios, keys ordenadas y ensure_ascii, incluyendo
surrogates UTF-16 para astrales.639 casos incluyen profundidad32, tamaño10000,
qualifiers/punteros/referencias, mapas/arrays/genéricos, control chars y Unicode.
Dígitos posteriores a Unicode15 cambiaban cinco resultados: source_pattern congela
ahora también clases decimal/inversa. No aumentar tolerancias ni ampliar cobertura
silenciosamente. Transferencias de campos indexan calls/receivers por owner.

La revisión final completa dejó tres Important de trabajo cuadrático: copia del
historial de writes por cada receptor, copia del set de contextos por efecto y
cruce de argumentos×parámetros con parsing repetido. Los tres se reprodujeron con
contadores de asignaciones en el API público (2000 rebinds/calls,2000 contextos,
dos llamadas de1500 argumentos:5,3M/5,4M/14,8M asignaciones) y se corrigieron en
una pasada, sin re-review. Ahora se prestan slices/sets y se indexan parámetros
por posición/nombre, preservando todas las ocurrencias duplicadas; spreads siguen
produciendo la cantidad de edges que realmente corresponde. Las cinco capturas
adicionales verifican orden completo, duplicados, spreads, bool/int/float, -0 y
enteros mayores que2^53 sin redondear por f64. Los tres casos pasan con límites
lineales generosos; un test aparte conserva RawValue de surrogates,1e400 y150
arrays anidados en metadatos de fuente, ENTITY y OPERATION, con entradas intactas.
El primer reviewer se perdió en un reinicio sin informe; la revisión completa
se recuperó una sola vez y su informe queda persistido en el workspace local.

Pasaron30 raíces de program,48 de syntax y seis de store/pipeline (84),
Clippy estricto y formato después de las correcciones. Los dos inventarios
actualizados también compilan en Python.

Siguiente núcleo pendiente: servicio build_project/source_manifest, invalidación
y cachés/publicación semántica persistente, luego compilador/operadores/sesiones
KQL1/2. Las fases del linker enumeradas arriba ya están implementadas; no volver
a listarlas como pendientes. M5 sigue abierto, al igual que M6 y resto de M7/M8.
Los inventarios futuros quedan público271/Best247 por una nueva raíz syntax;
las nuevas raíces de program no se incluyen en esos comandos. No son recibos
globales ni nueva calificación CPU/CI. SkylakeX/Intel conserva su pendiente anterior.
Crudos `.ken/rust-migration/project-semantics` y workspace
`.superpowers/sdd/2026-10-29-rust-project-semantics` quedan locales, sin seguimiento.
Ver [plan](superpowers/plans/2026-10-29-rust-project-semantics.md) y
[API/alcance](rust-migration.md#ensamblado-semántico-completo-del-proyecto).

Los apartados posteriores son el registro histórico de etapas anteriores.

Etapa grande del 29/10 (inicio13:18:19UTC): frontend local completo de nueve
lenguajes, enlace nominal del proyecto y orígenes/terminación local implementados
en un mismo bloque. `ken_syntax::structural::lower_source` es ahora el frontend
completo; `lower_operations` conserva su proyección anterior y comparte el
colector, sin duplicar reglas de ownership. Nuevos módulos separados por
responsabilidad: declaraciones, valores, llamadas, sentencias, condiciones,
inventarios y C++. `ken-program` sigue sin depender del parser/tree-sitter.

`project::link_nominal`, `_owned` y variantes `_with_check` cubren la fase exacta
del linker Python anterior a sequential_returns: merge, imports/ambigüedad,
tipos/bases, firmas C++, asignación/propagación de tipos posibles (16 pasadas),
capturas y resolución de llamadas, incluidos contratos Java estrechos auditados.
Preservar el quirk de relations: el proyecto empieza su inventario vacío y
registra sólo relaciones derivadas nuevas, sin unir las de fuente. Prefijo de
hechos de entrada exacto; hechos derivados comparados como multiconjunto completo
porque el original itera sets. Rust emite un orden determinista.
Cancelación ocurre antes de clonar unidades; las rutas mixtas abs/rel sólo fallan
cuando la resolución Rust crate realmente necesita commonpath. Atributos de
hechos no interpretados permanecen RawValue opacos, incluidos surrogates y números
fuera de f64. No volver a parsear indiscriminadamente todo el payload.

`control::sequential_returns` implementa el return_flow local completo, incluida
iteration_origins. Devuelve ReturnOrigins tipado y agrega evidencia al IR, con
límites originales32/256 y estado de campos por hash Python repr/Unicode15.
`normal_completion` agrega evidencia con cobertura parcial explícita y límite64.
La suite de integración recorre nominalIR→orígenes→CFG→contextos→terminación;
otras suites recorre bytes→nominal y bytes→AST→snapshot/reapertura. No afirmar
que el ensamblado final del linker/publicación del grafo completo esté migrado.

Capturas nuevas, observadas una vez contra el árbol congelado autenticado:

| Recurso | Casos | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| source-frontend-reference.json.gz | 88 | 318911 | `6eb76c8f73bfc3602c5d28810032d72366543184c531b8b5b936fccf7f72366f` |
| nominal-project-reference.json.gz | 41 | 423530 | `104c44a62672857cd9d0dc9c059f26703a29364be95def90fc8bce116ec5ab37` |
| local-origins-reference.json.gz | 53 | 1079881 | `0647b1a8794c317dc898439516c0339cfe7cb97f72e7d4d98be10b66d2a15730` |
| source-unicode-reference.json | 2 | 30079 | `20c129b60a71e20c455112ca1463641ae9b3a25aeb50ac2209d9789fa4051987` |
| string-properties15.json (producción) | — | 17857 | `2f3ee56b7044637f98cd6dbb15c97458bfa34655919943c067191c470cff9152` |

Los casos nominales/de flujo que parten de IR congelado no reejecutan el frontend
original. Sólo dos block_scope de JS/Go llevan Node.id/dirección efímera: se
normalizan al ID estable @block-start en la comparación, comprobando antes una
dirección positiva; producción conserva el atributo. No excluir otros atributos.

Una revisión final independiente encontró cuatro Important y dos Minor; ambos
Minor se regraduaron Important por coste cuadrático de subárboles y copias grandes
antes de cancelación. Todos corregidos en una pasada, sin re-review: valores con
máquina iterativa, texto de imports diferido, índices de declaraciones y argumentos
C++, grupos de parámetros de tipo cacheados, atributos opacos por relación y
commonpath Rust diferido. El caso profundo dejó de abortar y expuso un segundo
coste: parent() de tree-sitter busca desde la raíz. Un índice léxico construido
una vez eliminó los recorridos de ancestros por cada operando. Pasan expresiones
Python de1500 operadores,16000 campos C++ y4500 inicializadores con un plazo de10s
por proceso. Una captura adicional de dos casos expuso diferencias Python/Rust
regex en marcas combinantes; las clases de palabras/espacios y límites de palabras
relevantes usan Unicode15 congelado. No se amplían tolerancias ni se recorta sintaxis.

Pasaron 47 raíces syntax, 21 program y seis store/pipeline (74), Clippy estricto
y formato. La compilación Python de los dos inventarios también pasó. Próximos
inventarios público270/Best246 (nueve nuevas raíces syntax); program/store no se
cuentan en las suites de búsqueda. Los recibos globales anteriores no se repiten
ni acreditan el nuevo código.

Próximo trabajo core: fases posteriores de semantic.link_project (resúmenes de
retornos y binding de argumentos, campos/transferencias, dispatch y contratos,
colecciones/lifecycle y enriquecimientos de efectos/valores), luego ensamblado y
publicación/caches del grafo, compilador/operadores/sesiones KQL1/2. M6 y resto de
M7/M8 siguen abiertos. SkylakeX/Intel conserva su pendiente anterior; no repetir
matrices ni recibos globales para cerrar este bloque. Python instalado y fuentes,
crudos `.ken/rust-migration/source-frontend` y workspace `.superpowers/sdd/2026-10-29-rust-source-frontend`
siguen locales. Ver [plan](superpowers/plans/2026-10-29-rust-source-frontend.md) y
[API/alcance](rust-migration.md#frontend-completo-enlace-nominal-y-flujo-local).

Los registros siguientes describen etapas anteriores; sus pendientes y contadores
son históricos cuando la actualización anterior los sustituye.

Actualización de fuente del 29/10: `ken_syntax::structural::lower_operations`
produce el IR de operaciones desde bytes/GrammarCatalog para los nueve lenguajes
estructurales. Ownership separado, visita de tipos antes de usos, Rust impl y
receptores Go, prototipos C++ frente a callbacks/definiciones cualificadas,
clases expresiones/nested/closures, IDs/spans, roles, tokens, operadores/operandos,
async/delegación/descartes Rust y modificadores Ruby. La ejecución léxica usa el
kernel ya migrado; errores de parseo conservan sintaxis y estado unknown.
El adapter depende de ken-program; el dominio no depende de tree-sitter.
Contrato deliberado de etapa: entidades propietarias con identidad/coordenadas y
capability `syntax` solamente. No son metadatos completos de declaraciones ni
hechos semánticos de llamadas/tipos; no exponer esto como `lower_source` completo.
El CFG/normalizador/store consume esta salida explícita, sin prometer análisis
semántico completo. La siguiente etapa debe conservar los bindings/declaraciones
antes de ofrecer las garantías de cierre del frontend o linker.
42 casos originales nuevos: referencia de 72.907 bytes, SHA-256
`ad1ff86907c7ab717fe00c2d7e2db8996aa2ba9691da076f7512efd48e51cfbc`.
Vocabulario de producción de 3.460 bytes, SHA-256
`c6c73c28ae52496baf2f118e149c817703b90975ea38d073accdf0ea39d89ab0`,
extraído de los literales del original congelado y autenticado por su fuente.
Una revisión encontró parámetros que afectan ownership de un impl Rust y lookup
cuadrático de roles. Ambos se reprodujeron RED→GREEN en una pasada: una única
observación adicional original (no los 42 aceptados), de 1.909 bytes, SHA-256
`f72b663a53a4faf339f2939530a4c9b56af84a556aa810a55a6433d3f373d63a`,
y 20.000 sentencias con presupuesto de proceso generoso de10s. El recorrido
transporta roles desde un cursor por padre; el mapa de nombres conserva los
parámetros Rust relevantes para ownership. Sin re-review ni hallazgos pendientes.
Pasaron 38 pruebas syntax, 12 program y seis store/pipeline (56), Clippy estricto
y formato. Integración source→CFG/contexts→AST→snapshot/reapertura sin Python.
Una compilación Python de los dos inventarios actualizados también pasó.
Próximos inventarios público261/Best237 (seis raíces syntax nuevas sí se incluyen
en sus comandos); esto no representa nuevos recibos globales ni matrices CPU/CI.
Los contadores anteriores son históricos. Ningún original aceptado fue repetido;
crudos y workspaces siguen locales, sin seguimiento. M5/M6/resto de M7/M8 abiertos.
Ver [plan](superpowers/plans/2026-10-29-rust-source-operations.md) y
[API/alcance](rust-migration.md#núcleo-estructural-operaciones-desde-fuente).

Actualización de control del 29/10: `ken_program::control` implementa sobre IR
suministrado los kernels `lexical_execution`, `structured_control` y
`syntax_contexts`. Índices de operaciones separan parentesco léxico de ownership;
`CompletionRoutes` posee continuaciones, scopes de finalizador y retornos pendientes.
Preserva ramas/bucles/else, do/for/range, break/continue, hoisting JS/TS, resultado
descartado/await/tails Rust, excepciones/finally/except* Python, invalidación de
aliases y puntos de suspensión. Los hechos mantienen orden original y cobertura
parcial explícita; ninguna continuación se convierte en operación sintáctica.
No son pruebas de viabilidad runtime ni un frontal completo desde archivos.
Usa Ruff parser/AST y normalización Unicode ya fijados, sin nuevas versiones;
el recurso de excepciones Python3.12.9 deriva una sola vez del original.
Captura esencial: 88.797 bytes, SHA-256
`5fdbec695fd653bb31a6a737b2a9a57230c99035f616bdcbd1e8e26ffc8c090a`.
Tabla de producción: 12.630 bytes, SHA-256
`aadc7e2be8f377e114bb7d69ecf90e492a8f6ac33716973027010926d23353c6`.
23 casos nuevos de nueve lenguajes: 69 comparaciones exactas por etapas más
roundtrip integrado del IR enriquecido por snapshots persistentes. No se
repitieron originales ni se ejecutaron modelos, matrices CPU o nuevas CI.
Pasaron 12 pruebas de ken-program y seis del store/pipeline, Clippy estricto y
formato. Una revisión estática final encontró rangos CALL null que abortaban los
contextos y la retención del índice temporal de llamadas. El primero se reprodujo
RED→GREEN y cubre también números equivalentes y offsets no numéricos; el segundo
se liberó antes del mapa de ancestros. Sin re-review. Los errores iniciales de
compilación del nuevo test de integración y dos lints se corrigieron antes del
gate final, sin cambiar referencias.
Ver [plan](superpowers/plans/2026-10-29-rust-control-core.md) y
[API/alcance](rust-migration.md#núcleo-estructural-rutas-de-control).
Los contadores de búsqueda público255/BestSearch231 no cambian: sus comandos
excluyen ken-program/ken-store. Las cinco raíces nuevas de control/pipeline se
validan en el alcance M5; no se acreditan mediante los recibos de búsqueda.
Siguiente núcleo pendiente: productor IR/declaraciones/linker semántico desde
archivos, publicación del grafo, valores/efectos y compilador/ejecutor KQL1/2.
M5a/M5b/M5c siguen abiertos; M6 y resto de M7/M8 también.

Actualización del núcleo del 29/10: empezó M5a de adentro hacia afuera, por pedido
expreso del usuario. `ken_store::structural::StructuralStore` implementa la base
de persistencia que consumirá KQL: migraciones exactas 1–15, ownership/DDL/checksums,
unidades IR, propiedades tipadas, proyección de operaciones y AST, snapshots con
publicación CAS y scans en streaming siempre ligados a pertenencia. Incluye
leases/renovación durante cursores, conservación de adquisiciones activas, GC
conservador y fallback de proyecciones al exceder retención. Reutiliza el modelo
común/normalizador existente; no es un nuevo frontend ni un ejecutor KQL.
El nuevo namespace queda separado de ProjectDatabase/vectores y no añade tools.
Referencia esencial: 34.619 bytes, SHA-256
`e7d887858d27db2395fc141011ff7a52baa33001499250b2bdf31e916ab36751`.
El recurso SQL/layout de producción deriva una vez del original congelado:
51.953 bytes, SHA-256
`f5b49cc8a224d7758ea290a155916a0b45499c960f6659f5781a6403f08e5dbb`.
Se observaron por primera vez las 15 versiones/up/down y tres unidades con sus
AST/operaciones/propiedades/snapshots, preservando también una base original
sintética. No se repitieron observaciones aceptadas ni se ejecutaron modelos.
Pasaron cinco raíces nuevas del store y ocho de ken-program, Clippy estricto y
formato. La suite histórica amplia se detuvo en maintenance por faltar
KEN_RUST_REFERENCE antes de ejecutar su observador Python: no se habilitó esa
variable para repetir originales de vectores ya aceptados. Los tests nuevos no
ejecutan Python. Los recibos anteriores de vectores conservan su alcance.
Una revisión encontró la aceptación de bases ajenas con sólo vistas (heredada de
Python): se rechazó expresamente con RED→GREEN y comprobación de bytes intactos.
La reconstrucción cuadrática de entidades se regraduó Important para unidades
grandes y se indexó por ID; lo mismo en el codec IR ya existente, conservando su
orden y último reemplazo. Se validó con 7.500 entidades y operaciones repetidas.
La renovación usa estado interior mínimo para permitir heartbeat con un cursor
vivo; su regresión pasó. No hubo re-review ni nuevos ciclos CPU/CI/archivos.
Ver [plan](superpowers/plans/2026-10-28-rust-structural-store.md) y
[API/alcance](rust-migration.md#núcleo-estructural-almacén-de-snapshots).
Los contadores de búsqueda público255/BestSearch231 no cambian: sus comandos
no seleccionan ken-store. Las cinco raíces estructurales se validan aparte y
deberán formar parte del gate M5; no acreditarlas mediante los recibos M4/M7.
Siguen pendientes el productor IR desde archivos, el grafo/publicación semántica, los caches
de artefactos y la ejecución KQL1/2; M5a/M5b/M5c no están cerrados.

Actualización de codeflow del 28/10: señales estructurales de llamadas, bases y
wiring migradas en `ken-syntax`; resolución de símbolos, tiers, enclosing spans,
jerarquía y overrides en `ken-search/navigation/codeflow`. CLI/MCP añaden
`ken_related` callers/callees/subtypes/supertypes y `ken_find(scope="wiring")`.
Comparten un propietario diferido de gramáticas, sin modelos; `--resources`
admite un manifest mínimo con format y grammar_manifest. La preparación de
modelos sigue separada y su lector completo conserva la validación anterior.
Referencia esencial 3.413 bytes, SHA-256
`b5586fe9eae7915b49c44f8da201deda952aaa8bf6e87911882fa83028055969`:
19 señales, 26 consultas de dominio y 10 respuestas públicas capturadas una sola
vez, sin indexación/modelos originales. Todas coinciden en datos/texto. Pasaron
33 raíces nativas del alcance y Clippy estricto; revisión sin hallazgos.
Una aserción local adicional omitía descendientes Java/Dart del mismo nombre;
se corrigió esa expectativa, sin cambiar código de producción ni referencias.
Preservar los quirks originales observados: confianza numérica pública usa T2;
subtypes/supertypes envían down/up y ambas devuelven descendientes sin overrides.
La biblioteca sí ofrece direcciones sub/super y umbrales string T1/T2. No corregir
esas inconsistencias silenciosamente dentro de la migración. Los sources siguen
confinados al proyecto y una sesión observa ediciones actuales sin caché de AST.
Ver [plan](superpowers/plans/2026-10-28-rust-live-codeflow.md) y
[uso](rust-migration.md#exploración-nativa-del-código-vivo).
Próximos inventarios de calificación: público255, BestSearch231. No equivalen a
calificación global nueva; IR/CFG/KQL de M5, memoria de M6 y resto de M7/M8 siguen
pendientes. Fuentes originales, crudos y workspaces permanecen localmente.

Actualización de orientación del 28/10: `ken_rank` migra scopes `project`,
`architecture` y `changes` por CLI tools y MCP, sin modelos. Algoritmos iterativos
de SCC/capas, comunidades, PageRank y calidad conservan cobertura y muestras
acotadas. Git tiene plazo de cinco segundos, drenaje concurrente y cierre del
grupo de procesos en Unix; los cambios conservan símbolos indexados de archivos
borrados y las peculiaridades originales de porcelain v1. `session` queda
explícitamente pendiente, con su default MCP original; CLI rank default project.
Pasaron 31 raíces nativas del alcance y Clippy estricto en una validación conjunta;
revisión independiente sin hallazgos. No se repitieron matrices CPU/CI/archivos.
Referencia esencial 24.430 bytes, SHA-256
`c6813356a1dfaeb9a9bcc19700a47cadfec8f6f18bf46d45ecb43b6ac4ef51c7`:
24 informes de dominio y 20 públicos, más regresiones de ciclo12.000 y procesos.
La primera preparación falló antes de consultas por FK; la segunda conservó sus
42 registros aceptados antes de fallar en el setup Git por una ruta inexistente.
Se observaron sólo las dos consultas Git pendientes y se selló todo sin repetir
los 42 originales. Intentos, journals y comandos permanecen locales.
Ver [plan](superpowers/plans/2026-10-28-rust-project-orientation.md) y
[uso](rust-migration.md#orientación-nativa-del-proyecto).
No son nuevos recibos globales. Se instaló y aplicó deprecation-and-migration de
addyosmani/agent-skills (~111k estrellas observadas), fuera del repositorio;
sus pasos de retirar fuentes/cutover siguen subordinados a la autorización
vigente de preservar Python hasta completar la migración.

Actualización de perfiles del 28/10: `IndexNavigation.profile` migra los perfiles
de responsabilidad de archivos y paquetes; `ken_read(include=["profile"])`
completa los cinco includes del original por CLI/MCP, sin modelos ni escrituras.
Dieciséis casos de biblioteca y cinco respuestas públicas conservan datos y
texto, salvo el orden explícitamente indeterminado de un par con exactamente
iguales frecuencias/scores. Se conserva la captura original intacta y se demuestra
la igualdad antes de permitir ese único intercambio en la comparación. Pasaron
nueve raíces nativas del alcance y Clippy estricto; revisión sin nuevos hallazgos.
Referencia esencial 1.579 bytes, SHA-256
`947062689930f5f7c0404fdec13b2d9d07a22fc36a9eaf160e6e1825e04b12ea`.
Ver [plan](superpowers/plans/2026-10-28-rust-responsibility-profile.md).
No representan una nueva calificación global. Paquetes sólo por API de biblioteca;
el include público conserva el perfil de archivo del original.

Actualización de texto del 28/10: `WorktreeTextSearch` implementa búsqueda literal
en fuente actual y BM25 con espejo FTS incremental/atómico. CLI `tools find` y
MCP `ken_find(scope="text")` comparten el servicio, filtros por lenguaje y
JSON/texto/legacy sin cargar modelos. Las 29 nuevas observaciones originales
coinciden en biblioteca y procesos CLI/MCP, incluyendo edición, borrado y retiro
del índice. Pasaron 25 raíces nativas locales del alcance afectado y Clippy
estricto. Una prueba antigua que esperaba text no soportado se actualizó a wiring;
la revisión también corrigió la validación de formato antes de mutar el espejo.
Referencia esencial: 1.949 bytes, SHA-256
`75a95de020973bcaba8e06a1e2eeeffb5c85e28768a35649d5a1c8798f580396`.
Ver [plan](superpowers/plans/2026-10-28-rust-worktree-text.md) y
[uso](rust-migration.md#búsqueda-nativa-de-texto). Crudos/workspace locales sin
seguimiento. Esto no cambia recibos históricos ni cierra la matriz pendiente.

Actualización de navegación del 28/10: implementado un bloque completo de lectura
del índice con `IndexNavigation`, documentos ordenados y presentación compacta.
CLI `tools read/related/find` y MCP `ken_read`, `ken_related` y `ken_find` con
`scope="tests"` comparten el mismo servicio. Incluye símbolos, outlines, detalles,
snippets, grafos de imports, vecinos y asociación de tests; el resumen del proyecto
está disponible como API de biblioteca. No necesita instalación de modelos.
Pasaron 23 raíces nativas locales y Clippy estricto; 49 casos de dominio y 19
respuestas públicas nuevas del original conservan JSON/texto. La revisión final
corrigió la distinción texto/JSON de `tools --compact find --response-format compact`
y la lectura de todos los archivos en grafos pequeños (ahora sólo consulta IDs
seleccionados). Cada llamada pública abre una vista nueva; la instancia de
biblioteca conserva un snapshot de lectura. Perfiles de archivo, otras relaciones,
otros esquemas de presentación y calificación global quedan para sus bloques.
Ver [plan](superpowers/plans/2026-10-28-rust-index-navigation.md) y
[uso](rust-migration.md#navegación-nativa-del-índice). Referencia comprimida esencial:
4.580 bytes, SHA-256 `5d8140a9c79d558412201aa1f22d6bd2b207b6dacefe5ad47ce7a4c2f62fbae3`.
El resto de los originales, logs y workspace se conservan localmente, sin seguimiento.

Actualización posterior del 28/10: `ken-rs search-files`, `search-symbols` y
`mcp` ya tienen implementación nativa para la búsqueda por defecto/compacta en
Linux x86_64. Comparten `SearchApplication`, recursos explícitos y carga diferida
de los modelos. Las pruebas de procesos verifican CLI, sesiones MCP, recuperación
de errores y reemplazo de la base durante una sesión. La calificación con copias
fuera del checkout está en curso; esto no cierra M4 ni el MCP completo de M7.
`evidence`/`legacy` se rechazan explícitamente hasta migrar su orquestación.
CT2 x86 tiene implementación CPU y validación local AMD; siguen pendientes las
observaciones originales Intel/MKL y su matriz de aceptación.

Estado del código público `ccfcdb7e`: pasan localmente 239 raíces Rust y 21 de
herramientas, formato y Clippy estricto. La copia fuera del checkout pasa 11
pruebas con 30 procesos CLI/MCP; conserva entradas, salidas, carga de bibliotecas
y parentesco de procesos. El replay aislado con sus validadores archivados pasa.
Archivo local de fuentes: 21.403.196 bytes, SHA-256
`ef46ee75697905ea3fa60a1113a37f038a0fde5b8b00439c8e53a2220b059c62`.
La revisión independiente detectó y se corrigió la diferencia entre consultas
Unicode literales y escapadas en MCP, conservando los sustitutos aislados.
Queda diferida una mejora menor: el error de instalación debe indicar cómo
reparar el manifest nativo, en lugar de sugerir sólo preparar modelos/índice.
La matriz pública final (CI `40784047558`) no está aceptada: ambas réplicas pasan
10 pruebas y difieren en el `piece_score` de una composición registrada:
`-2.3249518584644573` frente a `-2.3288574266118545`. Es el desacuerdo ya observado
en la investigación de SkylakeX; falta contrastar su original por perfil. Una
réplica del código anterior sí pasó. No relajar scores, reutilizar ese recibo para
fuentes nuevas ni marcar este bloque como aceptado hasta completar los contrastes.

Actualización del 28/10: `BestSearch` y la preparación contextual están implementados
como biblioteca. La cadena completa pasa localmente y en una réplica CI Haswell;
la réplica SkylakeX presenta una diferencia numérica pendiente de contraste con
el original sobre ese mismo perfil. Este bloque todavía no está aceptado.
`PieceSearch` conserva su aceptación anterior; otros modelos, M4/global y M5–M8
siguen pendientes. El diagnóstico actual está al final del documento.

Actualización del 24/10: los directorios de evidencia se retiraron del seguimiento
de Git por pedido del usuario; sus archivos locales se conservaron. Para un clon
nuevo, [recuperar los artefactos necesarios](validation-artifacts.md) antes de
ejecutar la reconstrucción siguiente. La cápsula ya no viaja en el árbol actual.
El usuario autorizó continuar la migración y agregar Linux x86_64; los recibos
ARM históricos conservan su alcance y no certifican esta nueva arquitectura.

Traspaso del 23 de octubre de 2026. Rama: `codex/rust-migration`.
Punto histórico del traspaso: `5d9dc6f927098f47942d5c0dd5ee72ca22853c4a`.
Cierre M4c2 del 24/10: `3e4a4e4ccd6762f437af43f618e8631984e67b39`;
ver el recibo y la identidad de archivo al final de este documento.
**La migración completa todavía no está terminada.** La aplicación instalada sigue
siendo Python; `ken-rs` no sustituye todavía todos sus comandos.

La parada solicitada el 23/10 quedó superada por la orden de continuar del 24/10.
El usuario autorizó los push a esta rama y el soporte Linux x86_64. Continuar
por M4d, sin reiniciar M0/M1 ni repetir originales aceptados. Conservar fuentes,
recibos y archivos locales; comprobar cada bloque y subir commits periódicos.
Esta autorización no incluye merge, release, tags ni reemplazar el Ken instalado.

## 1. Autoridad y lectura inicial

1. Este documento fija el punto exacto de reanudación y los problemas conocidos.
2. [Contrato global aprobado](superpowers/specs/2026-10-18-rust-migration-design.md):
   capacidades, persistencia, calidad, retirada de originales y condiciones M0–M8.
   Sus párrafos históricos de estado no sustituyen los recibos posteriores.
3. [Especificación M4c2](superpowers/specs/2026-10-23-rust-source-pieces-design.md)
   y [plan ejecutable M4c2](superpowers/plans/2026-10-23-rust-source-pieces.md).
4. [Ledger preservado](validation/rust-migration-2026-10-23/handoff/LEDGER.md)
   y `progress.md` dentro de la cápsula: tareas realmente ejecutadas, RED/GREEN,
   decisiones, intentos inválidos y límites. Las casillas del plan no son recibos.
5. [Guía de construcción y perfiles](rust-migration.md), `AGENTS.md` y
   `CONSTRAINTS.md`. Diseñar desde el uso público, conceptos y responsabilidades.

Los enlaces de este documento son relativos al repositorio para funcionar al
cambiar de máquina. No dependen del historial del chat ni de memoria local de Ken.

## 2. Qué está terminado y qué falta

| Bloque | Estado real | Evidencia / próximo resultado requerido |
| --- | --- | --- |
| M0/M1 | Aceptados | Referencia, contratos, proyecto, paths y `status`; matriz Linux/macOS en `docs/validation/rust-migration-2026-10-18/m1/` |
| M2 | Aceptado | Datos, modelos, backends opcionales e integración; recibo `m2-integration-review` del 23/10 |
| M3 | Aceptado | Fuentes, 19 parsers / 20 gramáticas / 44 extensiones, imports, modelo común e indexación incremental; recibo `m3-index-review` |
| M4a | Aceptado | BM25F/SQL, búsqueda densa y fusión; `m4-kernels-review` |
| M4b | Aceptado | Intención, selección, propietarios, vistas contextuales y ranking de entidades/pasajes; `m4-selection-review` |
| M4c1 | Aceptado | Bosques, stemming, alineamiento, features y ranking numérico de propietarios; `m4-numeric-owner` |
| M4c2 | Aceptado tras una revisión y una pasada de corrección | Catálogo, piezas, ranking, cards, evidencia y presentación; 446 observaciones por ARM, 126/125 raíces Rust y 174 de tooling; recibo `m4-source-pieces` |
| Gramáticas Linux x86_64 | Aceptadas; requisito local de M4d | 33 raíces Rust/doc, 87 de tooling y 249 comparaciones en tres hosts; no equivale a aceptación completa de indexación/modelos x86 |
| Runtimes CPU Linux x86_64 | Aceptados | ONNX/Torch autenticados; 6 raíces ONNX/protocolo, 15/16 Torch y 364 de tooling por host en tres hosts; modelos e índice completos x86 siguen pendientes |
| Búsqueda por piezas Linux x86_64 | PieceSearch aceptado | 45 observaciones originales, 3 frames Ettin reales; cadena completa local y dos réplicas CI, 586 pruebas de herramientas y 206 nativas por host; replay aislado |
| M4d | En curso: BestSearch, preparación contextual y expansión CT2 x86 implementados; aceptación pendiente | Cadena local y CI Haswell pasan; contrastar SkylakeX con su original y completar Intel/MKL. Quedan modos de compatibilidad, modelos/canales y calidad global |
| Búsqueda pública por defecto x86_64 | CLI y MCP stdio implementados; calificación en curso | Manifest de instalación reubicable, recursos diferidos, texto/JSON y sesiones recuperables. MCP negocia el protocolo 2025-11-25; otros scopes/modos y el protocolo moderno quedan pendientes |
| M5a | Implementación en biblioteca; calificación M5 pendiente | Productor IR/CFG, ensamblado semántico, builder/caché y publicación/adquisición QueryView/GraphIndex nativos; integración y recibos globales pendientes |
| M5b/M5c | Parcial: frontend, preparación y ambos compiladores KQL2 implementados | Quedan KQL1, operadores, sesiones, evaluación BODY, flujo/completitud e integración pública |
| M6 | Pendiente | Conocimiento, memoria justificada, anchors, vigencia, entrega, razonamiento, checks, inspection y responsabilidad |
| M7 | Parcial: navegación/perfiles, literal/BM25, orientación y llamadas/tipos/wiring por CLI/MCP implementadas | Quedan ranking de sesión, otras relaciones, daemon, colas, watcher, lifecycle, concurrencia, CLI restante, MCP completo, hooks e integración con hosts |
| M8 | Pendiente | Distribución, matriz global, upgrade/rollback y promoción nativa sin Python |

No hay un porcentaje funcional global acreditado. M3 incluye el modelo común,
pero **no** acredita la ejecución KQL de M5. El productor IR ya tiene implementación
en biblioteca; su aceptación integrada pertenece a M5.
Ningún bloque numérico o probe interno acredita por sí solo la búsqueda pública.

Los recibos siguientes están bajo `docs/validation/rust-migration-2026-10-23/`:

| Recibo | SHA-256 de `FILES.json` |
| --- | --- |
| `m2-integration-review` | `293f1de6f3865a8f5c6c4ab489e804b77adaa18863599ef0d044741594ee76bb` |
| `m3-source-review` | `3a9448aa7489e9c9a99bbf80b6e70e0ed61f1beaf063208f4944443b0340caa9` |
| `m3-parsers-review` | `c1541177be2a0716ff52276d7cfe042ae4ff5acea75d3f4c90d4a3452ab48ff8` |
| `m3-imports-review` | `3779ac933aacc766c9372b8e623c4314bd5b65a31bb65735177ba2fa7aa6db6f` |
| `m3-program-review` | `20737c5dced1e23df625b2a1c1220536c0f9b9bdb38354b51094daf6bdc0f461` |
| `m3-index-review` | `5216c937b4537dd940f3d43c71181e7ce44c4b2987b53d6e6d2699877f7414a9` |
| `m4-kernels-review` | `b7143128a6959650bb4bc28d0b94c21e3a12d061627ecdfc40d81745762f644e` |
| `m4-selection-review` | `502522eb0af6e3136be30114c5509314593785e94604ff1c70303f721a33a10b` |
| `m4-numeric-owner` | `9058d60199da6ef080991203bf0b6351361a5c27c2d5e6358bf31c3f3e4d1a6e` |

Usar sus snapshots `native-sources`/validation para reproducir recibos históricos:
no atribuir resultados viejos a fuentes nuevas. Revisar sus `MINORS`, `RULINGS`,
`FIXES` y `REVIEW`; los menores diferidos siguen siendo límites, no correcciones
implícitas. M4c1 pasó por host 80 raíces Rust, 92 de tooling, 35 raíces originales,
861 observaciones nuevas y 758 observaciones de selección reejecutadas en Rust.
Sus tres Important fueron reparados; M4/global siguen falsos en ese recibo.

## 3. Trasladar el trabajo sin depender de esta máquina

```sh
git clone --branch codex/rust-migration https://github.com/Infinibay/ken.git
cd ken
git status --short --branch
```

Usar un clon completo; los objetos del commit inicial
`96a9d2d5ed5b7a6dc51b13c8e97e290cae7c9908` reconstruyen la parte inalterada
de la referencia. En un clon superficial, obtener antes ese historial.

### Cápsula local recuperable del historial

En `docs/validation/rust-migration-2026-10-23/handoff/`:

- `PORTABLE.json`: inventario de los 1.066 originales, objetos Git reutilizables,
  hashes, 102 archivos de progreso y tamaños/hashes de los dos archivos comprimidos.
- `original-overrides.tar.gz`: 75 contenidos originales que no se reconstruyen
  desde aquel commit inicial. Son un **fixture aislado del oráculo**, necesario
  porque el punto de partida incluía cambios previos y archivos sin commit.
  No se añadieron esos cambios al código Python de la rama ni se incluyeron otros
  directorios privados, bases, credenciales, entornos o cachés del usuario.
- `m4c2-progress.tar.gz`: capturas originales, JUnit, stdout/stderr, salidas RED/
  GREEN, gates, generadores y ledger; incluye intentos fallidos para auditoría.
- `oracle-environment.json`: versiones observadas del entorno de desarrollo.
  No es una instrucción de instalar todos los backends ni una dependencia runtime.

Hashes de los comprimidos:

```text
original-overrides.tar.gz  61d0c66498e731b66f0600f97f9a54a2c404a694867a4be1eed6597182ca6788
m4c2-progress.tar.gz       9148bec5dffb12d4809c31e3b457aa385ecbb57dc0cee5aea44112b08b66a328
```

### Reconstruir oráculo y progreso

Ejecutar desde la raíz del clon, con Python 3.12.9 disponible. El siguiente código
usa sólo la biblioteca estándar y Git. No modifica los originales del worktree.
Se niega a sobrescribir un destino ya existente. Los paths absolutos de capturas
históricas se conservan como evidencia; no hay que editarlos ni volver a sellarlos.

```sh
python3.12 - <<'PY'
from pathlib import Path
import hashlib, io, json, subprocess, sys, tarfile

root = Path.cwd()
capsule = root / 'docs/validation/rust-migration-2026-10-23/handoff'
manifest = json.loads((capsule / 'PORTABLE.json').read_bytes())
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
assert sha((root / manifest['baseline']['path']).read_bytes()) == manifest['baseline']['sha256']
archives = {}
for name, expected in manifest['archives'].items():
    raw = (capsule / name).read_bytes()
    assert len(raw) == expected['bytes'] and sha(raw) == expected['sha256'], name
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        entries = archive.getmembers()
        assert all(e.isfile() and not Path(e.name).is_absolute() and '..' not in Path(e.name).parts for e in entries)
        assert len({e.name for e in entries}) == len(entries)
        archives[name] = {e.name: archive.extractfile(e).read() for e in entries}
overrides = archives['original-overrides.tar.gz']
assert set(overrides) == set(manifest['override_files'])
reference = root / '.ken/rust-migration/portable-reference'
progress = root / manifest['sdd_root']
assert not reference.exists() and not progress.exists(), 'Use new destinations; preserve existing evidence'
records = []
for row in manifest['reference_files']:
    name = row['path']
    raw = (subprocess.check_output(['git', 'cat-file', 'blob', row['git_blob']], cwd=root)
           if row['git_blob'] else overrides[name])
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256'], name
    target = reference / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    records.append({'path': name, 'sha256': row['sha256']})
fingerprint = sha(json.dumps(records, sort_keys=True).encode())
assert fingerprint == manifest['portable_reference_fingerprint']
reference_manifest = dict(format='ken-rust-oracle/1', scope=['src/ken/**'],
                          fingerprint=fingerprint, python=str(Path(sys.executable).absolute()), files=records)
(reference / 'reference-manifest.json').write_text(json.dumps(reference_manifest, indent=2) + '\n')
saved = archives['m4c2-progress.tar.gz']
assert set(saved) == {r['path'] for r in manifest['sdd_files']}
for row in manifest['sdd_files']:
    raw = saved[row['path']]
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256'], row['path']
    target = progress / row['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
print('Restored', len(records), 'originals and', len(saved), 'progress files')
print('Reference:', reference)
PY
```

La referencia portátil contiene exactamente los originales del baseline; omite
antiguos archivos Rust e informes adicionales del freeze local de 616 MiB. Por eso
su fingerprint `5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038`
es distinto del freeze histórico `4077b9be320c25375e7716221298ee85d984bcff5064cca68a2ae3af0e8cda3d`.
Cada uno de los 1.066 contenidos y todos los owners usados por el observador
mantienen su hash. No modificar fingerprints de recibos históricos para ocultar
esta distinción. Las capturas nuevas deben declarar la referencia portátil.

### Recuperar el baseline en un clon nuevo para los gates futuros

Los gates actuales comprueban los 1.066 originales también en el worktree del
candidato. El clon Git, por sí solo, carece de los cambios previos del baseline.
**Sólo en un clon recién creado y limpio**, ejecutar esta restauración explícita:

```sh
python3.12 - <<'PY'
from pathlib import Path
import hashlib, json, subprocess
root = Path.cwd()
assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal']), 'Requires a fresh clean clone'
reference = root / '.ken/rust-migration/portable-reference'
manifest = json.loads((reference / 'reference-manifest.json').read_bytes())
for row in manifest['files']:
    raw = (reference / row['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row['sha256']
    target = root / row['path']
    if not target.exists() or target.read_bytes() != raw:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
print('Original baseline restored; keep these prior changes out of migration commits')
PY
```

Ese paso deja cambios previos y archivos originales sin commit, deliberadamente.
No usar `git add .`, reset, stash global ni clean sobre ellos. En esta máquina
esos originales ya estaban presentes y **no** se ejecutó dicha restauración.
Otros cambios del usuario ajenos al baseline no forman parte de esta cápsula:
si se necesitan fuera de la migración, trasladarlos por separado.

## 4. Preparar la máquina de desarrollo

Plataformas acreditadas: **macOS arm64 y Linux aarch64**. Otra arquitectura necesita
su propia preparación y evidencia; no hereda la aceptación numérica/ABI.

```sh
rustup toolchain install 1.95.0 --profile minimal --component rustfmt --component clippy
uv python install 3.12.9 --no-bin
uv sync --locked --dev --python 3.12.9 --managed-python
export CARGO_INCREMENTAL=0
export CARGO_BUILD_JOBS=2
export CMAKE_PARALLEL=2
export CARGO_PROFILE_DEV_DEBUG=0
export CARGO_PROFILE_TEST_DEBUG=0
export RUST_TEST_THREADS=1
export KEN_RUST_REFERENCE="$PWD/.ken/rust-migration/portable-reference"
```

Actualizar sólo el campo `python` de la referencia portátil a la ruta absoluta de
`.venv/bin/python`; ese campo es un ejecutable de desarrollo, no un contenido
original:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import json, sys
assert sys.version_info[:3] == (3, 12, 9), sys.version
path = Path('.ken/rust-migration/portable-reference/reference-manifest.json')
value = json.loads(path.read_bytes())
value['python'] = str(Path(sys.executable).absolute())
path.write_text(json.dumps(value, indent=2) + '\n')
PY
```

Comprobar Python 3.12.9, Unicode 15.0.0, SQLite 3.47.1, NumPy 2.4.4,
tree-sitter 0.25.2, tree-sitter-language-pack 1.8.1 y snowballstemmer 3.0.1.
Si el entorno resuelto difiere, usar las versiones registradas y conservar la
diferencia; no regenerar los oráculos para acomodar una actualización.

La preparación reproducible extensa está escrita en
`.github/actions/prepare-native-validation/action.yml`,
`tools/rust_migration/{preparation,transformer_prepare,grammar_prepare}.py`
y la [guía de perfiles](rust-migration.md). Adaptar `GITHUB_ENV` a exports locales
al ejecutar los bloques de la acción fuera de CI. Preparar herramientas/recursos
no obliga a repetir la inferencia de todos los modelos aceptados.

- C/C++/CMake 3.31.10; en Linux build-essential, pkg-config, zstd y strace.
  La compilación de dependencias de `ken-models` puede necesitar CT2/OpenBLAS
  aunque sólo se ejecute `ken-retrieval`. Seguir la preparación registrada;
  `--offline` funciona **después** de `cargo fetch --locked` y de preparar assets.
- Gramáticas: `crates/ken-syntax/grammars.lock.json` fija archivos, licencias,
  bundles por plataforma y hashes. `prepare_grammars(lock, cache, destination)`
  prepara el SDK. Para los observadores existentes el destino es
  `.ken/rust-migration/m3-parsers/sdk-macos` o `sdk-linux` con `manifest.json`.
  El original de ensamblado necesita configurar explícitamente el CPP de ese
  SDK: el HOME aislado no dispone del caché global del language-pack.
- macOS usa Accelerate para los kernels de alineamiento; Linux usa los sidecars
  exactos del registro de BLAS de recuperación, con `KEN_DENSE_BLAS_DIR` absoluto.
  Ver `crates/ken-retrieval/src/dense_math.rs` y
  `tools/rust_migration/retrieval_validate.py::prepare_runtime`.
  Ese OpenBLAS ILP64 de NumPy **no** es el OpenBLAS LP64 de CT2.
- Los pesos/catálogos/cores de M2 se adquieren con revisiones y hashes registrados.
  Configurar los `KEN_*` de la guía antes de la suite workspace completa. No
  descargar todos los modelos para empezar la Task 3: usa el NPZ y los bosques
  ya versionados; ejecutar sólo las suites afectadas hasta necesitar más perfiles.
- No hay que trasladar `target`, `.venv`, todo `.ken`, Cargo cache ni Docker.
  Son reconstruibles; los binarios/librerías son específicos del host. Mantener
  los recibos y originales; limpiar sólo scratch propio ya archivado y targets
  regenerables cuando no haya compilaciones activas.

Las rutas locales antiguas sirven para localizar recursos si esta máquina sigue
disponible, pero **no son requisito de reanudación**:

```text
macOS wrapper: .ken/rust-migration/m2-optional/review-repair/prepared-macos-env
macOS target:  .ken/rust-migration/m2-fastembed/target-final-ci
macOS Cargo:   .ken/rust-migration/m2-translation/cargo-home
Docker:        codex-ken-rust-m2, Linux aarch64, 2 CPU / 6 GiB
Docker source: /app/.ken/rust-migration/m2-optional/source-transformers-review-work
Docker wrapper:/app/.ken/rust-migration/m2-optional/review-repair/prepared-linux-env
Docker Python: /app/.venv/bin/python
```

Los wrappers antiguos contienen paths absolutos de `/Users/andres` o `/app`:
recrearlos con las rutas nuevas, no ejecutarlos ciegamente. No editar Rust mientras
algún host ejecuta cargo/clippy. Para sincronizar fuentes, copiar sólo contenidos
cambiados; usar `tarfile` de Python, evitando archivos AppleDouble de tar macOS.

## 5. Punto exacto de reanudación: gates ARM de Task 3, luego Task 4

### Actualización del 24 de octubre

Se implementaron `piece_features.rs`, `piece_ranking.rs` y `tests/piece_ranking.rs`.
En x86_64 se capturaron una vez los 84 inputs originales y sus nueve raíces de
ranking, y 14 inputs adicionales disjuntos reutilizaron esas raíces: límites de
términos, deduplicación, ocho declaraciones, cutoff de cancelación y declaración
ausente con expansión de espacios. El último conserva el error original
`'declaration_identity_stem'` como error retornado; nunca debe abortar con panic.
También hay una regresión de sufijos: `.json` no es un archivo con extensión
`.json`, mientras que `.config.json` sí la tiene.

`PieceMatch.proposal_index: usize` está implementado: conserva la identidad de
propuestas duplicadas aunque el resultado posea una copia de la pieza.
Se comparan las 262 columnas, llamadas, scores y caminos/hojas de los 1.280
árboles reales. Sólo las features de composición estática usan el bound F32 ya
aprobado; scores, caminos, llamadas e identidades siguen siendo exactos.

Los nuevos originales y logs están en el workspace local del plan, con prefijos
`original-linux-ranking*` y `original-x86-alignment*`. Los fixtures de Linux
nuevos de ranking declaran `machine=x86_64`: **no constituyen una captura ARM**.
Se conserva aparte `numeric-reference-alignment-linux-x86_64.json.gz`; los 22 casos
de alineamiento adicional coinciden con ARM y no duplican el fixture versionado.
El [registro y preparación de x86_64](rust-migration.md) preserva los registros ARM.

Próximo gate: ejecutar Task 3 con sus originales y suites nativas en macOS arm64
y Linux aarch64. Mantener las nuevas capturas ARM separadas de las x86_64 y no
sobrescribir recibos aceptados. Después seguir Task 4 (cards) del plan. No repetir
las tareas 1–2 ni capturas aceptadas. M4c2/M4/global aún no están aceptados.

La sección histórica siguiente describe el checkpoint portátil del 23/10;
sus pasos 2–5 ya se realizaron en x86_64, no en ARM.

### Lo conservado

- Task 1: `source_snapshot.rs`, `source_catalog.rs`, prueba `source_catalog.rs`;
  38 observaciones / 4 raíces originales por host; suites core/retrieval completas
  con 115 raíces Rust. Tres observaciones son guardas de admisión más estrictas
  que el original, conservadas como tales.
- Task 2: `piece_candidates.rs`, prueba `piece_candidates.rs`; 45 observaciones /
  3 raíces originales por host; 68 raíces Rust afectadas y 2 de tooling.
  Catálogo inmutable, caché privado de descripciones por generación, validación
  de identidad/hash/evidencia antes de codificar. Tres guardas explícitas más.
- Task 3 preparatoria: `tools/rust_migration/piece_ranking_reference.py`, ampliación
  de `piece_reference.py`, `piece-inputs-ranking.json` y
  `piece-reference-ranking.json` en `crates/ken-retrieval/tests/fixtures/`.
  En aquel checkpoint: **84 observaciones macOS y 9 raíces originales aprobadas;
  sin Rust nuevo**. La actualización anterior registra la implementación posterior.
- Generador correcto: `make-ranking-inputs.py` en el progreso restaurado.
  Captura válida: `original-macos-ranking/`. Captura previa con entradas aliased:
  `original-macos-ranking-aliased-inputs/`, retenida sólo para auditar el error
  del generador y reutilizar sus nueve raíces originales.

La primera captura compartía prototipos mutables y unas puntuaciones de overflow
contaminaron otros casos. Se corrigió con deep-copy; **no fue un fallo de Ken**.
La captura válida reutiliza las nueve pruebas originales previas sin repetirlas.
Su `reused_suite.sha256` apunta a
`1cd20ae9b42a085f25ef72edb0075e4e618b36e62d997cb566f51a8b788581fc`.
El path histórico es absoluto: resolverlo por el sufijo relativo al directorio de
progreso al verificar en otra máquina. El JUnit está en la cápsula previa; no
inventar uno para la captura nueva ni contar los 84 casos inválidos como aceptados.
El verificador completo de esta cadena todavía corresponde a Task 7.

### Pasos del checkpoint del 23/10 (referencia histórica)

1. Verificar hashes y restaurar el progreso. Leer el ledger y confirmar que no
   existen cambios nuevos de otro agente. Las tareas 1–2 no se reinician.
2. Capturar **Linux** para los mismos 84 inputs y sus nueve raíces una vez, usando
   el oráculo aislado. Guardar `original-linux-ranking/` y fixture
   `piece-reference-ranking-linux.json`. La función actual es:

   ```python
   from pathlib import Path
   from tools.rust_migration.reference import Reference
   from tools.rust_migration.piece_reference import capture
   root = Path.cwd()
   capture(Reference.load(root / '.ken/rust-migration/portable-reference'),
           root / '.superpowers/sdd/2026-10-23-rust-source-pieces/original-linux-ranking',
           repo=root, family='ranking')
   ```

3. Completar sólo observaciones adicionales disjuntas que falten al contrato:
   límites 4095/4096/4097 términos, deduplicación de campos completos, ocho kinds
   de declaración y cancelación pequeña con cutoff 0. `ranking-edges` es una
   propuesta **todavía no implementada**. Extender el observador/reuso de suite
   sin recapturar los 84 casos ni reejecutar nueve raíces aprobadas.
4. Escribir el uso público y `tests/piece_ranking.rs`; observar missing-API RED.
   Comparar las 262 columnas, secuencias de llamadas, orden, scores y digest de
   caminos/hojas de los 1.280 árboles reales. Nunca introducir respuestas
   esperadas en el probe nativo.
5. Implementar `piece_features` y `PieceReranker` según el plan, usando cobertura,
   stemming, encoder y `NumericRanker` aceptados. Proponer `proposal_index: usize`
   en `PieceMatch` para conservar identidad de propuestas duplicadas tras clonar;
   es una decisión pendiente que debe registrarse, no una API implementada.
6. Pasar las suites completas afectadas, tooling, fmt y clippy en ambos hosts;
   verificar originales y hacer commit/push del resultado. Después Task 4.

Comandos base, con los recursos nativos preparados y las variables del host:

```sh
cargo test --locked --offline -p ken-retrieval --test piece_ranking
cargo test --locked --offline -p ken-retrieval --all-targets
.venv/bin/python -m pytest -o addopts= -q tests/rust_migration/test_piece_reference.py
cargo fmt --all --check
cargo clippy --locked --offline -p ken-retrieval --all-targets -- -D warnings
.venv/bin/python -m tools.rust_migration.reference verify --repo . --manifest docs/validation/rust-migration-2026-10-18/baseline.json
```

En el checkpoint del 23/10 el primer comando fallaba por target ausente.
Actualmente la prueba existe e incluye ranking; ver la actualización del 24/10.
Si la sandbox deniega bind loopback en tests health de core, repetir la misma
suite con permiso local de sockets, conservar el fallo y no filtrar tests.

### Semántica que debe preservar Task 3

- Esquema: 262 nombres = 18 escalares + 4 kinds de petición + 8 de declaración +
  8 campos × 9 estadísticas originales + 8 × 10 expandidas completas + 8 × 10
  expandidas de declaración. Campos en orden explícito:
  `identity, signature, documentation, executable, calls, returns, path, all`.
- Documento: deduplicar textos completos por campo conservando orden de miembros;
  anteponer identidad y newline a identity. `all` une en el orden original;
  `code_terms` limita a 4096. No reemplazar por un conjunto ordenado arbitrario.
- Tres pases: consulta original sin stems, expandida completa con stems y
  expandida de declaración con stems. Cadena vacía cae a fallback; espacios son
  truthy. `best_score` viene de la primera propuesta, no del máximo global.
- `member_score_mean3` usa **sum de Python 3.12 con compensación Neumaier**:
  `sum([1e16, 1., -1e16]) == 1.`; dividir entre 3 da `1/3`.
  No usar fold secuencial ni `math.fsum`, ni cambiar el reductor NumPy pairwise
  de `reductions.rs` o la suma secuencial de los bosques. Referencia del algoritmo:
  `https://raw.githubusercontent.com/python/cpython/v3.12.9/Python/bltinmodule.c`
  (acumulador/corrección y guardas de cero/no finitos). Ya hay casos de cancelación,
  negativos, priors sin ordenar y overflow; falta cutoff 0 del caso pequeño.
- Petición incompatible falla antes de embeddings. Vacío produce 0×262 sin calls.
  Símbolos omiten features/forest opcionales y conservan propuesta/score inicial.
  Otras piezas priorizan path nombrado, soporte exacto, bosque y estabilidad.
- Reutilizar `tests/feature_support/mod.rs` para encoder/stems/log de llamadas y
  el adaptador de tabla real de `tests/rank_models.rs` para composición estática.
  Pasar JSON por `json_transport::python_strings` antes de `PythonText`, también
  en Linux: conserva surrogates aislados y une pares válidos escapados.
- Comparador exacto por defecto, incluido signed zero. Sólo rutas de features
  previamente declaradas toleran F64 a 1e-12 o composición F32 a 1e-6; caminos,
  hojas, scores, llamadas, orden y evidencia son exactos. Transportar NaN/Inf
  con categoría IEEE explícita; no convertir silenciosamente en null.

## 6. M4c2 cerrado; continuar M4d

Todas las tareas M4c2 cerraron con el recibo del 24/10. Esta tabla conserva
sus responsabilidades y contratos; el siguiente bloque pendiente es M4d:

| Tarea cerrada | Responsabilidad | Criterio de aceptación esencial |
| --- | --- | --- |
| 4: `piece_cards.rs` | Proyección fija de piezas con evidencia física | Cards/card_text/canónico iguales; roles y gaps correctos, sin líneas fabricadas o repetidas; límites 64 líneas / 4 excerpts / 12.000 caracteres; fuente stale o fuera del root rechazada |
| 5: `evidence.rs`, `source_evidence.rs` | Ventanas y refinamiento dentro del owner | Judge recibe documentos/purpose reales; ramas distantes conservadas en fragmentos; ≤40 líneas totales; sin votos duplicados ni texto de hijos; >64 cues; scores finitos por bundle; bypasses sin calls |
| 6: `presentation.rs` | Respuesta pública con fuente actual | Diccionarios originales, identidad archivo/owner, warnings/truncated/omitted, orden, round(score,8), líneas completas y presupuestos Python; cambios físicos retiran evidencia stale |
| 7: `source_piece_probe`, `piece_validate`, `piece_evidence` | Aceptación aislada y autenticada | Entradas sin expectativas, raw originals + suites/calls/sources/modelos fijados, tamper tests, ejecución fuera de checkout sin Python, strace Linux/loader, medidas delimitadas, matriz y una revisión final |

Tras Task 7: **una** revisión fresca del plan completo; regraduar hallazgos y
registrar rulings/minors. Una pasada de correcciones Important/Critical con TDD,
suites afectadas completas y replay desde fuentes archivadas; no bucles de
revisión ni recapturas generales sin una causa nueva. Aceptar M4c2 separado de
M4/global; archivar y limpiar su scratch sólo después de commit/push verificados.

M4d debe fijar antes de implementar el contrato de composición y aceptación:

- Conectar recuperación, reranking numérico, piezas, evidencia y presentación
  con datos reales y selección de modelos aceptada; cubrir búsquedas preparadas
  de símbolos/archivos y canales históricos del inventario.
- Preparar/reutilizar vistas y propietarios con lifetimes explícitos. No trasladar
  al adaptador reglas de scoring, ownership o fuente física.
- Probar CLI por procesos y MCP stdio con cliente real, incluyendo errores,
  freshness, límites y esquemas originales. La prueba neural de PieceSearch
  diferida de M4c2 Task 6 pertenece aquí.
- Verificar el contrato de calidad vigente: top1 ≥90%, Recall10 ≥95%, pertenencia
  top10 de los 197/200 casos aplicables, sin usar reserva privada para diseñar.
  Medir arranque, request completo, preparación/indexación y RSS por separado.
- Publicar recibo M4 completo sólo cuando todos sus canales y accesos públicos
  estén acreditados; ningún wrapper Python, stub o fallback silencioso cuenta.

## 7. Etapas restantes después de búsqueda

Antes de cada bloque nuevo, escribir su especificación y plan Superpowers con
llamada representativa, propietarios, archivos, pruebas y salida verificable.
La orden de continuar del 24/10 ya está vigente; no volver a pedir aprobación
de etapa por rutina.

1. **M5a, representación/persistencia estructural:** producir CFG/IR desde los
   parsers/modelo común; identidades, relaciones, valores, evidencia/versionado,
   lectura de formatos previos y snapshots reproducibles del corpus existente.
   M3d no reemplaza este productor. Dividirlo en capacidades completas probables.
2. **M5b, consulta:** conservar KQL1 y KQL2, parser/compilador/operadores,
   bibliotecas, registro, consultas guardadas, sesiones/preparación y frontends.
   Probar positivos, negativos, budgets, cache invalidation y estados desconocido/
   incompleto; un timeout nunca acredita ausencia. Preservar APIs Python públicas
   sólo mediante bindings finos del motor nativo si su auditoría exige mantenerlas.
3. **M5c, flujo/completitud:** cuerpos, valores/efectos, excepciones/finally,
   recursos, generadores y continuaciones con sus límites actuales; regresiones y
   oráculos runtime independientes. Repetir comparación Django aislada con
   resultados y cobertura explícitos. KQL2 preparado mantiene el objetivo vigente
   de gran mayoría de consultas simples dentro de 10 ms, con cold/warm separados.
4. **M6, conocimiento/contratos:** notas y findings, justificaciones/dependencias/
   hashes, anchors, vigencia, entrega, deduplicación por sesión/generación,
   razonamiento, checks y límites de evidencia. Migrar consumidores y persistencia
   con pruebas de comportamiento; conservar incógnitas y presupuesto de checks.
5. **M7, servicio/integración:** autenticación/protocolo local, snapshots/sesiones,
   orden y cierre de cola, watcher, reinicio, lifecycle, concurrencia y lectores,
   CLI/MCP restantes, hooks tolerantes a fallos, skills y hosts. Ejecutar transporte
   y procesos reales, recuperación/interrupciones e instalación/desinstalación
   sobre fixtures; no tocar configuración instalada para aparentar promoción.
6. **M8, entrega:** paquetes binarios con recursos/gramáticas/licencias/modelos y
   sidecars autenticados; CI nativa en cada plataforma/perfil prometido. Matriz
   global sin pendientes, autonomía fuera del checkout con Python ausente, datos
   compatibles, upgrade y rollback ensayados con copias verificadas. Sólo aquí
   puede promoverse la sustitución. Conservar los originales sigue siendo válido;
   no borrarlos como parte de este traspaso ni para adelantar el cierre.

## 8. Riesgos conocidos que no deben redescubrirse

- **Lectores y slots legacy:** COW protege propietario comprometido, rollback y
  reciclaje; no fija indefinidamente slots mmap para lectores entre commits.
  Antes de exponer búsquedas legacy en M4d/M7, materializar filas/vectores propios
  bajo exclusión del escritor o coordinar explícitamente la vida del lector.
  MVCC SQLite por sí solo no fija `vec_slots` del mmap.
- **Freshness del root (hipótesis aún no reproducida):** SourceAuthority confina
  con descriptor de raíz. Probar renombrar/reemplazar la raíz completa después
  de crear catálogo y antes de citar, además de reemplazo de archivo/symlink.
  Un descriptor antiguo puede ver bytes viejos mientras la ruta visible cambió.
  Añadir control mínimo de identidad sólo si el experimento lo exige.
- **Presupuesto de surrogates Task 6:** Python `json.dumps('\ud800', ensure_ascii=False)`
  mide 3 caracteres con comillas; su transporte UTF-8 seguro escapado mide 8.
  Contar caracteres semánticos Python, no bytes ni longitud del escape. También
  difieren escapes de control (`\n` frente a `\u000a`). No cambiar el codec
  compartido aceptado para arreglar el presenter; añadir caso original específico.
- **Floats canónicos ya corregidos M4c1:** Rust Debug puede elegir `.3` para
  `601174747868153.25` y Python `.2`. `rank_json::float` usa serde_json/zmij fijados
  para desempate y formato de exponentes Python. Mantener `float_roundtrip` en
  lectura: sin él un threshold F64 cambió un ULP. Ragged trace ahora valida ancho
  por owner antes de flatten; comparador exacto salvo rutas toleradas explícitas.
- **Coste de fingerprints ya resuelto:** bosque de 2.560 árboles memoiza identidad
  en `OnceLock`; veinte llamadas warm bajaron de 4.578 s a 2.083 ns totales en
  aquel debug. No reimplementar ni repetir ese perfil sin cambios relevantes.
- **Menores M4c1:** coerción/diagnósticos de entradas numéricas Python extremas
  (whitespace vertical-tab, int `10**400`, repr U+0080/U+00AD) siguen delimitados
  en MINORS; no ampliar tolerancias de inferencia por esos diagnósticos.
- **Coste de desarrollo:** capturar originales y catálogos grandes una vez,
  reutilizar recibos con fuentes fijadas, validar sólo el blast radius nuevo;
  ampliar suites cuando un cambio/fallo lo justifique. No regenerar todas las
  expectativas ni reconstruir targets después de cada lectura de documentación.

## 9. Identidades de recursos y criterio final

Los bosques originales están en `crates/ken-retrieval/resources/ranking/` con
manifest/licencias. No entrenar ni sustituir modelos durante el port:

| Recurso | Identidad |
| --- | --- |
| Forest native: 2.560 árboles / 251 features | fingerprint/JSON SHA `6b563fed14ed276e1b310beba84006078ef65ab5d7d3cb5622d759f6a671e3a0` |
| Forest piece: 1.280 árboles / 262 features | fingerprint/JSON SHA `62846d51f58e5da1cf27ad444073d14341bdc6368f8552a7bb1c30e8d6e7d9b9` |
| NPZ `src/ken/embedder/data/ken__static-qwen3-r512-v2.npz` | SHA `e6ab79ad2462d447d367ac4c9735e1062cb752ba6ed50901773ec2bd427a1ff0` |
| Linux dense `libscipy_openblas64_-7220728c.so` | 28.699.769 bytes; SHA `c938cf8481a5858e8d5efea804106275d7d5e7878a161a5d90f05b6121ef4583` |
| Linux dense `libgfortran-daac5196-038a5e3c.so.5.0.0` | 1.671.529 bytes; SHA `8c13f44b44e4dd0005632ea4173f5f5014d2829d50aa12b2054034297c07f233` |

M7/M8 deben distribuir/adquirir explícitamente esos sidecars por plataforma;
no confiar en que estén casualmente junto al ejecutable o instalados con NumPy.
Los manifests/versiones de dependencias son la autoridad, no el nombre del archivo.

La migración sólo termina cuando la matriz de **todas** las capacidades públicas,
perfiles y plataformas prometidas está verificada, CLI/MCP/integraciones usan Rust
de verdad sin intérprete, datos y rollback están probados y calidad/recursos
cumplen los contratos. Hasta entonces mantener `M4_accepted`/aceptación global
falsos donde corresponda y documentar el próximo corte exacto.

### Continuación del 24/10: runners ARM y preparación de cards

El workflow `Native source-piece gates` ejecuta ahora Rust 1.95 y el oráculo
portátil en runners reales `ubuntu-24.04-arm` y `macos-15`. El primer intento,
[40113265720](https://github.com/Infinibay/ken/actions/runs/40113265720), pasó
las 98 observaciones de ranking de piezas y sus dos raíces de pruebas en ambos
hosts. Las suites completas detectaron diferencias de alineamiento numérico
frente a los recibos históricos; ese intento **no acepta Task 3**.

El commit `41d324bd` conserva esos originales y prepara una comparación con
Python congelado en los mismos runners, sin ampliar tolerancias ni cambiar el
cálculo para ajustarlo a resultados esperados. Sus artefactos guardan originales,
resultados, descubrimiento y hashes; todavía requieren interpretación y cierre
de los gates. Los originales se guardan en caché antes de compilar para evitar
repetir las capturas cuando falla una prueba nativa.

Task 4 tiene 60 observaciones originales nuevas en Linux x86_64 y tres raíces de
pruebas, con tarjetas completas, texto canónico, límites de líneas/caracteres,
procedencia y cambios de archivos/directorios. El mismo workflow captura las
familias faltantes en ARM. `piece_cards` ya implementa unidades, extractos y
tarjetas tipadas, proyección canónica y validación física. Sus 60 observaciones
coinciden localmente; las suites completas pasaron 123 pruebas nativas y 108 de
tooling, junto con fmt/Clippy estricto. Sus gates ARM se cerraron en la ejecución
posterior indicada abajo; completar M4c2 sigue pendiente.

La prueba nueva del lector físico también detectó que reemplazar el directorio
raíz conservaba por error las lecturas del directorio anterior. Cada apertura
nueva adquiere ahora un descriptor confinado del directorio actual; los archivos
ya abiertos conservan su propio descriptor. La regresión pasó de RED a GREEN,
y las suites completas core/búsqueda pasaron localmente. El intento adicional de
indexación pasó publicación (7 raíces), pero sus 8 pruebas incrementales carecen
de `KEN_GRAMMAR_MANIFEST`; el catálogo de gramáticas aún no admite Linux x86_64.
Ese límite sigue pendiente y no debe confundirse con aceptación de indexación en
esta arquitectura.

La ejecución posterior [40117742527](https://github.com/Infinibay/ken/actions/runs/40117742527)
(commit `45dc4195`) pasó todos los gates en **ambos hosts ARM**: 123 pruebas
nativas en Linux y 122 en macOS (la prueba del sidecar BLAS es exclusiva de Linux),
109 de tooling, formato y Clippy estricto por host, además de las 98
observaciones de ranking y 60 de tarjetas. El ajuste de almacenamiento del
fixture (`Cow<str>`) resolvió el lint exclusivo de ARM; no cambió la aritmética.
Los originales de evidencia (86 observaciones/19 raíces) también se capturaron
antes de comenzar esa implementación nativa.

Task 5 ya implementa `evidence` y `source_evidence`: verificación de fuente,
completar regiones propias, ventanas y bundles juzgados, selección léxica con
máscaras dinámicas y un presupuesto común de 40 líneas. `result_selection` es la
autoridad compartida de deduplicación por archivo y slots para futura presentación.
La suma Python 3.12 existente se comparte desde `reductions`, sin duplicarla.
Las 88 observaciones locales coinciden (86 iniciales y dos adicionales de
stemming que reutilizan las 19 raíces originales). Pasaron 124 pruebas nativas
locales, 110 de tooling, formato y Clippy estricto. Falta ejecutar esa nueva
implementación en ambos ARM, Task 6, el probe/recibo y la revisión final de Task 7.
M4c2, M4 y la migración global siguen sin aceptación final.

La evidencia nativa de Task 5 cerró sus gates ARM en
[40118877663](https://github.com/Infinibay/ken/actions/runs/40118877663), commit
`b3b74726`: 124 pruebas nativas Linux, 123 macOS y 110 de tooling por host,
formato y Clippy estricto. Se verificaron por separado sus originales, salidas
crudas y los 757 hashes de fuentes contra ese commit.

Task 6 implementa `presentation`: respuestas tipadas de propietarios y piezas,
consulta sin pérdida, redondeo a ocho decimales, ventanas/rangos fieles y los dos
recortes originales por prioridad. El presupuesto usa el formato numérico y
escapado Python ya aceptado, contando los surrogates aislados como un carácter
semántico. Las 117 observaciones y nueve raíces originales pasaron también en
ambos ARM antes de escribir esa implementación, ejecución
[40119578070](https://github.com/Infinibay/ken/actions/runs/40119578070).
El oráculo necesita `onnx==1.20.1` para importar un fixture de la prueba acotada;
no se ejecuta la raíz neural ni se descargan modelos.

La comparación local de presentación pasó de API ausente RED a GREEN. Encontró
y corrigió el formato del aviso de archivo eliminado (errno y ruta), conservando
al lector confinado como única autoridad de bytes. Pasaron 125 pruebas nativas
locales, 111 de tooling, formato y Clippy estricto. Falta validar esa nueva
implementación en ARM y completar el probe/recibo/revisión de Task 7. No se ha
sustituido el comando Python instalado ni se acepta M4/global todavía.

## Cierre M4c2 del 24/10: recibo revisado y transportable

Fuentes aceptadas: `3e4a4e4ccd6762f437af43f618e8631984e67b39`.
La ejecución [40127406181](https://github.com/Infinibay/ken/actions/runs/40127406181)
pasó todos los gates en Linux aarch64 y macOS arm64: **126/125 raíces Rust**,
**174 de tooling por host**, formato y Clippy estricto. Son raíces descubiertas;
las cifras anteriores obtenidas sumando `passed` incluían además un subproceso
de la prueba de salud y no deben usarse como inventario de raíces.

Cada plataforma acredita **446 observaciones: 433 comparaciones y 13 guardas
más estrictas**. Siete casos originales sintéticos etiquetaban como clase una
declaración de otro tipo; se conservan sus resultados originales y se exige
ahora el error preciso sin llamadas de encoding. Las otras seis guardas de
admisión ya estaban declaradas. No se cambiaron modelos, tolerancias numéricas,
salidas válidas ni presupuestos para obtener el resultado.

La única revisión final encontró tres Important: escritura del probe por cadenas
de enlaces, soporte stale en cards y clase con entidad no clase. Una incidencia
de recibos Clippy se elevó de Minor a Important. Las cuatro se reprodujeron y
corrigieron en una pasada; los diez comportamientos apartados tienen resolución
explícita. No hubo segunda revisión ni recaptura de originales aceptados.

El [recibo local](validation/rust-migration-2026-10-23/m4-source-pieces/README.md)
contiene revisión, decisiones, reparaciones, binarios, originales, auditorías,
snapshots y replay. Sus 986 archivos de fuentes/tooling por plataforma se
contrastaron contra Git y la aceptación se repitió con el verificador archivado.
`FILES.json` tiene SHA-256
`92954a5df4ea37bf4820b50e695b023d84d305fab29e7c19c09b93ea7d781e20`.

Archivo local `.ken/rust-migration/archives/m4-source-pieces-3e4a4e4c.tar.gz`:
340.368.226 bytes; SHA-256
`feafc8ea7dfe9f81beaf729e5ba15766ff7ab70eb3d3c656a8dd9c447172f5d7`.
Se mantiene fuera de Git. Las capturas de plataforma también están en Actions
por 30 días: Linux `12572999379`, macOS `12573364847`. El recibo posrevisión
completo se transporta con el archivo local; no se reconstruye recapturando.

Los 1.066 originales conservan sus hashes. Los escenarios y runtimes temporales
se limpian al cerrar sus propietarios; se mantienen raw, SDKs y cachés compartidas.
**M4c2 está aceptado; M4 y la migración global siguen falsos.** La búsqueda pública,
CLI/MCP y el Ken instalado todavía no usan este motor completo. Continuar por
M4d: las gramáticas x86_64 quedaron registradas y validadas en el cierre siguiente;
continuar con composición, pools, modelos y gates públicos.


## Cierre de gramáticas Linux x86_64 del 24/10

Fuentes: `7048d3fb6f4505ca44dfa222cfdde80a9c3dea3e`.
La ejecución [40141705583](https://github.com/Infinibay/ken/actions/runs/40141705583)
pasó en Linux x86_64, Linux aarch64 y macOS arm64: **33 raíces Rust/doc,
87 de tooling y 249 comparaciones completas por host**, formato y Clippy estricto.
Son 20 gramáticas, 19 parsers y 44 extensiones; las 13 bibliotecas dinámicas x86
usan el pack 1.8.1 fijado y los dos registros ARM conservan sus bytes.

La referencia x86 se capturó una vez antes de habilitar el host: 215 casos,
217 llamadas y 124 raíces originales. Los originales ARM se reutilizaron;
los 1.066 archivos congelados siguen intactos. La única revisión final encontró
una falta de unión entre recibo, snapshot y tooling, además de filtros CI
incompletos. Ambos puntos se repararon en una pasada; ocho regresiones nuevas
pasaron de RED a GREEN. No hubo segunda revisión ni recaptura de originales.

El [recibo local](validation/rust-migration-2026-10-24/x86-grammars/README.md)
se reprodujo con el verificador archivado, ligado a las fuentes y al tooling
revisados. Se contrastaron 273 archivos de snapshot por host contra Git.
`FILES.json` contiene 942 miembros y tiene SHA-256
`7990e3edaf04a9b95f2ede40cb165298840d5f33094d397c1d749ee8beaf1350`.

Archivo local `.ken/rust-migration/archives/x86-grammars-7048d3fb.tar.gz`:
23.328.842 bytes; SHA-256
`479fd3e89717ae2130207b2859b8f83c854ddd4b61ed7adb126f90324da3535f`.
El replay también pasó tras extraer ese archivo en un destino independiente.
Los raw, SDKs y recibos siguen fuera de Git. Ver [transporte](validation-artifacts.md).

Sólo `Grammar_x86_64_accepted` es verdadero en este recibo. Las ocho pruebas
incrementales locales son smoke; falta aceptación completa de indexación y
perfiles de modelos x86. Los recibos ARM anteriores conservan su aceptación.
M4 completo, CLI/MCP y la migración global siguen pendientes; Ken instalado sigue
siendo Python. Continuar M4d sin volver a ejecutar originales ya aceptados.


## Avance M4d: fusión ordinal y siguiente objetivo x86_64

`reranker_fusion::fused_reranker_order` ya combina el orden existente y el neural
sin cambiar identidades ni limitar el pool. Fuentes `f239ea9b`, integración
`b2ea3b318280c393185600d49854de2ab29fd387`. Compara exactamente 2.616 observaciones
originales, incluidos errores, empates, subnormales y pools mayores que diez.
Sus doce raíces originales se ejecutaron una vez antes de escribir la API Rust.

La ejecución [40142505190](https://github.com/Infinibay/ken/actions/runs/40142505190)
pasó 127 raíces Rust en Linux ARM y 126 en macOS ARM, 174 de tooling y 446
observaciones de piezas por plataforma, formato y Clippy estricto. El aumento
respecto de M4c2 es exactamente la nueva raíz de fusión. Las fuentes y el tooling
se contrastaron contra Git y cada integración se reprodujo con su verificador
archivado. La regresión de sintaxis también pasó sus tres hosts en `40142505163`.
Localmente pasaron 127 raíces Rust, 174 de tooling y 363 comparaciones auditadas
x86, conservando intactos los recibos M4c2 y de gramáticas.

La única revisión final no encontró fallos de producción ni Critical/Important.
Queda un Minor de cobertura: añadir por separado el caso scores `[0,1]`, peso
`0.5`, offset `2^53`, que protege el agrupamiento aritmético ya correcto. La
siguiente captura M4d debe incluirlo sin reescribir el corpus de 2.616 casos ni
repetir sus doce raíces originales. Las ocho conductas apartadas tienen resolución.

El [recibo parcial local](validation/rust-migration-2026-10-24/reranker-fusion/README.md)
conserva original, fuentes, revisión y gates; `FILES.json` tiene 69 miembros y SHA
`27d87534b036bf336590d967eca242f931f0fae5ab14d8a1fd6f3cd91ca7b6d3`.
Los paquetes CI completos y sus verificadores permanecen fuera de Git en
`.ken/rust-migration/fusion-ci-40142505190/`; este recibo pequeño no afirma un
replay separado de esos paquetes externos. M4d/M4/global siguen pendientes.

El usuario reiteró que quiere Linux x86_64 como objetivo de validación completo.
Gramáticas, BLAS y runtimes CPU están habilitados; modelos e indexación requieren
su propia aceptación de arquitectura. El primer original contextual x86 ya está
preparado, con 20 comparaciones nativas exitosas. Continuar desde ese original,
conservar los recibos y después retomar la composición restante de M4d.

## Runtimes CPU Linux x86_64 aceptados el 24/10

El candidato `ece7a0c67c5c7ad64e0cb72a1e2cd03fb099c458` añade selección exacta por OS y arquitectura,
ONNX 1.25.1/API25 y Torch 2.9.0 CPU para Linux x86_64. Las fuentes oficiales,
licencias, bytes y cierre de bibliotecas quedan autenticados antes de publicar
un SDK en un destino nuevo. Los registros ARM conservan sus identidades.

El CI [40149696864](https://github.com/Infinibay/ken/actions/runs/40149696864)
pasó en Linux x86_64, Linux aarch64 y macOS arm64: 6 raíces ONNX/protocolo por
host, 15 de Torch en Linux y 16 en macOS, 364 de tooling por host, formato y
Clippy estricto en ambos workspaces. La raíz adicional de macOS es la prueba
MPS existente. Linux registra exec/connect reales; esta capacidad nueva exige
en macOS un sandbox y un probe que demuestra el bloqueo de un hijo propio,
un ejecutable de ruta absoluta y una conexión. Se preservó el alcance de los
protocolos históricos. También pasaron las regresiones de gramáticas en tres
hosts (`40149696833`) y de fuentes/piezas en dos ARM (`40149696715`), con sus
fuentes y tooling contrastados contra Git y replay archivado independiente.

El recibo local está en
`docs/validation/rust-migration-2026-10-24/x86-runtime-cores`.
`FILES.json` contiene 3762 miembros y SHA-256
`150a0f88cacfe22c98d8d053411299bf5281eef30cc68a112a25aaa754c4ce12`.
Archivo local: `.ken/rust-migration/archives/x86-runtime-cores-ece7a0c6.tar.gz`, 108804290 bytes,
SHA-256 `19b7361473f7074712f4aa5f059c925d555e0095ba369af976a98363b90039bc`.
Pasó el replay desde los snapshots archivados y desde el transporte extraído.
El replay se aísla de `PYTHONPATH` para cargar el validador archivado. Los 1.066
originales congelados siguen intactos; SDKs, raw y archivos permanecen locales.

Sólo `NativeCPUCore_x86_64_accepted=true`. La aceptación completa de modelos e
índice x86, M4 y la migración global siguen pendientes. El Ken instalado sigue
siendo Python. Faltan los originales x86 y matrices completas de los restantes
modelos/perfiles, CT2, indexación con sus historiales y composición de búsqueda.
El executor antiguo de transformers rechaza x86 hasta contar con originales
ligados a arquitectura: no retirar esa guarda ni usar originales ARM como prueba.

El siguiente original contextual ya existe en `.ken/rust-migration/x86-context`:
20 historiales originales x86, 4 pruebas originales y 20 comparaciones nativas
pasaron con los límites existentes y un solo exec, sin conexiones. Es un
experimento pendiente de fixture permanente y cierre de su propia capacidad.
El original tiene 935725 bytes y SHA-256
`b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733`.
Transporte local: `.ken/rust-migration/archives/x86-context-preparation-9b9ff88b.tar.gz`,
4603583 bytes, SHA-256
`18417f23303f9a21aa32c20b7d2a861648afe211e004fc182616a66734f20869`.
Conservar sus labels `9b9ff88b` y reutilizarlo sin recapturar. Ese original ya se incorporó al test permanente; el estado posterior está al final
de este documento. Además pasaron
localmente 7 contratos de los encoders/juez con Torch real y 6 de `ken-rs status`.

Hubo una revisión final y una pasada TDD. El Important de aislamiento quedó
resuelto. El conteo se corrigió por plataforma tras observar las 16 pruebas
macOS: no se omitió ninguna. Menor diferido: una descarga fallida puede dejar
su temporal `.sdk-download-*`; la limpieza se hará por separado. Las decisiones,
los intentos y los límites están en `LEDGER.md` del recibo local.

## Estado contextual x86_64 y fallo ARM preexistente

El fixture contextual propio de Linux x86_64 ya está incorporado y el test dejó
de exigir aarch64. Se conserva el original de 935725 bytes y SHA-256
`b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733`.
No se volvió a capturar. El candidato de código es
`b9ea0578151c887c92984e3112734ffd81d94a77`.

En el [CI 40154476254](https://github.com/Infinibay/ken/actions/runs/40154476254),
Linux x86_64 y macOS pasaron sus 8 raíces contextuales Rust, 20 historiales
nativos auditados y 11 de tooling, además del padre CPU completo. Los tres
hosts pasaron el padre CPU (6 raíces ONNX/protocolo, 15/16 Torch, 364 de tooling,
formato y Clippy). También pasaron gramáticas y fuentes/piezas del candidato.
La única revisión final encontró un Important de vinculación del JUnit; quedó
reparado mediante RED→GREEN y comprobación del destino declarado, incluido el
transporte a otra carpeta. No hubo segunda revisión.

**La matriz contextual completa no está aceptada y el workflow global queda rojo.**
Linux ARM falla en `passage-boundary511`: esperado `0.21820393204689023`,
obtenido `0.181270033121109`. El diagnóstico ejecutó en el mismo runner tanto
la versión actual como el baseline intacto `26ec740d...`: ambos fallaron igual.
Los logs confirman que el baseline se compiló desde su worktree. El selector
x86 y la corrección del JUnit no introdujeron esa diferencia. Su causa exacta
sigue sin determinarse; no atribuirla todavía al hardware ni al backend.
No se cambiaron los originales, tolerancias ni criterios para convertirlo en verde.

El [estado local preservado](validation/rust-migration-2026-10-24/x86-context-status/README.md)
registra x86=true, macOS=true y ARM=false; no es un recibo de aceptación.
`FILES.json`: 3818 miembros, SHA-256
`72eb98dacf9590a18965b9cfd5dcfa734a218b05deea72912792a74f56eb56dc`.
Archivo local `.ken/rust-migration/archives/x86-context-status-b9ea0578.tar.gz`,
121742888 bytes, SHA-256
`f1ed4cd7ff7f5e195e237a8084512266700ce8acac8fe260579bb5e2ba1e9bba`.
Los verificadores archivados reproducen los estados observados. Los raw, SDK,
pesos y diagnósticos siguen fuera de Git. El recibo CPU aceptado de ece7a0c6
permanece intacto.

Quedan dos menores de este bloque: el audit contextual tiene un límite de 60 s
frente a los 600 s históricos, y el hash Rust del fixture se comprueba en una
raíz de test separada del consumo. El conjunto completo sí exige esa raíz y el
coordinador Python comprueba el hash antes de comparar. El resto de modelos,
CT2, indexación x86 y M4/global siguen pendientes. La siguiente investigación
es explicar la diferencia ARM conservando la evidencia del baseline; no recapturar
sus vectores para hacer coincidir la implementación.

## Continuación del 25 de octubre: diagnóstico ARM y Ettin x86_64

El [diagnóstico ARM 40213861529](https://github.com/Infinibay/ken/actions/runs/40213861529)
terminó correctamente en `1cecb476`. Para `empty-query`, `passage-boundary511` y
`passage-boundary512`, Python ONNX y Rust producen exactamente los mismos 768
componentes. Se probaron carga desde archivo/memoria, uno/dos hilos y dos
repeticiones: las doce combinaciones son estables e idénticas entre lenguajes.
Los dos textos largos difieren del original ARM preservado, con máximos absolutos
0.967323899 y 1.681113482. En x86 las doce combinaciones coinciden exactamente
también con su original; sus ocho raíces contextuales volvieron a pasar.

Esto reproduce la diferencia en el runtime compartido, también mediante Python
ONNX directo con los mismos tokens y opciones; no es exclusiva del port Rust.
No identifica todavía la instrucción/kernel/condición de CPU responsable. La
aceptación contextual completa sigue falsa y el workflow histórico sigue rojo.
No cambiar tolerancias, recapturar los originales ni convertir este diagnóstico
de tres casos en aceptación de los veinte historiales.

Diagnóstico local: `docs/validation/rust-migration-2026-10-25/context-arm-diagnostic`,
26 miembros, `FILES.json` SHA256
`3ed530c628f8bd8eb7eb38d1ed794f50bcaace5f98b7cfa7e34e7d5502fffab8`.
Transporte `.ken/rust-migration/archives/context-arm-diagnostic-1cecb476.tar.gz`,
246579 bytes, SHA256
`70f7b9bb3f7b3d30fc2f2a63037ff8acb5b03a6900333913460ccf39238a9e99`.
Se verificaron sus miembros y se reprodujo el análisis archivado. Este análisis
requiere, además, los originales del repo con sus hashes fijados; no es autónomo.

El siguiente bloque independiente quedó implementado en `3da84508`: el test real
de Ettin elige el original por OS **y** arquitectura, verifica su hash antes de
consumirlo y rechaza destinos desconocidos. Antes trataba todo Linux como aarch64.
El scorer, compilador de cabeza, políticas y tolerancias no cambiaron.

Su primera captura Linux x86_64, anterior al selector, contiene los 23 historiales:
667940 bytes, SHA256
`ec1a7477107da440828fd0f46ab2c6d9be45a5d64c7c516306797aa2636e20ce`.
Se consume sin cambios en `crates/ken-models/tests/fixtures/ettin/linux-x86_64-original.json`.
**Nunca recapturar** `.ken/rust-migration/x86-ettin/original.json`. Pasaron 24
pruebas originales, RED→GREEN del selector, las 16 raíces nativas del target
`onnx_reranker`, formato/Clippy estricto y 23 historiales en una sonda nativa con
preparación Rust fresca y reutilización sin fuente. Auditoría: un exec, ningún
connect, sin Python; fuentes/core/binario intactos. Caché nativo y fuentes
verificadas quedan locales. Los 1066 archivos congelados siguen idénticos.
La única revisión final del plan Ettin encontró 0 Critical/Important/Minor.

Evidencia local: `docs/validation/rust-migration-2026-10-25/x86-ettin`, 256 miembros,
`FILES.json` SHA256
`4f15fc3a39e94a8a6b7091db24e88a8b6be0414cb9e06bf6f40ec21b2913f0fe`.
Transporte `.ken/rust-migration/archives/x86-ettin-test-3da84508.tar.gz`, 4915668
bytes, SHA256
`7bb91c418006587e41738ecdb323dc99cfe9fcdbbe1e741bf40a89775914c883`.
`replay.py` exige Python aislado y usa el tooling archivado para comparar todos
los historiales y verificar raw/auditoría/pruebas. Es verificación del test y
experimento local x86; **Ettin completo, matriz de modelos/M2/M3, índice x86,
M4 y migración global siguen sin aceptar**. Falta integrar los modelos x86 en
sus ejecutores/recibos completos, luego CT2, composición de búsqueda y los
subsistemas restantes; resolver por separado la identidad numérica ARM contextual.

## Foco x86_64: ejecutor de modelos cerrado el 25 de octubre

La instrucción actual del usuario es avanzar **sólo en x86_64 por ahora**.
Los workflows activos de modelos y gramáticas ejecutan Linux x86_64; los
originales, registros y recibos históricos de ARM/macOS se conservan. La
investigación numérica ARM queda diferida y no bloquea este nuevo alcance.

El candidato `45ab4dc495df6265f7ad2c70dc347f9042013104` pasó el
[CI de modelos 40217751708](https://github.com/Infinibay/ken/actions/runs/40217751708)
y el [CI de gramáticas 40217751756](https://github.com/Infinibay/ken/actions/runs/40217751756),
con un único job Linux x86_64 en cada workflow. El ejecutor completo pasó:

- CPU: 6 raíces ONNX/protocolo, 15 Torch y 364 de tooling; formato/Clippy estricto.
- Contexto: 8 raíces Rust, 20 historiales auditados y 11 de tooling.
- Ettin: 16 raíces Rust, 23 historiales auditados y 38 de tooling.

`tools/rust_migration/ettin_host.py` integra Ettin con el padre CPU y reutiliza
su referencia existente de SHA `ec1a7477...`; nunca llama al comparador legacy
que recaptura Python. La petición contiene configuración, casos, fuente y core,
sin respuestas. Se exige preparación Rust fresca y reutilización sin upstream.
Los 15 artefactos de entrada permanecen intactos; sólo se permiten los cuatro
archivos de caché declarados, con bytes/hashes exactos.

`NativeJsonCapture` mantiene el protocolo `/1` inmutable de 60 s. Su extensión
explícita `generated_files` usa `/2`, 600 s y contrato autorizado por el caller;
rechaza entradas sobrescritas, salidas ausentes/extra/alteradas, symlinks y cambios
de contrato. La auditoría conserva exec/connect/loader y rechaza carga de Python.
No es una sandbox general de filesystem; los callers actuales trabajan desde el
checkout y ejecutan código nativo revisado. Los originales/tolerancias/modelos
Rust no cambiaron. Los 1066 archivos congelados y ambos originales x86 siguen intactos.

La única revisión fresca encontró 0 Critical, 0 Important y un Minor diferido:
el path generado inválido `"."` falla antes de ejecutar con `IndexError`, en vez
de `ValueError`. Los cuatro paths reales de Ettin no se ven afectados. No hubo
pasada de reparación ni segunda revisión.

Recibo local `docs/validation/rust-migration-2026-10-25/x86-models`: 1630 miembros,
`FILES.json` SHA256
`d22252ad561c5c5dbe4a0fdf8ef5aa0f82c579952a5fd24ab0923c2d1a6ce3b6`.
Se autenticaron 1225 entradas de modelos y 289 de gramáticas contra el candidato
Git; los datos históricos ignorados se vinculan al checkpoint `02a0e6b...`.
Transporte `.ken/rust-migration/archives/x86-models-45ab4dc4.tar.gz`, 54559658 bytes,
SHA256 `653ad538d2d17cfecae831f3c200cd82446e11126acb53621b7a9fd5b6b069a8`.
`replay.py` usa Python aislado y el tooling archivado; también pasó desde el
transporte extraído fuera del checkout, ignorando un PYTHONPATH del repo vivo.
Raw, SDK, pesos y cachés siguen locales y fuera de Git.

Este recibo acepta **Context_x86_64 y Ettin_x86_64** bajo el alcance de un host.
La matriz contextual histórica de tres hosts permanece con su estado anterior.
M2/M3 completos en x86_64, su índice, M4 y la migración global siguen pendientes. Continuar
los perfiles de modelos x86 restantes y la composición de búsqueda M4; no volver
a investigar ARM ni recapturar los originales para avanzar en este foco.


## Vistas neuronales de símbolos en Rust: Linux x86_64

El candidato `206f4861571b7dd6300649043dd90d2e0d69774f` pasó el
[CI de modelos/búsqueda 40225028046](https://github.com/Infinibay/ken/actions/runs/40225028046)
y el [CI de gramáticas 40225028097](https://github.com/Infinibay/ken/actions/runs/40225028097),
con un único host Linux x86_64. `paired_reranker` posee la conversión escalar y
la delegación al modelo; `symbol_views` posee admisión del código completo,
deduplicación, fallback por candidato, media exacta `(original+code)/2` y orden
estable. Rechaza vistas de más de 64 líneas Python o 12000 codepoints enteras;
nunca puntúa un prefijo. Conserva Unicode/surrogates en las proyecciones y la
inferencia vacía no necesita recursos del modelo.

La primera observación independiente, anterior a los APIs Rust, contiene 61
casos de política, 5 frames reales de Ettin y 2 pruebas originales. Las peticiones
neutrales desactivan naturalmente las preferencias de operaciones/tests/operadores;
no se sustituyó la política original. El original preparó su propio modelo desde
las 15 entradas verificadas. Referencia cruda de 566724 bytes, SHA256
`77fe898f25f5ad42cff951b023262065e9b633c1010ddf556e7a5f1ec7944e0e`;
fixture comprimido de 7320 bytes, SHA256
`80bf3b93cfa93533da9c3fdf0b9654e0317c7785b00fe059e7b2b5b51f59261f`.
**Nunca recapturar** `.ken/rust-migration/symbol-views/original`.
El nuevo test de agrupación de fusión usa una observación separada; no modifica
el corpus anterior de 2616 casos. Los 1066 archivos congelados y los originales
x86 de contexto/Ettin siguen idénticos.

Pasaron RED→GREEN de política/adaptador y los 134 roots nativos únicos de
ken-core/ken-retrieval (127 anteriores + 7 nuevos), 27 roots de tooling,
formato/Clippy estricto y los 5 frames nativos reales auditados. El probe calcula
sus propios logits de tarjetas y de código; recibe sólo entradas, sin respuestas.
Permanecen obligatorios los padres CPU 6/15/364, contexto 8/20/11 y Ettin
16/23/38, además de gramáticas. Las cuatro salidas de caché y las 15 entradas
inmutables se verifican junto con el binario/core y exec/connect/loader.

La única revisión fresca encontró 0 Critical, 1 Important y 1 Minor. El Important
era un test que cargaba el árbol congelado local antes de probar el rechazo de
recaptura: fallaba en checkout limpio. Se reprodujo RED en la copia archivada y
se reparó en `206f4861` construyendo un Reference temporal sin archivos; GREEN
aislado sin `.ken` local, suite completa y CI del candidato. No hubo segunda
revisión. Minor diferido: falta un test directo de NaN/±Inf devueltos por el
colaborador adicional; el guard de finitud existe. Se conserva también el Minor
previo del path generado `"."` (IndexError antes de ejecutar).

Recibo local `docs/validation/rust-migration-2026-10-25/symbol-views`: 1683
miembros, `FILES.json` SHA256 `c5827e651d92f23f4138e7522afd6365b88767c3de90505cb57baa0cb6776a6d`. Transporte local
`.ken/rust-migration/archives/symbol-views-206f4861.tar.gz`, 59365577 bytes, SHA256 `dc747bdfa63159a2d45dd3ab8d286ea98b62b2b054cc783dd9b8e51b7590da73`.
Los snapshots de modelos/gramáticas se autentican byte por byte contra el
candidato Git; los inputs históricos ignorados contra checkpoint `02a0e6b...`.
Pasó `replay.py` con Python aislado y tooling archivado, también desde el transporte
extraído fuera del checkout e ignorando PYTHONPATH vivo. El paquete precommit
anterior conserva su HOST `9fb448c`; no se relabeló como evidencia del candidato.
Raw, originales, SDK, pesos y cachés permanecen locales y fuera de Git.

Acepta sólo **SymbolViews_x86_64**, un prerrequisito neural para componer búsqueda.
Preferencias de operaciones/test/operadores, SymbolRanker completo, PieceSearch,
modelos restantes, M4 y migración global siguen pendientes. EntityKey conserva
su contrato escalar; PythonText mantiene las proyecciones lossless. ARM/macOS y
su rendimiento no se revalidaron. El workflow histórico ARM de piezas queda
manual; la suite nativa de retrieval corre automáticamente en x86_64. Continuar
con los observadores de operaciones y requisitos de símbolos para componer
SymbolRanker/PieceSearch sin mezclar esa política con el adaptador neural.


## Preferencias explícitas de símbolos: Linux x86_64

El candidato de validación `49bf56ce2dedc4df327ff1c99942438e0ddf0e3a` pasó los CI
[modelos/búsqueda40232431774](https://github.com/Infinibay/ken/actions/runs/40232431774) y
[gramáticas40232431765](https://github.com/Infinibay/ken/actions/runs/40232431765), ambos
con un único host Linux x86_64. `symbol_requirements` interpreta requisitos explícitos de
operaciones, tests y operadores; `symbol_preferences` aplica tres preferencias estables:
operaciones → tests → operadores. Conserva todos los candidatos, sus puntuaciones
neuronales y el orden previo dentro de cada grupo. Los arrays de evidencia y la
permutación se validan antes de indexar. La identidad de test utiliza rol, extensión y
contexto callable del catálogo inmutable, incluyendo el prefijo Java original de 12 líneas
y el primer brace. El patrón TEST_OBJECT tiene un solo dueño compartido con intent.

La primera observación anterior a los APIs Rust contiene 286 casos de política, 21
identidades de catálogos reales tras cambiar el disco y 13 raíces originales puras.
Referencia de 110121 bytes SHA256
`af38fdcb6a19a0a8e0b8780ce8cf526a9c641e9392fc7537f5f24a0d076d010a`; fixture de 6670 bytes
SHA256 `dfa4e7b78aabd72e573435aeb0564d219ee18cf48c664218abc83fd472351e73`. Nunca
recapturar `.ken/rust-migration/symbol-preferences/original`.

La única revisión fresca encontró 0 Critical, 1 Important y 1 Minor. El Important:
Oniguruma no trata U+001C–U+001F como espacios, y un \S sin traducir podía consumirlos al
retroceder \s+, inventando una invocación incluso ante `no listener` o `nothing`. Se
capturaron 118 observaciones nuevas y disjuntas ANTES DE LA CORRECCIÓN, conservando el
fixture de 286 casos intacto. Referencia de 23283 bytes SHA256
`73bf887642412edcfb29fb2ab7c312d830518c0c17b72be82b69f1d57e144c6b`; fixture de 1116 bytes
SHA256 `7ab32bc98cbc5b51d1740391b44e354b8a792de4d2dec2e4fc734ed335d61165`. Nunca
recapturar `.ken/rust-migration/symbol-preferences/whitespace-original`. El test nativo
fue RED antes del arreglo y GREEN después: text_patterns traduce \S fuera de clases con el
complemento de su misma clase Python de \s. La regla queda en el matcher, sin duplicarla
en la política. Una sola reparación, sin segunda revisión. Minor diferido: is_test_case
recorre owners por candidato; queda una mejora de consulta indexada, sin benchmark de
rendimiento.

Pasaron 141 raíces nativas únicas de core/retrieval (134 previas +7), 404 observaciones de
requisitos/preferencias, 21 identidades y 24 raíces de tooling, formato/Clippy estricto.
La sonda nativa recibe sólo entradas. Se exige también CPU 6/15/364, contexto 8/20/11,
Ettin 16/23/38, vistas 61/5/27 y gramáticas. Los modelos, tolerancias, los 1066 archivos
congelados y originales previos permanecen intactos. La política compone con las vistas
neuronales sin alterar sus scores.

La primera ejecución nativa completa omitió rutas de runtime/modelo: dos tests reales de
Ettin fallaron por falta de recursos; ambos pasaron con el entorno fijado. El primer
paquete local completo se descartó porque añadí el observador disjunto mientras corría y
el control de fuentes detectó el cambio. Ambos raw y el paquete marcado `c032a960` se
preservan; no se aceptan ni cambian sus etiquetas. La época reparada marcada `2c0bf3ac`
pasó local. El ejecutor `49bf56ce` pasó la cadena local y los CI completos con fuentes
fijas. El runner del CI aprobado fue AMD EPYC 7763, con AVX2.

Recibo local `docs/validation/rust-migration-2026-10-25/symbol-preferences`: 3032
miembros, FILES SHA256 `98bfb5936043f0ee931cbcb02d56bfe52fc1ff8079a07ba2de89060d05e40a74`.
Transporte `.ken/rust-migration/archives/symbol-preferences-49bf56ce.tar.gz`, 98734579
bytes, SHA256 `72b0084b6a16b807487ddeffc11e68f7cdd9eeb947e7b0fa9f1e34543e2ba13a`.
Snapshots de modelos/gramáticas autenticados contra el candidato Git; datos históricos
ignorados contra checkpoint `02a0e6b...`. Replay aislado con tooling archivado pasó
también desde el transporte extraído fuera del checkout, ignorando PYTHONPATH vivo. Raw,
SDK, pesos y cachés siguen locales y sin tracking.

Se conserva además el fallo contextual anterior en CI 40230143378: en passage-boundary511
esperaba -0.015078825876116753 y obtuvo 0.15921735763549805, antes de ejecutar
preferencias. Sus 1244 entradas se autenticaron contra `2c0bf3ac`; el padre CPU completo
pasó, contexto 7/8 y los perfiles siguientes no se ejecutaron. Los árboles de
ken-models/API nativa y Cargo son idénticos a `45ab4dc4`; esta igualdad no determina la
causa del fallo. El diagnóstico 40231386038 en AMD EPYC 7763 pasó el test de los 20
historiales del baseline y del candidato; en 3 casos × carga archivo/memoria × 1/2 hilos ×
2 repeticiones, Python/Rust y el original coincidieron exactamente en 768 componentes. Ese
diagnóstico filtró el test registrado y no comparó las 8 raíces completas; el CPU del
runner fallido no se registró. La causa exacta continúa sin demostrar. No se modificaron
vectores, modelos ni tolerancias. El recibo conserva ambos estados, sus fuentes y raw: no
es aceptación de todos los CPUs x86 ni del modelo global. La hipótesis de kernels/ISA
sigue pendiente; el diagnóstico no la prueba.

El ejecutor ahora registra CPU-ENVIRONMENT y PROFILE-STATES, completa los perfiles
independientes y omite dependientes sólo cuando falta su padre real:
core→Ettin→vistas→preferencias; contexto es independiente tras core. Tres pruebas
RED→GREEN verifican esta coordinación. El job global sigue fallando si cualquier perfil
falla o se omite. Esta separación no relaja ninguna comparación numérica.

Acepta sólo **SymbolPreferences_x86_64**. El caller suministra testigos de operaciones; la
observación real OperationWitnesses no se simula ni queda implementada aquí. Faltan esos
observadores, SymbolRanker/PieceSearch completos, modelos restantes, M4/global. ARM/macOS
no se revalidan. Continúan los dos menores heredados: clase de error del path generado
`"."` y cobertura directa del guard neural de scores adicionales no finitos. Siguiente
paso: portar los observadores de operaciones sobre el catálogo para completar la
composición de símbolos.

## Testigos sintácticos de operaciones: Linux x86_64

`SyntaxOperationWitnesses` implementa el backend Java/JavaScript/TypeScript del
observador original: detecta invocaciones y retornos de un flag con actualización.
`SourceCatalog` conserva la autoridad sobre snapshots, owners canónicos y extents;
`GrammarCatalog` conserva la selección de gramáticas; el nuevo backend posee las
cachés por archivo y por owner. No lee nuevamente el disco para observar código.
El resultado devuelto es una copia independiente de la caché y las extensiones no
admitidas producen un error explícito. La política de preferencias consume los
testigos reales sin alterar scores neuronales.

La primera captura independiente, anterior al backend Rust, contiene 120 casos,
144 owners y cuatro raíces originales disjuntas aprobadas. Referencia267835bytes
SHA256 `26dd79e21a5016116938846666dd9ab79b02fd250043b0e30e2ca4c9a2b323a8`;
fixture12758bytes SHA256
`3f1f851be636cce48403df41fda0d88a49f28b6159df7e924d4a04899c64d805`.
Nunca recapturar `.ken/rust-migration/syntax-operation-witnesses/original`.
La primera finalización rechazó una versión mal anotada del language-pack; se
corrigió sólo el validador contra el lockfile1.8.1 y se finalizaron las mismas
observaciones existentes. No se repitieron ni los observadores ni esas pruebas.
Los1066archivos congelados y los fixtures previos se conservan intactos.

Se conserva la selección exacta del callable por rango/orden/desempate y el end
line; se inspecciona sólo su body y se excluyen callables anidados. Clases locales,
constructores, getters, cuerpos ausentes y árboles recuperados mantienen el
comportamiento original. La igualdad de targets quita espacios Python incluso
dentro de literales; no es equivalencia AST. Gramáticas Java/JS/TS/TSX son builtin:
la sonda posee sólo el binario y el manifiesto canónico de20entradas, sin afirmar
que cargó veinte módulos dinámicos. El manifiesto, los recursos poseídos, entradas
y resultados se autentican. La ejecución nativa aislada tiene PATH vacío y audita
exec/connect y loader; no recibe respuestas esperadas ni ejecuta Python.

La coordinación admite un grafo explícito sin cambiar la API anterior de cuatro
perfiles. Syntax depende de preferencias; contexto sigue siendo independiente
tras core. Cinco pruebas nuevas verifican dependencia, propagación del fallo y
rechazo de grafos inválidos antes de ejecutar callbacks. El job falla si cualquier
perfil falla o se omite. Se conserva la incertidumbre contextual documentada en el
recibo anterior; esta ejecución no demuestra una causa ni todos los CPUs x86.

La implementación tiene alcance **SyntaxOperationWitnesses_x86_64**; su aceptación
completa de CI permanece pendiente. Python necesita un backend que
preserve la semántica de su AST: RustPython0.4 no satisface directamente los
contratos de surrogates, identificadores y strings Python3.12. No se añadió ninguna
dependencia ni un fallback parcial. Quedan Python AST witnesses, el router completo
OperationWitnesses, SymbolRanker, PieceSearch, modelos restantes y cierre M4/global.
ARM/macOS no se revalidan y la aplicación instalada continúa en Python.


El candidato `417453b7f90c5d88885f0a7b5a189d9e320af024` pasó la cadena local
completa con fuentes fijas:145 raíces nativas de core/retrieval,25checks nuevos,
formato/Clippy estricto y padres CPU6/15/364,contexto8/20/11,Ettin16/23/38,
vistas61/5/27 y preferencias404/21/24. El replay aislado con validadores extraídos
pasó. También pasó el [CI de gramáticas40240925523](https://github.com/Infinibay/ken/actions/runs/40240925523),
cuyas fuentes se autenticaron contra Git.

La única revisión independiente encontró0Critical,1Important de cobertura y1Minor.
El Important quedó corregido en `417453b7`: el caso congelado de recuperación sólo
admitía extent de módulo1..4 y no seleccionaba el callable que acaba en3; la prueba
de backend sólo usaba owners desconocidos. Dos mutaciones deliberadas (descartar
árboles con errores y devolver vacío para extensiones no admitidas) pasaban los
4tests anteriores. Las nuevas comprobaciones, derivadas del contrato fuente y
separadas de los120casos congelados, fallaron ante ambas mutaciones. Restaurar los
bytes exactos del backend dejó4/4GREEN. Ahora se observa invocation en un árbol
con error mediante extent canónico1..3 y se exige Invalid ante owners canónicos
.py/.jsx. Sólo cambiaron55líneas de tests; no hubo recaptura ni cambio de lógica.
El Minor diferido es la falta de un owner que seleccione específicamente el getter.

El [CI final40240899343](https://github.com/Infinibay/ken/actions/runs/40240899343)
**falló** en un AMD EPYC9V45. Contexto obtuvo7/8: el caso boundary511 volvió a
esperar-0.015078825876116753 y recibir0.15921735763549805. La suite de recuperación
obtuvo144/145: `full_original_dtype_dispatch_and_term_summary_observations`, caso
`product-float32-float32-float64-4-128-3/weighted`, obtuvo2.1855458146647404 frente
a2.1855457487859224. Los4tests de testigos nuevos pasaron también allí. Ettin pasó;
preferencias y la sonda aislada de testigos se omitieron por la dependencia fallida.
El job global mantuvo failure. Los sources de modelos/API/Cargo/alignment no
cambiaron frente al candidato anteriormente aprobado49bf56ce. La correlación con
el CPU distinto no demuestra la causa; falta comparar Python/Rust y baseline en el
mismo9V45, conservando suite completa y sólo el test registrado como observaciones
diferentes. No alterar tolerancias, modelos ni originales para obtener verde.

El CI anterior40240129308 se canceló al quedar reemplazado por las mejores pruebas;
se conservan metadata, logs y artefacto parcial. Corría en AMD EPYC7763, había pasado
las8raíces de contexto y fue interrumpido durante compilación de recuperación.
Nunca se acepta como ejecución completa. El paquete local inicial29b35d49 sí pasó
completo y se conserva separado del paquete final417453b7.

Task3 del plan sigue pendiente: la implementación y las pruebas locales están
completas, pero no hay aceptación remota de esta capacidad ni cierre M4/global.
El recibo verifica tanto los éxitos locales como el fallo remoto: un replay válido
de evidencia no convierte el resultado de CI en éxito. El siguiente trabajo es el
diagnóstico numérico en el CPU que falla; la implementación Python AST sigue después.

Recibo local `docs/validation/rust-migration-2026-10-25/syntax-operation-witnesses`:
3207miembros, FILES SHA256
`f3a6de5c599da2961a2a1f4a9db6220230707516426e8094f420a0d019db40fb`.
Transporte `.ken/rust-migration/archives/syntax-operation-witnesses-417453b7.tar.gz`,
127565131bytes, SHA256
`9b77142ebc9952948c253b007c174837e6df10a26b90e9a6f9e892caf0448358`.
Se autenticaron1261entradas locales y1261del CI fallido contra el candidato Git,
y305de gramáticas; datos históricos ignorados contra02a0e6b. El transporte extraído
en `/tmp/ken-syntax-witnesses-u1iyqxt3` pasó replay aislado con validadores archivados,
confirmando explícitamente los éxitos locales y los fallos/skips remotos.
`SyntaxOperationWitnesses_x86_64_accepted=false`, `ci_acceptance_pending=true`.
Los1066archivos originales siguen intactos. Raw, pesos,SDK,cachés y ambos workspaces
permanecen locales sin tracking, siguiendo la instrucción de conservarlos.

## Diagnóstico numérico x86 por entorno de ejecución

La investigación posterior a `c7889b1d` encontró coincidencia exacta de valores
entre el Python original y los callers Rust en los casos observados. Las
expectativas congeladas bajo Linux/x86_64 no son portables a todos los entornos
numéricos x86 observados. Esto no constituye aceptación global del modelo ni de
la migración; permite distinguir una divergencia del port de una variación que
el propio original también produce.

Se midieron tres casos de contexto (`empty-query`, `passage-boundary511`,
`passage-boundary512`) y el caso de alineamiento
`product-float32-float32-float64-4-128-3`. El adaptador Python original está
verificado por hash de fuente; se comparó con la sonda nativa y con sesiones ORT
Python por archivo/memoria, 1/2 hilos y dos repeticiones. Tokens, artefactos,
runtime nativo, dimensiones, tipos y resultados completos se verifican antes de
reconstruir la comparación. Las sondas reciben sólo entradas, nunca resultados
esperados. Los 1066 archivos congelados y las referencias previas siguen intactos.

En el primer diagnóstico, `a679e4f8` / CI40243860877, los runners fueron EPYC9V74
(AVX512/VNNI, OpenBLAS SkylakeX) y EPYC7763 (AVX2, OpenBLAS Haswell). En el 9V74,
Python y Rust producen el mismo valor ponderado `2.1855458146647404`, diferente
del congelado `2.1855457487859224`. En procesos nuevos, la intervención
`OPENBLAS_CORETYPE=Haswell` selecciona efectivamente Haswell y devuelve el valor
congelado en ambos lenguajes. En el 7763, ambas selecciones ya coinciden con el
congelado. Esta intervención demuestra el efecto de la selección del kernel
BLAS en el caso medido; no se aplica como política de producción.

En contexto, Python y Rust coinciden exactamente entre sí también en el 9V74,
aunque los vectores difieren de los congelados, incluido boundary511. Todos los
modos de carga/hilos observados coinciden. La intervención Haswell pertenece al
experimento de alineamiento: no demuestra ni corrige el mecanismo interno de ORT.
La atribución precisa a una instrucción/kernel de ORT continúa sin probarse.

La revisión independiente encontró 0 Critical, 2 Important y 0 Minor. Ambos
Important quedaron reparados en una sola pasada `f8d68146`, sin re-review:

- Los payloads incompletos podían pasar replay. Once clases de mutación de
  resultados, con hashes y resumen actualizados, fueron RED; ahora se exigen
  campos, dimensiones/dtypes, valores finitos, máximos, fuente, modo/hilos y
  runtime/core completos y coherentes.
- La procedencia de suites permitía un override de fixtures y checkouts
  cruzados. Las regresiones fueron RED; ahora se elimina y vigila
  `KEN_NUMERIC_REFERENCE_DIR`, cada rol declara revisión/directorio/target y se
  verifican sus nombres exactos de tests, command, cwd, target y exit real.

La comprobación de procedencia reveló además una contaminación concreta de Cargo:
tras compilar un baseline en un target compartido, ejecutar desde el candidato
podía reutilizar un test cuyo `CARGO_MANIFEST_DIR` seguía apuntando al baseline.
Se reprodujo con la fixture presente en el candidato, exit101 y el archivo `.d`
apuntando al otro checkout antes y después. Los targets independientes por rol
eliminan esa ambigüedad. El baseline recibe sólo el soporte histórico de selección
de plataformas, autenticado contra su SHA preservado; ello permite ejecutar las
8 raíces completas. No implica ejecutar ni revalidar binarios ARM/macOS.

Los datos v1 se preservan y sus observadores numéricos pueden verificarse con los
nuevos validadores de payloads. Su comparación de suites completas no se acepta
como prueba de procedencia: el baseline también carecía del soporte ignorado.
El formato v2 distingue esos datos históricos de las ejecuciones corregidas.

Localmente, las 37 pruebas del diagnóstico pasaron. Candidato `f8d68146` y
baseline aceptado `49bf56ce` pasaron sus tres comandos separados: contexto
completo (8 raíces), contexto filtrado (1 raíz) y alineamiento (4 raíces).
Los árboles/archivos de modelos, API nativa, matemática de alineamiento y Cargo
son idénticos entre ambas revisiones; los directorios y targets de ejecución
permanecen distintos.

El diagnóstico reforzado CI40244828414 vuelve a observar el EPYC9V45 que había
fallado en CI40240899343. En el mismo 9V45, Python original y Rust coinciden
exactamente en los casos medidos. Candidato y baseline fallan únicamente en los
mismos tests numéricos registrados: contexto completo 7/8, filtrado 0/1 y
alineamiento 3/4. Al repetirse también filtrados y en el baseline, las discrepancias
observadas no dependen del orden de las otras raíces ni de un cambio reciente del
port. Los exits101 y los vectores completos siguen siendo datos de fallo frente
a los congelados, no aprobaciones de esas suites.

El workflow de diagnóstico retorna éxito sólo cuando termina y valida sus
observaciones, incluso si un comando registrado de modelos retorna101. No
sustituye el workflow de modelos/búsqueda, que continúa fallando si cualquiera
de sus perfiles falla o se omite. Las referencias, tolerancias y modelos no se
modificaron; tampoco se fuerza un kernel antiguo para imitar otro CPU.

Siguiente capacidad: registrar referencias independientes del original por
perfil numérico de ejecución, con identidad de runtime/kernel y selección
verificada, conservando las referencias Haswell existentes. Usar sólo
`Linux/x86_64` para elegir una expectativa resulta demasiado amplio. Antes de
promover un perfil nuevo se necesita observar su corpus completo del original;
los tres casos de contexto y el caso de alineamiento de este diagnóstico no
prueban todos los inputs ni todos los CPUs.

Siguen pendientes la aceptación de CI del bloque CST, el backend Python AST,
OperationWitnesses completo, SymbolRanker/PieceSearch y M4/global. No se modifica
la aplicación instalada. Los raw, targets y worktrees de diagnóstico permanecen
locales fuera de Git según la instrucción de conservación.

El CI reforzado completo40244828414 terminó correctamente en ambas réplicas, con
37checks del diagnóstico aprobados en cada una. Un detalle importante: el EPYC9V74
de esta segunda época NO anunciaba AVX512/VNNI y seleccionó Haswell; allí todas las
suites de ambos checkouts pasaron y las mediciones coincidieron con el congelado.
El EPYC9V45 sí anunciaba AVX512/VNNI y seleccionó SkylakeX; mostró las diferencias
compartidas por Python/Rust descritas arriba. El primer 9V74 sí anunciaba AVX512.
Por tanto, tampoco basta el nombre comercial del CPU: importan las capacidades
expuestas al proceso y el kernel realmente seleccionado. Las épocas se conservan
por separado y ninguna observación se elige por obtener un gate numérico verde.

Recibo local `docs/validation/rust-migration-2026-10-25/x86-numerics`: 917 miembros,
578 archivos de fuentes autenticados por blob Git y SHA256. FILES SHA256
`ff2c2370179f99b619502ddf396568c46d4cad9e4d4bdcccac8fcba00a504c51`.
Transporte `.ken/rust-migration/x86-numerics/x86-numerics-f8d68146.tar.gz`,
17420031 bytes, SHA256
`ff3cfe5fa9f901c246928834d25b317a20649020a93542ca4c8150466c0e7b0a`.
La extracción `/tmp/ken-x86-numerics-r1p92ud2` pasó replay aislado con validadores
archivados. Su estado dice `diagnosis_tooling_complete=true`,
`model_acceptance=false`, `CST_CI_acceptance=false`, `migration_complete=false`.
Las cuatro réplicas de ambas épocas se conservan: la segunda época corrige
instrumentación, no repite ejecuciones buscando un gate numérico verde.

## Referencias numéricas por perfil de ejecución x86_64

La implementación usa un registro inmutable para elegir referencias originales
según las capacidades efectivas expuestas al proceso y el backend BLAS realmente
cargado. El nombre comercial del CPU y la arquitectura por sí solos no eligen la
referencia. Contexto y alineación son ejes separados; los perfiles desconocidos,
ambiguos, con referencias alteradas o con un runtime distinto se rechazan.
La política de un hilo para BLAS se fija solamente en el entorno de validación.
No cambia la aritmética de producción, los modelos ni las tolerancias.

El CI original40248728038/86e6f7af capturó cuatro observaciones completas antes
de implementar la selección nativa. Junto con la primera captura local, fueron
20 historiales de contexto y245 casos de alineación por observación, usando las
1066 fuentes Python congeladas con fingerprint
`5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038`.
Los datos Haswell coinciden exactamente con las referencias anteriores: se
mantienen sus bytes y se referencian directamente desde el registro. Las
observaciones AVX512/SkylakeX suplementan los datos anteriores. No se reejecutaron
las raíces pytest originales ni se generaron referencias con resultados Rust.

El primer CI de integración40250394146/66a01448 tuvo una réplica completa
aprobada y otra rechazada por un descriptor contextual desconocido. Esta última
no conservó su descriptor debido al orden de escritura del diagnóstico; por lo
tanto su perfil sigue siendo desconocido y no se atribuye retroactivamente a
ninguna captura posterior. Se conserva la ejecución fallida.

Una revisión independiente única encontró cuatro problemas Important, reparados
en una sola pasada RED→GREEN: autenticar el inventario1066 recalculando su
fingerprint; comprobar los bytes exactos del observador de alineación retenido;
guardar capacidades/CPU antes del rechazo; y vincular el descriptor ORT al
registro autoritativo y al runtime nativo autenticado antes de comparar números.
No quedaron hallazgos Critical/Important/Minor abiertos. La revisión no certificó
las ejecuciones todavía pendientes: su evidencia se verificó separadamente.

Se amplió explícitamente el presupuesto con una sola tanda original adicional de
cuatro runners, CI40251490215/ad8ec094. Dos detectaron perfiles conocidos y no
repitieron mediciones originales. Dos encontraron el mismo perfil nuevo,
`4fd097c7c15ded15e3459b7ae1aabe90f9d2c6d3618857ae0be8e4f51bb6a1f0`:
AVX512/VNNI disponible, AVX_VNNI ausente. Sus20 historiales completos y245 casos
coincidieron entre sí. Los valores contextuales coinciden exactamente con la
referencia moderna existente, por lo que el nuevo descriptor la referencia sin
duplicar el archivo. Quedaron tres perfiles contextuales y dos de alineación.
El presupuesto de captura de esta etapa está consumido; no repetir buscando un
CI verde. Conservar todas las capturas y rechazos.

La versión de código final es `d49be5af60736ea8f4c2f33e4c232c437da117fc`.
Los paquetes registran el perfil antes de los cálculos; Rust detecta sus propias
capacidades y su BLAS independientemente. El replay usa las identidades grabadas,
sin detectar la CPU del equipo que verifica el archivo. Los snapshots incluyen
el registro, referencias, helpers y herramientas. La documentación de la tanda
previa que declaraba pendiente el bloque numérico queda superada solamente en el
alcance que confirmen los paquetes finales de esta sección.

La cadena final local y el CI40251790898 aprobaron todos los bloques con la
misma versión de código:505 raíces de herramientas y195 raíces nativas por host,
más formato y Clippy. Las dos réplicas de CI aprobaron contexto/Ettin/vistas/
preferencias/CST, sin ignorar errores numéricos. Los hosts finales ejercitaron
contexto22ec (Haswell) y4fd (AVX512), y ambos perfiles de alineación. El descriptor
582 sigue registrado por sus observaciones originales completas, pero no fue
seleccionado por los hosts de esta última tanda nativa; STATUS lo identifica
explícitamente y no certifica una ejecución completa adicional para ese perfil.

Recibo local `docs/validation/rust-migration-2026-10-25/execution-profiles`:
2847 miembros,1286 fuentes autenticadas por Git. FILES SHA256
`c52c2bdb14237d4e77f822de5367613f22df337556590da5325e7c03e2e26cb4`.
Transporte `.ken/rust-migration/archives/execution-profiles-d49be5af.tar.gz`,
218119397 bytes, SHA256
`b535c28b03613d7cb880efdd32d0c6056a3c6305d2e670f88e10d47024f7417c`.
La extracción `/tmp/ken-execution-profiles-zm4pg7sk/execution-profiles` pasó
replay aislado con sus propias fuentes y validadores, verificando los tres
paquetes, las siete observaciones originales y todos los orígenes del registro.
No requiere detectar la CPU del replay ni usar el checkout vivo.

El estado declara `execution_profile_validation_complete=true`,
`CST_CI_acceptance=true`, `M4_accepted=false`, `migration_complete=false`.
La aceptación es la de los hosts y el alcance declarados; los perfiles futuros
sin registrar siguen siendo errores. Todos los recibos y workspaces quedan
locales y fuera de Git, como pidió el usuario.


La siguiente etapa de este documento incorpora el backend Python AST y el
router de operaciones. Siguen pendientes SymbolRanker/PieceSearch completos,
otros modelos y la aceptación M4/global.
La portabilidad de índices entre perfiles y las políticas arbitrarias de hilos
de producción no quedan aceptadas por esta validación. El trabajo sigue acotado
a Linux x86_64; no se cambia la aplicación Python instalada ni se certifica ARM/macOS.

## Backend Python AST y router de operaciones

Rust incorpora PythonOperationWitnesses sobre las instantáneas inmutables del
catálogo y OperationWitnesses como selector de Python, CST y archivos sin backend.
La implementación observa invocaciones, causas de excepciones, escrituras con
snapshot de clave y renovación de flags devueltos; conserva la pertenencia de los
owners, los límites de funciones/clases/lambdas, la adyacencia AST y las cachés.

Se conservaron tres tandas originales independientes de Python 3.12.9:
154 casos iniciales/166 entidades, 31 casos adicionales y 33 casos de revisión.
Los 218 casos/230 entidades coinciden, incluyendo las equivalencias ast.dump,
NFKC/Unicode15, cadenas/bytes/surrogates, f-strings, decoradores, admisión y límites.
El router también conserva los 120 casos CST anteriores. No se repitieron las
raíces pytest originales ni se reemplazaron sus resultados con salidas Rust.
Las 1066 fuentes originales mantienen el fingerprint
`5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038`.

Una única revisión independiente encontró seis diferencias Important; se
corrigieron en una sola pasada RED→GREEN: backslash antes de interpolación,
propagación del kind Unicode desde literales vacíos, newline en format spec de
comillas simples, BOM, tabs de ocho columnas y límites de enteros/anidamiento.
No quedaron hallazgos Critical/Important/Minor de esa revisión pendientes.
Ruff 0.15.8 usa los pins Unicode existentes; dos parches de lexer son explícitos y
reversibles. Las pruebas reconstruyen y autentican todos los bytes upstream,
además de verificar licencia, requests sin respuestas y procedencia Git.
La suite afectada local pasó 182 pruebas, formato y Clippy estricto.

La versión `d3a47eb38018cb9a9d8ceb855c743490337eed70` pasó la cadena local
completa, y las dos réplicas del
[CI 40611631533](https://github.com/Infinibay/ken/actions/runs/40611631533)
aprobaron la misma versión: 532 pruebas de herramientas y 198 nativas por host,
con formato y Clippy. Se verificaron los paquetes descargados, sus inventarios
y su vínculo con las fuentes, además del estado del workflow. La primera época 7bacb189
(local y CI 40610175928) se conserva separadamente y queda superada por la
reparación semántica; no prueba los nuevos 33 casos.

Recibo local `docs/validation/rust-migration-2026-10-27/python-operation-witnesses`:
3136 entradas verificadas, más `FILES.json`. El snapshot contiene 1324 archivos
de código/herramientas autenticados por Git; otros cinco archivos de diseño y
soporte tienen sus pruebas Git separadas. Se incluyen las 1066 fuentes originales,
las tres tandas de observaciones, los dos paquetes CI, el paquete local y los
logs RED→GREEN. El soporte contextual heredado se incorpora desde su snapshot
propio; su referencia histórica conserva el SHA fijado por el verificador.
FILES SHA256 `f87db4e0e01e4f347ec6b082114d0702b618b3c8e1c94161bbfe9b6d2c8e9eb1`.

Transporte `.ken/rust-migration/archives/python-operation-witnesses-d3a47eb3.tar.gz`,
246281910 bytes, SHA256
`232f4979e8599c6a2dbd4bbd8122969fbc69f3f463ff3a8707402cb93d8b6de7`.
La extracción `/tmp/ken-python-witnesses-375rlrf1/python-operation-witnesses` pasó el replay con Python `-I -B`,
sin importar validadores del checkout vivo ni detectar la CPU del replay.
Se validan los tres hosts, ambos perfiles efectivamente observados (22ec/4fd),
las referencias originales, fuentes Git, inputs sin respuestas, binarios,
resultados y gates completos. El descriptor 582 permanece registrado; no fue
seleccionado por los hosts de esta tanda.

El estado declara `python_operation_witnesses_accepted=true`,
`M4_accepted=false`, `migration_complete=false`.

Decisiones y límites de esta etapa:
- Se eligió una proyección explícita de AST CPython sobre Ruff, porque CST y
  ComparableExpr no preservan esa identidad; la aceptación depende de la
  conformidad observada, sin certificar todo input o condición extrema.
- Se capturaron solo casos originales nuevos, sin repetir pytest original;
  esta etapa no constituye una ejecución nueva de esas suites históricas.
- Se mantuvieron los pins Unicode existentes al vendorizar el parser; las
  diferencias con su paquete publicado requieren comprobación de compatibilidad.
  Sus snapshots no usados y el archivo original se conservan localmente.
- El probe transforma únicamente campos de presentación sintéticos vacíos en
  cinco strings vacíos; no certifica presentación de esos catálogos sintéticos.
- Tres lints de estilo upstream se permiten solo en el manifiesto vendorizado;
  el Clippy estricto del código propio permanece activo.
- Dos parches reversibles de lexer corrigen tabs y formatos multilínea; se
  mantiene un fork que exige revisar esos parches al actualizar el parser.

La revisión no certificó ejecuciones todavía pendientes: su cierre se comprobó
separadamente con los paquetes y el replay. No se ejecutó la suite upstream del
parser ni pruebas arbitrarias de agotamiento de pila. La decisión de integración
sigue siendo conservar y subir la rama de migración autorizada.

La siguiente etapa incorpora SymbolRanker. Siguen pendientes PieceSearch completo,
otros modelos y la aceptación M4/global. No se declara completada la migración ni certificación
ARM/macOS, configuración arbitraria del parser/hilos o agotamiento extremo de
pila. La aplicación Python instalada permanece como estaba. Todos los crudos,
recibos y workspaces se mantienen locales y fuera de Git.

## SymbolRanker completo y descripciones compartidas en Rust

Rust incorpora `SymbolRanker` para componer las vistas neuronales, la evidencia
operacional y las preferencias estables de símbolos. Conserva el top 10, los
scores, el fallback de código completo, las llamadas al modelo y las prioridades
operación/test/operador. Los requisitos interpretan el request original y el
modelo recibe la consulta expandida. `OwnerDescriptions` vincula síntesis y
caché a un catálogo; el ensamblador y el ranker reutilizan las mismas instancias.

Se capturaron 36 casos nuevos del SymbolRanker Python congelado antes de la
implementación: 33 con un modelo controlado y tres con Ettin real, cada uno frío
y caliente, con resultados, llamadas y descripciones. No se repitió pytest
original ni se modificaron referencias previas. La primera captura falló por un
selector Java de un método sin región exclusiva en una clase de una línea; se
conservó completa como intento fallido. La captura corregida usa cuerpos en
líneas separadas y guarda cada observación en un journal antes de seguir.

Una revisión independiente encontró un Important: el accessor mutable de caché
permitía reemplazarla por la de otro catálogo con iguales keys/hashes y distinta
metadata. La regresión pública reprodujo el problema y pasó tras añadir el guard
al ensamblador, conservando la prioridad del error de límite inválido. No quedaron
hallazgos Critical/Important/Minor de esta revisión pendientes. Se hizo una sola
pasada de reparación, sin re-review. La suite completa de core/búsqueda pasó
153 raíces descubiertas, formato y Clippy estricto. No se suman summaries de
subprocesos para contar raíces.

La versión `d78d83138595177920dc430e0e543e91b044fc5b` pasó la cadena local
completa: 557 pruebas de herramientas y 202 nativas, formato y Clippy. El
[CI 40620639879](https://github.com/Infinibay/ken/actions/runs/40620639879)
aprobó sus dos réplicas sobre la misma versión: 557 pruebas de herramientas y
202 nativas por host. Los paquetes descargados también pasaron la verificación
independiente de fuentes, resultados, llamadas y gates completos. La primera
época bd8c81da/local y CI40619691674 quedó interrumpida tras el hallazgo de revisión;
sus artefactos parciales y metadata se conservan y no establecen aceptación.

Recibo local `docs/validation/rust-migration-2026-10-27/symbol-ranking`:
2989 entradas verificadas, más `FILES.json`, con 1334 archivos de código y
herramientas autenticados por Git, cinco archivos adicionales de diseño/soporte
con pruebas Git separadas y las 1066 fuentes originales. Se conserva la captura
completa, su journal, el intento fallido y los logs de la regresión. Los binarios
de modelos preparados y las cachés de los originales permanecen en sus directorios
locales originales; el recibo conserva sus identidades y verifica las
observaciones, sin reejecutar esos modelos.
FILES SHA256 `9f84ee4c57452af33aebfaf9f28b11a189cf55c4883730de113ea8a6d33b547a`.

Transporte `.ken/rust-migration/archives/symbol-ranking-d78d8313.tar.gz`,
204296848 bytes, SHA256
`1f1b2ae25a776961f2e07dd8483e258e6a3742e82bfcb11c70e83a30dee76124`.
La extracción `/tmp/ken-symbol-ranker-rqw6536e/symbol-ranking` pasó el replay con Python `-I -B`,
usando únicamente sus validadores y fuentes archivados. Comprueba los tres
hosts, las 36 composiciones, los tres frames reales, los originales, los recursos
nativos y todos los prerrequisitos. Los perfiles se eligen por sus registros,
sin detectar la CPU del equipo del replay.

El estado declara `symbol_ranker_accepted=true`, `M4_accepted=false`,
`migration_complete=false`.

Decisiones: composición reutilizando los componentes aceptados; keys canónicas
como entrada en lugar de tarjetas de presentación; una caché con procedencia
estricta, no un diccionario externamente sembrado; un modelo compartido con Rc
sobre el hilo actual, sin ampliar el contrato Send/Sync; capturas previas
inmutables y ningún cambio numérico. La validación de formas de tarjeta y
presentación corresponde al futuro PieceSearch. No se acepta concurrencia,
benchmarks ni paridad con los comportamientos inseguros de caché/NaN del original.

Siguen pendientes PieceSearch completo, otros modelos y la aceptación M4/global.
El foco sigue siendo Linux x86_64; la aplicación instalada continúa en Python.
Todos los datos crudos, recibos y workspaces se conservan localmente y fuera de Git.

## PieceSearch completo en Rust sobre Linux x86_64

`PieceSearch` compone tarjetas, ensamblado y descripciones compartidas,
`PieceReranker`, `SymbolRanker`, fusión y presentación. Conserva los diez
candidatos nativos antes de aplicar límites de visualización, el ranking numérico
en modo exacto sin llamadas neuronales y la promoción estable final de la ruta
solicitada. Las señales de explicación se asignan por identidad a los resultados
que sobreviven al recorte. El accessor de descripciones es de solo lectura;
los guards de procedencia de catálogo de ambos consumidores permanecen activos.

La referencia comprende 45 casos nuevos del API Python original congelado:
42 con modelos controlados y tres con Ettin real, cada uno frío/caliente,
con respuesta, llamadas y caché. Se observaron primero 41 casos y luego cuatro
consultas nuevas que comienzan con `Find ruta`, para cubrir la sintaxis real de
ruta explícita; no se repitieron las 41 observaciones ni pytest original.
Cada fila está guardada en su journal y la referencia combina ambos grupos.
Las referencias anteriores, modelos y tolerancias no cambiaron.

Se conserva una particularidad del original: `present_cards` recorta antes de
agregar las señales de `explain`. La observación con presupuesto de 650 devuelve
una respuesta final de 847 caracteres; la de 1400 llega a 2908. Esta etapa conserva
ese contrato, no redefine el presupuesto. Los scores neuronales incompletos o
no finitos se rechazan antes de indexar.

La revisión independiente de f41ca7ed no encontró Critical/Important/Minor ni
conductas declinadas. El gate completo posterior detectó una omisión de recursos
del probe: el ranking numérico aislado requería los tres sidecars BLAS, ausentes
en la primera captura. Se agregó la preparación existente y la autenticación de
las tres identidades y la ruta de carga real. Una regresión falló sin los recursos
y pasó con la corrección; el preflight corregido coincidió en los 45 casos.
No hubo cambios Rust, numéricos o de originales en esa reparación ni re-review.
La época local f41ca7ed queda fallida; CI 40627223040 fue cancelado y ambos
artefactos parciales se conservaron. Ninguno establece aceptación.

El código 4d88c8379b61c3570ff1cea5bcc31ac924d84619 pasó la cadena local completa y las dos réplicas del
[CI 40628141649](https://github.com/Infinibay/ken/actions/runs/40628141649):
586 pruebas de herramientas y 206 nativas por host, con formato y
Clippy estricto. La suite de core/búsqueda contiene157 raíces únicas descubiertas;
no se suman summaries retransmitidos por subprocesos. Los paquetes descargados
pasaron la verificación independiente de fuentes, recursos, respuestas y gates.

Recibo local `docs/validation/rust-migration-2026-10-28/piece-search`:
3195 entradas más `FILES.json`, 1343 fuentes de código/herramientas
vinculadas al commit por pruebas Git, cinco archivos adicionales de diseño/soporte
autenticados y las 1066 fuentes originales. FILES SHA256 `0ef733373775722bf63bc39aa187e0bbaebf7bd61e2bc211e824fbf3082dc3e1`.
Los modelos originales preparados y las cachés de sus entornos permanecen en
sus directorios locales; el recibo conserva identidades y observaciones, sin
reejecutar esos modelos. Incluye ambos journals, el fallo aislado inicial y los
paquetes parciales de CI.

Transporte `.ken/rust-migration/archives/piece-search-4d88c837.tar.gz`,
239142622 bytes, SHA256 `28e439eb5954eb101f727cb2108ffc7089e171b2f1eafe75cf34542ba1d79d0a`.
La extracción `/tmp/ken-piece-search-final-b7rbt9mo/piece-search` pasó el replay con Python `-I -B`, usando únicamente
los validadores y las fuentes archivados. Verifica los tres hosts, las 45
composiciones, los tres frames reales y todos los prerrequisitos; elige perfiles
por sus registros y no por la CPU del equipo del replay.

Esta tanda seleccionó los perfiles contextuales `22ec` y `4fd`, y los de
alineamiento `66669` y `1f613`. El perfil registrado `582` no fue seleccionado
por estos hosts; `4fd` reutiliza su referencia según el registro aceptado.

Estado: `piece_search_accepted=true`, `M4_accepted=false`,
`migration_complete=false`. La siguiente integración es `BestSearch`: recursos,
preparación y caché por generación, camino exacto y recuperación contextual.
Continúan pendientes otros modelos y la aceptación M4/global, además de M5–M8.
La aplicación instalada sigue en Python. Todos los crudos, recibos y workspaces
se conservan localmente y fuera de Git.


## BestSearch implementado: diagnóstico SkylakeX pendiente

El código `7dc69841679df405ed938091d1b5855a37472603` incorpora `ken-search`,
recursos diferidos, bootstrap/ruta exacta, recuperación contextual y una caché
LRU de dos proyectos vinculada a base, raíz, generación y perfil. Las conexiones
SQLite sin nombre no reutilizan el estado de otra base en memoria. La preparación
contextual conserva el caché SQLite, las identidades ASCII del original y matrices
NPY de solo lectura. El header se admite antes de construir dtypes o calcular
productos que puedan desbordarse. Las escrituras preceden al snapshot de consulta.

Las referencias nuevas conservan 29 historias de preparación y 37 de BestSearch,
34 controladas y tres composiciones reales Potion/contexto/Ettin en inglés.
La primera captura aportó 16 historias válidas; solo se corrigieron y observaron
las 21 controladas que fallaron por un contador de tokens inexistente. Ambos
observadores y sus journals permanecen intactos. No se repitieron originales
aceptados ni se cambiaron modelos o tolerancias anteriores.

La cadena local completa y la réplica 2 del
[CI 40716215155](https://github.com/Infinibay/ken/actions/runs/40716215155)
pasaron 640 pruebas de herramientas y 272 nativas por host, formato y Clippy.
Ambos paquetes se verificaron de nuevo contra las fuentes de ese commit.
Seleccionan contexto `22ec4aa2...` y alineamiento `66669ec8...` (Haswell).
El primer intento local falló por enlaces duros entre filesystems; se conservó
como `packet-cross-device-7dc69841` y la repetición completa usa un TMPDIR privado
fuera del checkout, en el mismo filesystem. Las mutaciones reemplazan archivos
atómicamente y no pueden modificar el paquete fuente por un enlace compartido.

La réplica 1 selecciona contexto `4fd097c7...` y alineamiento `1f613df1...`
(SkylakeX). Pasó los ocho perfiles padres, pero falla la comparación exacta de
`piece_score`: Rust devuelve `-2.3249518584644573` y la referencia observada en
Haswell contiene `-2.3288574266118545`. Esto no establece todavía si hay un fallo
nativo o una diferencia del original por perfil. No se amplían tolerancias ni se
reemplaza el fixture para convertir el gate en verde.

`8941b1abfbe400ce201935430f89a3ee63e9d554` añade el
[diagnóstico 40722479532](https://github.com/Infinibay/ken/actions/runs/40722479532):
solo permite observar las tres composiciones completas todavía no observadas en
ese par exacto de perfiles SkylakeX. Otro hardware termina antes de ejecutar
originales o preparar modelos; los dos primeros intentos omitieron correctamente
Haswell. El tercero recibió SkylakeX con contexto `582ea68b...` (AVX-VNNI distinto)
y también omitió la observación: sigue sin ser el par exacto que falló. Los tres
intentos terminaron sin ejecutar originales. Se agotó el límite de tres intentos
de asignación; no hubo nuevas observaciones que comparar. La próxima reanudación
necesita el perfil exacto `4fd097c7...`/`1f613df1...` antes de cambiar expectativas.
La evidencia independiente debe decidir entre reparar la implementación y añadir
expectativas separadas por perfil. El workflow no declara aceptación.

Los paquetes y ZIPs con digests de GitHub verificados están en
`.ken/rust-migration/best-search/`: `packet`, `ci-7dc-attempt-1`,
`ci-7dc-attempt-2` y `profile-diagnostic-attempt-*`. El ledger completo y los
scripts de cierre todavía condicionales están en
`.superpowers/sdd/2026-10-28-rust-best-search/`. No ejecutar el sellado como si
las tres plataformas hubieran pasado: la aceptación y el transporte final siguen
pendientes del diagnóstico. Las épocas fallidas anteriores también se conservan.

La única revisión encontró dos Important (admisión NPY y filtros CI), reparados
con RED→GREEN dentro de la única pasada de corrección; no hubo re-review.
La preparación registrada en español sigue sin aceptar: dos pruebas CT2 exigen
una plataforma ARM registrada. Pasaron 42/42 pruebas elegibles de modelos, no
44/44. CT2/expansión x86 es el siguiente bloque después de resolver BestSearch.
M4/global y M5–M8 permanecen pendientes; la aplicación instalada continúa en Python.
