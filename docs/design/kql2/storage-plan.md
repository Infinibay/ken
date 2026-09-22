# Almacenamiento estructural y migraciones

**Plan, no implementación.** [Plan principal](implementation-plan.md).

La aclaración posterior del modelo central está en [AST común y contextos](common-ast.md):
AST nativo → AST común persistido, enriquecido por ámbitos y relaciones semánticas.
El schema ejecutable actual llega a versión 6 e incluye AST común, scopes,
símbolos/referencias e índices. Las tablas y límites restantes propuestos aquí
no quedan implementados automáticamente por esa proyección.

## 1. Archivos y propiedad de los datos

```text
.ken/ken.db                         # base principal existente: conservar
.ken/structural-cache.sqlite        # caché KQL 1: compatibilidad/retirada separada
.ken/structural/v2/store.sqlite     # nuevo grafo, unidades y artefactos KQL 2
.ken/structural/v2/store.sqlite-wal # overhead de transacciones cuando haya WAL
.ken/structural/v2/store.sqlite-shm # estado auxiliar SQLite, no datos para copiar solos
.ken/structural/work/<request-id>/  # archivos temporales de evaluación/rebuild
.ken/structural/migrations/        # manifiestos de transición/recuperación
```

Todos los paths nuevos son propuestos. La DB estructural pertenece a un proyecto,
identificado por UUID y root canónico; no comparte term IDs entre proyectos.
Las reglas propias/TOML/.kql permanecen fuera del almacén descartable. Los
artefactos compilados son derivados de esos archivos y sus hashes.

| Dato | Política |
|---|---|
| Memorias, sesiones, interacciones, configuración y reglas propias | Preservar; fuera del ámbito de DROP estructural |
| Índices `ci_*`, vectores y FTS principales | No tocarlos en esta migración; tienen consumidores existentes |
| IR KQL 1 comprimido y resultados antiguos | Reconstruibles; conservar mientras se use el dialecto anterior o retirar explícitamente |
| Grafo KQL 2, estadísticas, planes y resultados | Reconstruibles y evictables conforme al presupuesto |
| Snapshots activos en consultas | Fijados mientras se usan; no borrar por migración/GC |

No hacer una migración global «drop todas las tablas y up». El cambio completo
de schema se permite **dentro del almacén estructural dedicado**, con una lista
cerrada de objetos propios y un procedimiento de recuperación.

## 2. Versiones independientes

Guardar y validar al abrir:

* `storage_epoch`: familia de formato, inicialmente `2` para este nuevo almacén.
* `schema_version`: número secuencial de migración dentro del epoch.
* `ir_contract`: contrato de entidades/análisis; no inferirlo de schema_version.
* `frontend_fingerprint`, `model_fingerprint`, `analysis_profile` por artefacto.
* `compiler_semantics` y `optimizer_revision` por plan; dialecto por query.
* `project_uuid`, `application_id` y checksum del schema reconocido.

`PRAGMA user_version` refleja schema_version; el ledger conserva historial y
checksums. Una versión futura desconocida se rechaza, no se resetea automáticamente.
Un cambio de modelo semántico puede invalidar datos sin cambiar tablas. Un cambio
de índice puede cambiar schema sin invalidar el significado de los datos.

## 3. Modelo de persistencia

Un **unit** es el resultado inmutable de parsear/lower un archivo con bytes,
lenguaje, path y frontend determinados. Un **segment** es un conjunto inmutable
de hechos fuente o derivados con dependencias explícitas. Un **snapshot** selecciona
units y segments que forman una revisión del proyecto/perfil. No duplicar cada
unidad sin cambios al publicar un snapshot nuevo.

Tablas propuestas; PK = clave primaria, UQ = restricción única. Nombres/campos
son el contrato inicial a convertir en DDL durante S10/S11, no DDL ejecutado aquí.

| Tabla | Campos y claves principales | Propósito |
|---|---|---|
| `k2_meta` | `key PK, value` | Identidad, formato y puntero published snapshot |
| `k2_migrations` | `version PK, checksum, applied_at, application_version` | Ledger de migraciones confirmadas |
| `k2_units` | `unit_id PK, path, language, source_hash, frontend_hash, ir_contract, status, diagnostic_ref`; UQ de identidad completa | Parse/lowering por archivo |
| `k2_segments` | `segment_id PK, segment_key UQ, kind, producer, profile_hash, state, logical_bytes` | Hechos agrupados y evicción/invalidez |
| `k2_unit_segments` | `(unit_id,segment_id) PK` | Segmentos fuente de una unidad |
| `k2_snapshots` | `snapshot_id PK, parent_id, manifest_hash, model_hash, profile_hash, state, coverage_state, created_at` | Revisión inmutable; state y cobertura separados |
| `k2_snapshot_units` | `(snapshot_id,path) PK, unit_id, source_status` | Manifiesto completo, incluidos archivos fallidos/omitidos |
| `k2_snapshot_segments` | `(snapshot_id,segment_id) PK, role` | Materializaciones que esa revisión puede utilizar |
| `k2_terms` | `term_id PK, tag, canonical BLOB`; UQ `(tag,canonical)` | IDs enteros para entidades y valores escalares tipados |
| `k2_nodes` | `term_id PK/FK, unit_id, local_uid, kind, owner_tid, scope_tid, name_tid, start_byte, end_byte`; UQ `(unit_id,local_uid)` | Entidades fuente/canónicas y spans |
| `k2_relations` | `relation_id PK, name UQ, arity, signature, contract_version` | Schema tipado de relaciones |
| `k2_edges` | `edge_id PK, segment_id, relation_id, subject_tid, object_tid, modality`; UQ de esos cinco campos | Camino rápido para relaciones binarias |
| `k2_tuples` | `tuple_id PK, segment_id, relation_id, tuple_key BLOB, modality`; UQ de esos cuatro campos | Relaciones de otras aridades sin convertir todo en binario |
| `k2_tuple_args` | `(tuple_id,position) PK, term_id` | Argumentos tipados de cada tupla |
| `k2_evidence` | `proof_id PK, segment_id, origin_kind, payload_ref` | Pruebas con origen y spans |
| `k2_edge_proofs`, `k2_tuple_proofs` | `(edge_id,proof_id) PK` / `(tuple_id,proof_id) PK` | Una afirmación con múltiples pruebas |
| `k2_coverage` | `coverage_id PK, segment_id, subject_tid, relation_id, scope_key, status, profile_hash, proof_id` | Completitud por sujeto/relación/ámbito, incluso sin hechos |
| `k2_dependencies` | `(consumer_segment,dependency_kind,dependency_key) PK, dependency_hash` | Dependencias positivas y universos observados |
| `k2_statistics` | `(segment_id,stat_key) PK, value, sampling_info, revision` | Conteos/NDV/histogramas, nunca evidencia de ausencia |
| `k2_artifacts` | `artifact_key PK, kind, dependency_hash, codec_version, payload, payload_bytes, last_used` | AST compilado/plan/resultados opcionales |

FKs activas para términos, unidades, segmentos y snapshots, con política explícita
de borrado. Referencias globales/entidades externas tienen nodos internados con
proveniencia de modelo, no `unit_id` falso; unit_id puede ser NULL sólo en esa
clase de nodo, con constraint y namespace externo en la identidad.

Las constraints que SQLite no puede expresar sin coste excesivo (aridad, firma
de posiciones, pertenencia de term al snapshot) se validan por lote antes de sellar
segmentos. No habilitar un segmento parcialmente escrito para los lectores.

### Términos y scalars

`tag` diferencia EntityRef, String, Int, Float, Bool, Enum y TypeRef, entre otros.
`true`, `1`, `"1"`, null fuente y dato desconocido no son el mismo valor.
Dato desconocido vive en conocimiento/coverage, no se almacena como string
`"unknown"` que coincida con cualquier término. El tipo fuente unknown sí es TypeRef.

`canonical` es una codificación binaria determinista versionada. Las UQ comparan
la codificación completa; hashes aceleran búsquedas, pero una colisión de hash no
unifica entidades. Preservar anchura/signo de tipos fuente, NaN/inf cuando existan
y separar representación de igualdad de búsqueda según el contrato de cada tipo.
Los term IDs internos no son IDs públicos estables entre rebuilds. La salida
expone identidad lógica + revisión; no promete conservar el entero físico.

### Relaciones calientes y atributos

No guardar todo en un JSON de atributos que requiera descomprimir cada nodo.
`kind`, owner/scope, nombre y spans tienen columnas; propiedades escalares menos
frecuentes usan una tabla tipada `k2_properties(segment_id,subject_tid,key_id,value_tid)`
con UQ e índices definidos en [índices](cache-index-plan.md).

Relaciones frecuentes de más de dos argumentos pueden tener proyecciones físicas
`k2_reads`, `k2_writes`, `k2_arguments`, `k2_cfg`, definidas por schema con columnas
tipadas. Son materializaciones del contrato relacional, no otra fuente de verdad.
Se generan y verifican junto al segmento; si no existen el reader usa tuplas.
No crear una tabla específica `builder` o `singleton` para ocultar heurísticas.

Los atributos que cambian el significado no son sólo evidencia: una guarda,
contexto de llamada o rama que condicione un hecho forma parte de su identidad
lógica. Usar una relación n-aria que incluya ese contexto, o una proyección con
clave equivalente. No reducir un hecho contextual a `(subject,relation,object)`
y guardar la guarda únicamente en `proof`: se podrían unir ramas incompatibles.
El adaptador de Fact debe clasificar cada atributo como argumento semántico,
propiedad escalar o procedencia, y verificar ese mapeo mediante roundtrip.

Blob comprimido se reserva para payload frío: árbol de sintaxis serializable,
evidencia extensa o plan. Nunca persistir objetos Tree-sitter/Python con pickle.
No se necesita guardar el código fuente completo; si no hay bytes de la revisión
para mostrar un snippet, devolver hash/span y «fuente no disponible», sin mostrar
texto de una revisión diferente. Una query que necesita texto exacto lo debe fijar
en el snapshot como recurso requerido.

## 4. Escritura y publicación

1. Capturar manifiesto de paths y hashes de bytes leídos, incluyendo omitidos y
   fallidos. Construir sobre esos bytes; un watcher event no prueba su identidad.
2. Reutilizar units por clave exacta. Parsear cambios fuera de la transacción larga
   del writer, sin ejecutar el programa; workers entregan lotes inmutables.
3. Un writer coordinado inserta unidades/segmentos en transacciones acotadas.
   Estado `staging`; lectores no los incluyen por defecto.
4. Resolver/enlazar y producir análisis. MVP: recalcular todos los segmentos
   globales al cambiar el manifiesto; optimizar dependencias después de demostrar
   equivalencia con rebuild. Fuentes sin cambios no se reparsan.
5. Validar FKs, identidad, firmas, coverage, hashes y proyecciones. Sellar segmentos.
6. Publicar snapshot y cambiar puntero activo en **una transacción**, con comparación
   de `expected_parent`. Si otro writer publicó, rebase/reintento o descarte,
   nunca mezclar revisiones. Snapshot `sealed` no implica coverage completa.
7. Consultas existentes conservan el snapshot que adquirieron; nuevas ven el nuevo.
   GC posterior elimina sólo componentes no referenciados ni fijados.

El aislamiento SQLite no congela el filesystem. Si cambian archivos durante la
captura, el modo «live consistente» reintenta un manifiesto; si no estabiliza,
reporta `source_changed`/incomplete. Un snapshot histórico capturado explícitamente
puede consultarse por sus hashes, sin afirmar que es el HEAD/live actual.

## 5. Lectores, writers y mantenimiento

Conexiones independientes por worker; un writer de publicación/mantenimiento,
read transactions cortas y handles que fijan snapshot/segmentos a nivel de aplicación.
No compartir un cursor mutable entre threads. Empezar con WAL en filesystem local,
busy timeout y foreign_keys verificados, no sólo enviados como PRAGMA.

Las consultas largas no deben sostener indefinidamente un read transaction que
impida checkpoint: cargar lotes de segmentos inmutables mientras un lease lógico
evita su GC. Lease usa proceso+nonce/start identity y heartbeat; el mantenimiento
no elimina pins de un proceso vivo sólo porque una query tarde. Para migración
destructiva, drenar/coordinar lectores antes de cerrar conexiones.

WAL permite lectores concurrentes con un writer y requiere controlar checkpoints;
no ofrece atomicidad conjunta entre varias DB anexadas ni debe moverse su archivo
principal solo mientras está activo. Por eso la publicación es dentro de una DB
y las transiciones entre archivos usan un protocolo explícito.
[Contrato WAL de SQLite](https://sqlite.org/wal.html).

## 6. Migraciones up/down y reemplazos

### Runner nuevo

Migraciones numeradas con: ID, checksum, schema previo esperado, objetos propios,
up, down (o `rebuild_required`), preflight y validación post. Escribir el ledger
en la misma transacción que el cambio de schema, antes de COMMIT, de modo que
ambos se confirmen o reviertan juntos. Publicar éxito sólo después del COMMIT.
No ignorar OperationalError suponiendo «ya existía».
Repetir misma versión/checksum es no-op; mismo ID/checksum distinto es error.

No usar una mezcla de executescript y transacciones implícitas sin probar sus
límites. El runner debe controlar la transacción real de cada etapa, incluidos
DDL y ledger. No asumir que todas las operaciones de mantenimiento (VACUUM,
cambio de journaling) pertenecen a la misma transacción de schema.

### Rutas iniciales propuestas

| Ruta | Up | Down |
|---|---|---|
| Fresh → epoch 2/schema 1 | Crear tablas y constraints; validate; ledger | Quitar objetos KQL2 allowlisted; almacén vacío/rebuild_required |
| Caché legacy → epoch 2 | Crear nueva DB al lado; reparse/lower fuentes; publicar | Desactivar namespace KQL2; KQL1 usa caché legacy o la reconstruye |
| Cambio aditivo schema N→N+1 | Transacción DDL/datos/índices/ledger, validación | DDL inverso si se preserva significado; si no, rebuild del formato anterior |
| Cambio incompatible de epoch | Crear namespace nuevo, reconstruir, publicar y retirar viejo después | Reactivar snapshot/formato anterior compatible o reconstruirlo |

No convertir blobs IR 1.77 en garantías de KQL 2. Se pueden usar como insumos de
un adaptador explícito, pero sus datos parciales mantienen el perfil anterior;
la ruta inicial recomendada reconstruye las nuevas proyecciones desde fuentes.

### Procedimiento de reemplazo destructivo controlado

1. Preflight: verificar ownership/magic/schema, espacio, versión de la app,
   ausencia de writers incompatibles y ruta canónica dentro del directorio propio.
2. Registrar manifiesto durable `prepared` con origen/destino/checksums/estado
   anterior. Si se necesita backup, usar SQLite backup API o cerrar de forma
   coordinada el conjunto de archivos; no copiar sólo `.sqlite` con WAL activo.
   [API de backup](https://sqlite.org/backup.html).
3. Construir el formato nuevo en ubicación separada. Mantener el anterior legible.
4. Validar integridad (`integrity_check`, `foreign_key_check`), schema, manifest,
   perfiles y consultas de smoke documentadas. Estados desconocidos permitidos
   siguen siendo desconocidos, no cambian a completos para publicar.
5. Drenar writers y publicar selección de epoch mediante manifiesto con replace
   atómico y sincronización del archivo/directorio. Registrar fase `published`.
   Tras crash, el manifiesto permite decidir qué DB está publicada; no hay una
   supuesta transacción SQLite que cubra dos archivos y el filesystem.
6. Retirar antiguo sólo cuando no haya readers y la versión anterior no sea
   necesaria. Borrado explícito del namespace o DROP de lista cerrada, nunca
   `DROP` generado para todo lo que aparezca en sqlite_master.
7. Marcar `retired`. Los backups/manifiestos de transición tienen tamaño/política
   de retención visible, distinta de caché activa.

Un DROP seguido de UP sobre la misma DB se permite como **rebuild explícito** de
datos estructurales descartables, después de drenar usuarios y verificar scope.
No es la ruta normal de upgrade: antes de terminar UP no habría índice utilizable.
El plan de recovery debe dejar `rebuild_required`, no una DB vacía marcada ready.

Para reconstrucción de una tabla en schema compatible, crear tabla nueva, copiar
con validación, recrear índices/triggers y sustituir bajo el procedimiento de
migración. No improvisar ALTER con FKs desactivadas sin comprobación final.
[Procedimiento ALTER TABLE de SQLite](https://sqlite.org/lang_altertable.html).

### Qué significa downgrade

Downgrade de almacenamiento no traduce queries KQL2 a KQL1. Una aplicación anterior
ignora/rechaza el namespace nuevo y puede volver al caché legacy. Los resultados
calculados se pierden o recalculan; reglas fuente y datos de usuario permanecen.
Si la versión anterior no puede extraer las fuentes actuales, informar ese límite;
no afirmar que restaurar tablas recupera soporte semántico.

Comandos futuros propuestos, **no disponibles hoy**: `ken structural db status`,
`migrate --target`, `migrate --dry-run`, `downgrade --target`, `rebuild`, `verify`.
Cada uno informa objetos/bytes/versiones y si conserva o reconstruye datos.

## 7. Casos de fallo que deben probarse

* DB ausente, legacy reconocida, legacy con tablas desconocidas, schema futuro.
* Fallo antes/después de cada COMMIT y del cambio de manifiesto; reabrir el proceso.
* Disk full en copia, creación de índice, publicación y checkpoint.
* Dos migradores o un daemon viejo activo: rechazo/espera acotada, no carreras.
* Reader fijado al snapshot anterior mientras se publica y mientras corre GC.
* Up/down/up repetidos; checksum manipulado; DROP de objetos propios únicamente.
* Memorias, reglas propias, tablas `cr_*`, vectores y FTS intactos en hashes/conteos.
* Snapshot con archivo omitido/diagnóstico: la caché no lo promociona a cobertura total.
* Presupuesto menor que un snapshot: uso temporal/incomplete, nunca evicción de
  filas necesarias que haga aparecer un negativo.
