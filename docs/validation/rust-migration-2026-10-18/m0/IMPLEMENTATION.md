# M0: referencia e inventario ejecutados

La referencia local está en `.ken/rust-migration/m0-m1/reference` y contiene
los cambios originales sin commitear. Su fingerprint es
`e95cc533cc8a603d46481c5310f4b870ffbaaced6fa24fd8a1d85cbd04123222`.
El manifiesto inicial conserva 1.066 hashes. La copia no se publica: incluye
fuentes de trabajo del usuario, pero excluye estado privado y credenciales.

`capture.json` registra 60 rutas CLI, 15 herramientas obtenidas por MCP stdio
y 475 archivos de fuentes/recursos con responsabilidad y etapa asignadas.
`cli.json` conserva ayuda real, defaults y opciones anidadas. `mcp.json`
conserva los schemas del transporte y del registro local; sus diferencias
preexistentes (títulos y representación nullable/defaults) quedan visibles.
`capabilities.json` inventaría APIs candidatas, formatos, lenguajes y hosts;
asignar un dueño no demuestra que una capacidad esté migrada.

`baseline-results.json` conserva el resultado completo de pytest y mypy.
El primer intento no pudo recolectar por faltar `snowballstemmer==3.0.1`;
se instaló exclusivamente la rueda con hash fijado en `uv.lock`.
El segundo intento obtuvo 15.575 aprobadas, 6 fallidas y 10 xfail.
Cinco fallos pertenecen al arranque de servicios KQL en el sandbox; uno fue
un defecto del nuevo capturador MCP (`inputSchema`), corregido y comprobado
en sus pruebas. No se ha modificado código Python original para repararlos.
Mypy informa dos imports ausentes de `transformers`, con IDs/archivos en el recibo.

Comandos reproducibles desde la raíz, con el intérprete del proyecto:

```sh
.venv/bin/python -m tools.rust_migration.inventory --reference .ken/rust-migration/m0-m1/reference --out docs/validation/rust-migration-2026-10-18/m0
.venv/bin/python -m tools.rust_migration.reference verify --repo . --manifest docs/validation/rust-migration-2026-10-18/baseline.json
.venv/bin/python -m pytest tests/test_paths.py tests/test_status.py tests/rust_migration -q
```

## Harness diferencial

Los 58 casos de `m1-cases.json` se fijaron antes del port Rust. Hay copias
independientes por motor, datos sintéticos, expectativas declaradas y control
de mutaciones de meta/port/dump lógico de SQLite, incluyendo un escritor WAL
abierto. Sólo se normalizan las posiciones explícitas de rutas temporales.
Claves, tipos JSON, arrays, streams y exits permanecen comprobables.

El autocontrol Python/Python aprobó 57 casos. Excluye únicamente la diferencia
deliberada de redirect de health, obligatoria en la matriz Rust. Este resultado
se etiqueta `harness-self-check`; no certifica compatibilidad nativa.
El control negativo real ejecutó un subprocess que devuelve `{}` y exit 0;
el CLI comparador devolvió exit 1 e identificó `installed_empty-json`.
Los recibos completos permanecen bajo `.ken/rust-migration/m0-m1/`.

Los errores de datos conservan exit 1 y separación de streams, sin exigir el
traceback Python; los errores de argumentos conservan exit 2. Las excepciones
son IDs declarados antes del port, no una aceptación genérica de fallos iguales.

## Aceptación observada

El gate M0 serial aprobó **43 tests, cero fallos/omisiones**, en 51,883 s;
`m0-gate.xml` conserva sus IDs. Los verificadores del manifiesto inicial y de la
copia ampliada devolvieron `passed=true`. M0 queda aceptado; M1 sigue pendiente.
Los intentos concurrentes se conservaron: excedieron deadlines del tooling de
captura y mostraron dos fallos adicionales de presupuesto/arranque en KQL
original. La captura MCP aislada recorrió initialize/list_tools/close con exit 0.
Se repitió el gate serial completo, sin aumentar timeouts ni relajar aserciones.
