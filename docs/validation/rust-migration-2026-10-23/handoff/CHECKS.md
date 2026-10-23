# Comprobaciones del traspaso — 2026-10-23

Este checkpoint conserva trabajo preparatorio de M4c2 Task 3. No acepta la tarea,
M4 ni la migración completa. No modifica código Rust ni reejecuta modelos/suites
nativas previamente aceptados.

Comprobaciones ejecutadas antes del commit:

- `python -m pytest -o addopts= -q tests/rust_migration/test_piece_reference.py`:
  **2 passed**, 0.16 s; cubre catálogo y ensamblado.
- Validación de las fixtures originales actuales: catálogo **38 casos / 4 raíces**,
  ensamblado **45 / 3**, ranking macOS **84 / 9**. Ranking Linux sigue pendiente.
- Cinco alteraciones independientes de ranking (input, resultado, observer,
  skipped y discovery incompleto): todas rechazadas por `validate_reference`.
- Ejecución literal del bloque de reconstrucción del Markdown en un directorio
  temporal: **1.066 originales / 102 archivos de progreso reconstruidos**, hashes
  correctos; todos los owners requeridos coinciden con el baseline. Se eliminaron
  después sólo esos archivos temporales de la prueba.
- Autenticación de cada archivo raw de seis capturas originales (catálogo y
  ensamblado en ambos hosts, ranking macOS corregido y su predecesora). La captura
  corregida coincide con la fixture; el hash del predecesor coincide con el
  `reused_suite`. Las observaciones aliased no se aceptan como casos de ranking.
- Enlaces locales del documento y nueve hashes `FILES.json` históricos correctos.
- Ausencia real de `piece_features.rs`, `piece_ranking.rs` y fixture Linux de
  ranking, consistente con el punto de reanudación documentado.
- `verify_reference` del worktree original: **sin cambios en los 1.066 archivos**.
- `git diff --check`: sin errores de whitespace.

El bloque opcional que restaura originales dentro del worktree se entrega para
un clon nuevo y limpio; no se ejecutó sobre el worktree actual con cambios previos.
Las rutas absolutas históricas de los registros permanecen intactas.
