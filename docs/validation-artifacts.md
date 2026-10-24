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
