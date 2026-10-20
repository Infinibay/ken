# M2: almacenamiento relacional y vectorial nativo

Continúa el programa aprobado de migración completa, con ejecución nativa,
originales conservados y pruebas antes de avanzar. Este documento concreta el
subsistema de datos; no acredita M2 completo, los runtimes opcionales pendientes,
la indexación, la búsqueda ni una sustitución del comando instalado.

## Intención y contratos observados

Un índice debe conservar sus filas, sus vectores y la identidad de su espacio al
cambiar de implementación. SQLite sigue siendo SQLite; los vectores siguen en
`.ken/vectors/{space}.json` y `{space}.{segment:04}.vec`, formato1, F32 de la
máquina, segmentos de65536filas. Las plataformas registradas son little-endian
Darwin/arm64 y Linux/aarch64. No se crea un formato nuevo por usar Rust.

Las fuentes propietarias son `db.py`, `schema.sql`, `vectors.py` y las operaciones
de selección/configuración del proyecto en `embedder/__init__.py`. Sus pruebas
existentes se conservan. `indexer.py`, `reembed.py`, `install.py`,
`retrieval/representations.py`, canales del ranker y `cli.py` son consumidores que
se integrarán en sus etapas; no se cambian ahora para llamar a Rust desde Python.
Las relaciones de ken son incompletas para imports dinámicos; la lista se
contrastó con llamadas/imports reales, no se supone completa por un grafo vacío.

Se añade un crate `ken-store`: el almacenamiento tiene una responsabilidad real
separada de modelos y estado. Reutiliza rusqlite0.40.2/bundled ya fijado. La SQL
actual se incorpora al binario como recurso compartido, sin copiar su autoridad
ni requerir Python o el checkout al ejecutar. `ken-core` conserva su lector de
estado de sólo lectura; no se hace que status cargue motores de inferencia.

## Conceptos y responsabilidades

| Concepto | Responsabilidad |
|---|---|
| ProjectStore | Coordinar apertura del proyecto y recuperación antes de exponer datos |
| ProjectDatabase | Abrir SQLite con la política actual y ofrecer consultas/metadata |
| Schema | Aplicar la SQL compartida y las migraciones aditivas en orden seguro |
| WriteTransaction | Mantener BEGIN IMMEDIATE y confirmar o revertir una operación |
| VectorSpace | Nombrar sólo ci_files,ci_symbols,ci_intent_sources |
| SlotAllocator | Reservar/liberar slots por espacio dentro de WriteTransaction |
| VectorManifest | Validar identidad, dimensión, formato y capacidad existentes |
| VectorStore | Leer/escribir segmentos F32, normalizar y puntuar por slot |
| VectorMaintenance | Migrar inline, verificar, compactar y recuperar interrupciones |
| StoredModelState | Leer el marcador y la presencia real sin decidir qué modelo usar |
| Storage receipt | Acreditar lectura cruzada, procesos, integridad y recuperación |

ProjectStore recibe los ProjectPaths ya resueltos de ken-core, crea sólo el directorio
de datos explícito si hace falta y delega la recuperación a VectorMaintenance antes
de exponer la conexión/los segmentos. No genera identidad del proyecto ni instala
comandos. ProjectDatabase también sirve como conexión SQLite de bajo nivel para
fixtures, pero esa apertura aislada no acredita recuperación de un proyecto.

Uso representativo: abrir ProjectStore sobre una copia de proyecto, asegurar
schema, abrir VectorStore para un VectorSpace, tomar WriteTransaction, reservar
slots, escribir los bytes, insertar referencias SQL y confirmar. Un error revierte
la transacción. Los helpers anidados reciben la misma WriteTransaction: no abren
una transacción diferida ni confirman antes que el coordinador. Una transacción
deferida arbitraria nunca acredita el permiso de asignar slots.

## SQLite y metadatos

Conexión read/write/create: WAL, synchronous=NORMAL, foreign_keys=ON,
busy_timeout=5000ms, autocommit fuera de transacciones explícitas. No se abre ni
modifica una base real del usuario para validar. La inicialización es idempotente;
conserva datos, todos los objetos SQL compartidos y las cinco columnas aditivas:
ci_imports.resolution TEXT; vec_slot INTEGER en ci_files/ci_symbols/
ci_intent_sources; ci_passages.implementation_start_line INTEGER. Índices de
columnas migradas y triggers de liberación se crean después de las columnas.

Las migraciones nuevas detectan una columna existente mediante introspección;
no ocultan otros errores SQL como si fueran «ya existe». El proceso informa el
fallo y revierte la inicialización nativa en vez de presentar éxito parcial.
Metadatos usan upsert, conservan cadenas vacías/Unicode/NUL y distinguen ausencia
por fila de un valor vacío. No se convierten errores de lectura en ausencia.

StoredModelState conserva el valor NULL/ausente como ausencia para la política y
present-empty como presente vacío. La presencia de vectores de archivo se prueba
con embedding IS NOT NULL OR vec_slot IS NOT NULL, incluyendo BLOB vacío y slots
cero/negativos. Publicar un pin inicial exige comprobar en la misma transacción
que el valor del marcador está ausente o es NULL y no hay vectores; escribe modelo y document_space=2 sin
borrar claves ajenas. La política Rust existente decide el nombre; el almacén no
reimplementa precedencias ni defaults.

## Asignación, segmentos y consultas

La lista libre se consume por slot ascendente antes de crecer high-water. Espacios
independientes, liberación idempotente, rollback y los triggers SQL conservan la
semántica actual, incluyendo borrados en cascada e índices únicos parciales.
Los contadores y offsets se calculan con aritmética comprobada; datos corruptos
no provocan overflow, una asignación gigante implícita ni un nombre de tabla/ruta
arbitrario. Los helpers aceptan VectorSpace, no SQL proporcionada como nombre.

Una fila eliminada dentro de una transacción puede reaparecer por rollback o
caída del proceso. Su slot no se reutiliza hasta confirmar la eliminación: la
asignación consulta también los propietarios comprometidos bajo el bloqueo
IMMEDIATE. La lista libre conserva esos slots para la transacción siguiente.
Un contador ausente o inferior a un propietario actual o recuperable produce un
error antes de reservar slots o permitir sobrescribir sus bytes.

Cada segmento se crea una vez con capacidad completa y nunca se redimensiona.
Una carrera de creación no permite usar un archivo parcialmente dimensionado:
publicación exclusiva de un segmento preparado completo o verificación/reintento
acotado antes de abrirlo. Un segmento truncado o ilegible produce un error; uno
nunca creado representa ceros, como en el original. Escrituras completas y orden
bytes-antes-de-referencia son obligatorios. durable=false corresponde al perfil
NORMAL actual; flush/durable=true hacen fsync. No se promete resistencia adicional
a pérdida eléctrica que la configuración original tampoco ofrece.

La lectura nativa usa buffers propios por bloques mediante read_exact_at, con
objetivo8MiB por bloque y al menos una fila. Evita prestar slices Rust sobre
archivos que los escritores modifican concurrentemente. La [documentación de
memmap2](https://docs.rs/memmap2/0.9.11/memmap2/struct.MmapOptions.html#safety)
advierte que modificar el archivo subyacente puede invalidar la seguridad de un
mapa. El formato fijo sigue siendo compatible con lectores mmap originales.
Se medirán RSS y tiempo del recorrido nativo; no se presume aceleración ni se
cambia el contrato del lector por una opción de implementación.

Los vectores se convierten a F32 y normalizan con norma F32 y suelo1e-12; ceros
siguen siendo ceros. El scoring normaliza la pregunta del mismo modo y devuelve
un vector F32 por slot[0,count). read conserva el orden y duplicados solicitados.
Los segmentos no creados son ceros. La selección live elimina slots libres dentro
del rango; las fugas no se confunden con filas vivas y los consumidores resuelven
por SQL. La limitación actual de lectores no serializables queda declarada: este
port no acredita snapshots de ranking concurrente de M4/M7.

Manifiestos existentes se leen sin reescribirlos. Se conservan claves y defaults
compatibles; formato1, dtypefloat32, dimensión/capacidad positivas y espacio deben
ser válidos. Un modelo solicitado explícitamente no puede contradecir uno
registrado explícitamente; model=null sigue significando que el manifiesto no
acredita un modelo y la metadata del proyecto debe establecerlo al integrar.
Un modelo no solicitado no borra el registrado. La creación mantiene permisos
consistentes con segmentos y umask sin cambiar globalmente el umask durante
operaciones concurrentes.

Correcciones de integridad explícitas respecto al original: rechazar manifiestos
que mienten sobre espacio/dtype/capacidad, errores de I/O/SQL enmascarados y normas
no finitas (incluido overflow de entradas F32 finitas). El original puede escribir
ceros falsos al desbordar su norma. No se contabilizan estos casos como paridad
idéntica: los recibos separan compatibilidad válida y errores corregidos. Una
entrada corrupta no se acepta para aparentar equivalencia.

## Mantenimiento y recuperación

Verificación conserva high_water, referenced, free, leaked, out_of_range,
double_booked y segments. bytes_on_disk informa bloques asignados cuando el
sistema los ofrece, manteniendo separado tamaño aparente. Migración inline usa
lotes de2000 por defecto y actualiza cada lote dentro de BEGIN IMMEDIATE;
filas de otra dimensión quedan inline, el proceso es reiniciable e idempotente.
No se promete igualdad bit a bit de entradas que el original vuelve a normalizar;
se comparan los bytes cuando son exactos y la tolerancia declarada cuando aplica.
VACUUM/checkpoint es mantenimiento explícito: errores no deshacen una migración
ya confirmada y se devuelven al adaptador para su presentación.

Los eventos de mantenimiento describen progreso real y fases de publicación para
diagnóstico; un callback del consumidor los recibe sin cambiar la operación. El
driver de prueba puede bloquear ese callback mediante pipes y un controlador
externo terminar el proceso; el producto no conoce inyección de fallos.

Compactación debe conservar los valores/referencias y remapear un prefijo denso
sin colisiones transitorias del índice único. Mantiene BEGIN IMMEDIATE y prepara
un directorio nuevo completo. Antes del intercambio publica un journal atómico
con identidad de operación y nombres de staging/backup confinados. Un marcador
transaccional interno de SQLite distingue commit de rollback. Recuperación,
bajo el mismo bloqueo de escritor, conserva el directorio nuevo si hubo commit y
restaura el anterior si no. Contempla interrupción entre cada rename y commit;
las limpiezas sólo retiran staging/backup propios identificados. El journal y
marcador se retiran tras completar recuperación, sin restos en el estado estable.
Los formatos finales permanecen legibles por Python. No se opera sobre el índice
real del usuario en esta etapa. El costo declarado es bloquear escritores durante
compactación; no se acredita disponibilidad del daemon para ese mantenimiento.

La limpieza también es recuperable tras una terminación: antes de eliminar la
generación no comprometida se publica atómicamente la fase `discarding_new` en
el diario externo, conservando los inodos ya acreditados. Esa fase permite
reanudar una eliminación parcial aunque haya desaparecido su recibo interno;
no autoriza eliminar una generación comprometida ni otra carpeta que ocupe su
ruta. Cada subdirectorio ajeno conserva sus permisos originales al copiarse.
Si sus permisos impiden borrar una generación descartada ya acreditada, la
limpieza puede habilitar permisos de propietario únicamente en los directorios
reales de esa generación. No sigue enlaces simbólicos ni modifica los permisos
de la generación conservada. Esto también aplica al reanudar tras SIGKILL.

## Pruebas y aceptación

Antes de implementar se congela un oráculo de operaciones del original en ambas
plataformas, sobre bases/segmentos propios. Incluye fresh/legacy schema, blobs,
Unicode/NUL, índices/triggers/cascadas, slots reutilizados y rollback, límites de
segmento, ceros, scores, migración mixta y mantenimiento. Tolerancia numérica
máxima prefijada1e-6 absoluta y1e-6 relativa para F32 normalización/scoring; orden,
slots, SQL, bytes de entradas exactas, IDs, dimensiones y efectos son exactos.
Si la referencia no es estable bajo esa regla se resuelve antes del código Rust.
Los defectos explícitos se prueban separadamente y nunca se usan como oráculo de
comportamiento correcto.

Pruebas Rust por uso público y pruebas reales de dos procesos acreditan exclusión
de escritores, liberación por cascada, flush concurrente y errores antes de que
una fila apunte a bytes inválidos. Terminaciones reales del proceso durante
compactación/migración se inyectan con barreras externas de pruebas; no se añaden
switches de fallo a la API del producto. Python lee los datos Rust y Rust lee los
datos Python en copias independientes. El proceso Rust corre fuera del checkout
con PATH sin Python; Linux registra exec reales y dependencias nativas.

El gate compone los28 controles actuales con release/paridad/recuperación de
almacenamiento; conserva tests Python, baseline, typing, fmt, Clippy, todos los
targets Rust y los1066 hashes originales. Exige las dos plataformas y las huellas
actuales; M2_accepted continúa falso hasta cubrir datos y todos los modelos.
Un revisor independiente al final del plan, una sola corrección Critical/Important
con TDD y suite completa, sin rerevisión; decisiones y ámbitos declinados quedan
registrados con costo. La instrucción del usuario mantiene la ejecución continua
sin nuevas confirmaciones; se conservan especificación y plan verificables.

Autorrevisión: conexión, reglas de almacenamiento y selección de modelos tienen
propietarios distintos. SQL compartida, API transaccional y formato persistente
son explícitos. Concurrencia de escritores, recuperación por proceso y límites
numéricos reciben pruebas propias; no se atribuye serializabilidad de lectores,
recuperación eléctrica ni promoción instalada a estos ensayos.
