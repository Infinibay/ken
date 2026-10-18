# M1: proyecto y estado nativos

Fecha: 2026-10-18. Estado: especificación propuesta, pendiente de revisión.
Depende del [contrato de migración](2026-10-18-rust-migration-design.md).

## Objetivo y límite de la entrega

Producir el primer ejecutable funcional Rust: `ken-rs status [PATH] [--json]`,
capaz de inspeccionar proyectos creados por Ken Python. Resuelve el proyecto,
consulta sus datos y presenta el mismo informe que `ken status` sin invocar
Python, cargar modelos ni arrancar un daemon para consultar su salud.

La entrega incluye descubrimiento/confinamiento de rutas, lectura de metadatos,
lectura de los contadores SQLite existentes y cliente de health local. No
incluye indexar, instalar, editar datos, servir MCP o implementar comandos vacíos.
El ejecutable Python y sus integraciones instaladas siguen activos.

## Caller y resultados

```sh
ken-rs status /ruta/proyecto --json
ken-rs status /ruta/proyecto/subdirectorio
KEN_PROJECT_ROOT=/ruta/otro-proyecto ken-rs status /ruta/proyecto --json
```

PATH vale `.` por defecto. `KEN_PROJECT_ROOT` no vacío prevalece sobre el punto
de partida, como en `_paths.find_project_root`; una ruta forzada inválida no
activa búsqueda alternativa. Una cadena vacía equivale a no forzar el proyecto.
La raíz requiere `.ken/meta.json` como archivo, no sólo un directorio `.ken`.
Se preservan expansión de `~`, resolución de symlinks y búsqueda de la raíz más
cercana subiendo desde el directorio inicial.

| Estado observable | Resultado/exit code |
| --- | --- |
| No hay proyecto | JSON `{ok:false,error:...}` y exit 1; texto de error y hint por stderr sin `--json` |
| Hay metadatos pero no base | `ok:true`, raíz, project_id, descripción de base e `installed:false`; exit 0; no crea base |
| Base instalada válida | `installed:true`, todos los contadores, salud de índice, señales, cobertura, recomendaciones y daemon; exit 0 |
| Daemon ausente/no responde/health inválido | El informe sigue siendo válido con `daemon.running:false`; no spawn ni borrado de port file |
| Metadatos/base ilegibles, corruptos o incompatibles | Error explícito, exit no cero, sin informe exitoso ni escritura correctiva |

La forma exacta de los errores de datos corruptos se captura en M0 para distinguir
el contrato útil de trazas internas Python. No se promete reproducir un traceback
Python byte por byte; una mejora de diagnóstico se registra como diferencia
deliberada, manteniendo fallo y ausencia de corrupción.

`--json` conserva claves/tipos y valores del informe de `status_report`.
Espacios de serialización y orden de claves JSON no son identidad semántica.
El modo texto conserva líneas, recomendaciones visibles y separación de
stdout/stderr observada en `show_status` y sus pruebas. JSON retiene inventarios
internos que el texto omite. Los errores de sintaxis de argumentos mantienen la
convención exit 2; la ayuda identifica el binario temporal `ken-rs`.

## Conceptos y límites

| Concepto | Responsabilidad |
| --- | --- |
| `ProjectLocator` | Encontrar la raíz según entorno y punto de partida; distinguir ausencia de error de acceso |
| `ProjectPaths` | Componer rutas canónicas y rechazar escapes de un path solicitado |
| `StatusReader` | Construir el informe desde metadatos, contadores, archivos y health |
| `StatusCounts` | Expresar el inventario de datos que usan las reglas de estado |
| `DaemonHealthClient` | Hacer una consulta local autenticada y acotada, sin gestionar el ciclo de vida |
| Presentación de estado | Convertir un informe al JSON/texto del contrato |

Son responsabilidades, no una obligación de crear seis traits. El plan fijará
tipos y firmas tras escribir pruebas representativas. El lector de estado
orquesta; las reglas de cobertura, recomendaciones y señales tienen un hogar
único. El transporte no decide cuándo recomendar indexar o reembeddear.

Estructura propuesta, creada sólo al comenzar implementación:

```text
Cargo.toml                         workspace mínimo
Cargo.lock                        resolución reproducible del binario
rust-toolchain.toml               toolchain verificado
crates/ken-core/src/project.rs    identidad, descubrimiento y confinamiento
crates/ken-core/src/status.rs     informe y reglas de estado
crates/ken-core/src/health.rs     cliente health local
crates/ken-core/tests/            pruebas de contratos de biblioteca
crates/ken-cli/src/main.rs        argumentos y coordinación del comando real
crates/ken-cli/src/status.rs      presentación pública de estado
crates/ken-cli/tests/             pruebas del proceso real
tests/rust_migration/             fixtures/comparación diferencial con Python
```

El plan de implementación añadirá manifiestos de crates y los módulos mínimos
necesarios; este árbol representa responsabilidades, no scaffolding ya creado.
El comparador Python es tooling de validación y no dependencia del ejecutable.

## Datos y efectos permitidos

Se lee `.ken/meta.json` sin exponer `auth_token` en salida. La base usa el esquema
actual y sus contadores; M1 no aplica migraciones ni escribe en bases del usuario.
Las pruebas se realizan sobre fixtures y copias. Las conexiones deben ver los
commits publicados en WAL y liberar recursos antes de salir. La ausencia de DB
no abre una conexión que la cree como efecto secundario.

Se conservan los quince contadores de `StatusCounts`, incluyendo embeddings
inline y `vec_slot`, sesiones, contextos, interacciones, findings e intent sources.
`index_health` compara los paths indexados con archivos actuales y limita la
muestra a los cinco primeros en el orden vigente. Los vectores no se cargan:
sólo se consulta su presencia conforme al contrato actual.

Las reglas de `rank_signals`, `embedding_coverage` y `recommendations` se trasladan
con sus casos vacíos/parciales/completos. El redondeo de porcentajes y tamaños se
prueba en límites, porque los defaults numéricos de Rust pueden diferir de Python.

Health usa `.ken/daemon.port`, GET a `http://127.0.0.1:PORT/health`, bearer de los
metadatos y el timeout vigente de 1 segundo. Conserva los campos publicados por
health en el informe. Puertos inválidos, rechazo de conexión, timeout y JSON
inválido producen daemon detenido. No se siguen redirects fuera de loopback ni
se registran credenciales; una diferencia respecto al cliente Python se documenta
como restricción deliberada. La consulta nunca envía código del proyecto.

Los escapes por `..`, ruta absoluta externa o symlink existente se rechazan con
el prefijo contractual `path escapes project root:`. La resolución de paths aún
inexistentes debe conservar el comportamiento de Python, no depender solamente
de `canonicalize`, que exige existencia.

## Matriz de aceptación a construir en M0/M1

| Grupo | Casos mínimos |
| --- | --- |
| Descubrimiento | Raíz exacta, directorio anidado, raíces anidadas, sin proyecto, `.ken` sin meta, override válido/inválido/vacío |
| Rutas | Relativa/absoluta interna, expansión de usuario, componente inexistente, `..`, symlink interno/externo, nombres Unicode y espacios |
| Estado de datos | Sin DB, esquema vacío, filas completas, embeddings inline/slots/mixtos, sesiones abiertas/cerradas, findings e intent sources |
| Reglas | Índice vacío, embeddings ausentes/parciales/completos, historial insuficiente, prompts sin interacciones, scores disponibles |
| Frescura | Archivos presentes/ausentes y más de cinco paths faltantes con orden estable |
| Health real | Servidor local fixture con bearer correcto, campos extra, port ausente/inválido, conexión rechazada, timeout, JSON inválido |
| Errores y salidas | Texto/JSON, stdout/stderr y exits; meta inválida, campo requerido ausente, SQLite corrupto, esquema incompatible, permisos denegados |
| Integridad | Hashes de originales intactos, DB/metadata sin cambios lógicos, sin creación de DB ni spawn de daemon; commits WAL visibles |

Se aprovechan `tests/test_paths.py` y `tests/test_status.py` como evidencia del
contrato, añadiendo fixtures de proceso que no dependan de monkeypatches internos
de Python. El comparador ejecuta los dos binarios en copias equivalentes, registra
el estado esperado y no se limita a afirmar que ambos devolvieron lo mismo ante
un error. Los casos con rutas temporales se normalizan de forma declarada.

## Cierre de la entrega

M1 termina sólo si el binario realiza todas las variantes anteriores sin Python,
las pruebas nativas y diferenciales pasan, los originales permanecen intactos y
el recibo permite reproducir entorno, fuentes y resultados. Se informa arranque,
tiempo completo y memoria sin inventar un umbral adicional para este comando.

Esta entrega no acredita que búsqueda, KQL, memoria o integraciones estén
migradas. Su valor es proporcionar un primer camino completo y una infraestructura
de comparación reutilizable antes de abordar los motores mayores.
