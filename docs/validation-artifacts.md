# Artefactos de validación locales

Los recibos de ejecución, logs, capturas y reportes históricos de
`docs/validation/`, `docs/structural-validation/` y `docs/benchmark-evidence/`
se conservan localmente y están ignorados por Git. Las pruebas y sus fixtures,
el código de los verificadores y los planes de migración siguen versionados.
Los enlaces históricos hacia esos directorios requieren los artefactos locales.

En un clon nuevo, recuperar sólo el archivo o directorio necesario desde el
último checkpoint que los versionaba, sin añadirlo al índice. Por ejemplo,
para continuar la migración a Rust:

```sh
git archive 02a0e6b4597649388d376375e706b6b365d14271 \
  docs/validation/rust-migration-2026-10-18/baseline.json \
  docs/validation/rust-migration-2026-10-23/handoff | tar -x
```

La reconstrucción y verificación por hash del oráculo y del progreso está en
[el traspaso de Rust](rust-migration-handoff.md). Los verificadores históricos
pueden necesitar otros recibos locales: recuperar su subdirectorio de la misma
forma. No regenerar originales aceptados para suplir un archivo ausente.

CI recupera los recibos de migración desde ese checkpoint con la acción
`restore-validation-fixtures`; no los vuelve a incorporar al seguimiento.
El corpus adversarial que consumen las pruebas estructurales vive en
`tests/structural/fixtures/catalog-adversarial-cases.json`.

Guardar nuevas ejecuciones en `.ken/rust-migration/` o en el directorio local
del plan bajo `.superpowers/sdd/`. Incorporar a los fixtures versionados sólo
las entradas y observaciones que las pruebas de regresión consuman.

## Recibos nuevos posteriores a la limpieza

El cierre M4c2 del 24/10 nunca versionó sus logs. Su recibo completo se guarda en
`docs/validation/rust-migration-2026-10-23/m4-source-pieces/` y en el archivo local
`.ken/rust-migration/archives/m4-source-pieces-3e4a4e4c.tar.gz` (340.368.226 bytes):
SHA-256 `feafc8ea7dfe9f81beaf729e5ba15766ff7ab70eb3d3c656a8dd9c447172f5d7`.
Transportar ese archivo para recuperar también la revisión y el sellado local.
Las dos capturas previas al sellado se pueden descargar de la ejecución Actions
`40127406181` durante sus 30 días de retención; no contienen por sí solas el
recibo posrevisión completo.

Extraer el archivo verificado en un destino nuevo y ejecutar el replay con el
entorno de validación Python 3.12.9/NumPy 2.4.4:

```sh
mkdir -p .ken/rust-migration/receipt-copy
# Verificar primero el SHA-256 anterior; no sobrescribir otro recibo local.
tar -xzf .ken/rust-migration/archives/m4-source-pieces-3e4a4e4c.tar.gz \
  -C .ken/rust-migration/receipt-copy
.venv/bin/python -B .ken/rust-migration/receipt-copy/m4-source-pieces/replay.py \
  92954a5df4ea37bf4820b50e695b023d84d305fab29e7c19c09b93ea7d781e20
```

El replay autentica los 4.718 miembros del recibo e importa su verificador
archivado. No requiere Git, red ni ejecutar binarios ARM; conserva falsos los
indicadores M4/global. No regenerar originales para suplir el archivo perdido.


El soporte de gramáticas x86_64 tiene su propio recibo local en
`docs/validation/rust-migration-2026-10-24/x86-grammars/` y el archivo
`.ken/rust-migration/archives/x86-grammars-7048d3fb.tar.gz` (23.328.842 bytes),
SHA-256 `479fd3e89717ae2130207b2859b8f83c854ddd4b61ed7adb126f90324da3535f`.
Extraerlo en un destino nuevo y ejecutar `x86-grammars/replay.py` con Python
3.12.9/NumPy 2.4.4 y el SHA de `FILES.json`:
`7990e3edaf04a9b95f2ede40cb165298840d5f33094d397c1d749ee8beaf1350`.
El replay autentica 942 miembros y usa su verificador archivado sin Git, red ni
binarios ARM. La ejecución Actions `40141705583` conserva las tres capturas por
30 días; el archivo local incluye además revisión, decisiones y sellado final.
No reejecutar originales para recuperar un recibo ausente.
