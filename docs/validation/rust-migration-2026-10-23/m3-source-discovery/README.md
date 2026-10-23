# M3a: exclusiones y recorrido de fuentes

Se acredita sólo el descubrimiento de fuentes: **270 decisiones y51recorridos**
del original frente a consumidores Rust nuevos en cada plataforma. Las15fixtures
incluyen las16exclusiones incorporadas, reglas Git anidadas, `.kenignore`,
negaciones, patrones escapados, Unicode, bytes inválidos en reglas, scopes,
directorios podados, archivos ocultos, orden e identidades de aliases internos.

Cada consumidor se copia fuera del checkout y se ejecuta con PATH vacío de
Python/Git. Linux conserva la traza real de un único execve/execveat y ninguna
conexión; ambos sistemas conservan registros del cargador sin dependencias Python.
Los casos de enlaces externos/ciclos son correcciones de integridad separadas,
con errores explícitos, sin reemplazar resultados originales. La prueba de
permisos usa un usuario ordinario en ambos sistemas, incluso cuando Docker corre
como root: sólo su hijo de prueba se ejecuta con UID65534.

El corte añade la dependencia fijada `ignore0.4.33` y conserva la composición de
reglas en Ken. El original `pathspec1.1.1` descarta clases de caracteres inválidas;
la adaptación nativa reproduce ese resultado y propaga otros errores. No se
recorren directorios excluidos ni hermanos de un scope.

Los gates actuales ejecutaron30casos Rust de `ken-core` y24tests de herramientas
de fuentes por plataforma; todos pasan. Las listas descubiertas deben coincidir
con los casos ejecutados. Formato/clippy y la guardia de1066originales pasan.
Las matrices neurales y la suite Python completa sin cambios se reutilizan en
su alcance anterior. M2 queda fijado por el manifiesto del cierre de revisión.

`originals` contiene capturas reales independientes macOS/Linux con propietarios
y versiones; `macos`/`linux`, las solicitudes, salidas, cargador y trazas nativas.
`gates` conserva la salida completa y XML. `native-sources` guarda únicamente los
archivos del consumidor compilado y sus contratos de compilación, sin pesos ni
targets. `validation-sources` conserva las herramientas de comparación y pruebas.
INDEX liga estas identidades y FILES autentica la pertenencia exacta y los bytes.

La aceptación automática `M3a_accepted` no acredita parsers, indexación completa,
M3 ni la sustitución de la aplicación. La revisión del plan y su resolución se
conservan como un cierre posterior. El comando instalado y los originales siguen
activos. Los errores originales y los intentos fallidos de preparación permanecen
en el registro de esta etapa; no se convierten en omisiones aceptadas.

Para replay, desde el repositorio con sus originales intactos:

```sh
.venv/bin/python -c 'from pathlib import Path; from tools.rust_migration.source_evidence import aggregate_source_matrix; r=aggregate_source_matrix(Path("docs/validation/rust-migration-2026-10-23/m3-source-discovery"),Path.cwd()); print(r); assert r["passed"]'
```

Use el entorno de validación existente del proyecto, que incluye NumPy por sus
helpers compartidos de evidencia. El replay no carga modelos ni ejecuta inferencia;
el producto Rust no invoca Python.
