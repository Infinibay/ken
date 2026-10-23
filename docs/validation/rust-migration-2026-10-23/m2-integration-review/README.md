# Cierre de integración M2 tras revisión

La revisión única encontró tres problemas importantes. La reparación única añade
rechazo temprano de backend cruzado en jueces, presupuestos de espacio incremental
por filesystem de destino y comparación de la preparación completa FastEmbed con
la evidencia directa fijada. No cambia el cálculo de tensores ni los originales.

La suite Rust actual pasó **318 casos en macOS arm64 y 308 en Linux aarch64**,
sin casos omitidos. Los **77 tests Python de integración afectados** pasaron en
cada plataforma. Formato, clippy de todo el workspace y guardia de1066originales
pasaron. Las listas descubiertas y la salida completa se conservan: los casos
ejecutados coinciden exactamente con las listas de cada plataforma.

Las regresiones reprodujeron el backend cruzado, la ausencia de APIs de capacidad,
el bypass de capacidad con un grafo ya preparado y24mutaciones de preparación.
`review-controls.py` reproduce además la falsa aceptación de la matriz anterior
con su código exacto y rechaza seis matrices reselladas con el replay corregido.
La matriz restaurada pasa. Los registros RED se conservan junto a los GREEN.

El presupuesto agrupa copias nuevas por el dispositivo obtenido del descriptor de
su destino existente más cercano. Suma asignaciones y una reserva de3GiB en cada
filesystem que recibirá datos. Incluye caché de adquisición, private_parent y
temporales del runtime; fuentes prestadas o presentes no vuelven a cobrarse.
Las pruebas separan el cálculo con medidas controladas y la consulta real del
filesystem, incluyendo un destino aún inexistente sin crearlo.

## Alcance y reproducción

El recibo anterior `docs/validation/rust-migration-2026-10-21/m2-integration` permanece
intacto (ruta real: `docs/validation/rust-migration-2026-10-21/m2-integration`).
Su manifiesto se fija por SHA-256 en INDEX. La referencia exacta se conserva en
`.ken/rust-migration/m2-integration/source-6eca4cb1`, creada con `git archive
6eca4cb1` y superponiendo los1066archivos originales autenticados de M0. No usa
hardlinks. El replay previo pasó antes y después de las correcciones usando esas
fuentes; ya no se compara una captura histórica contra fuentes futuras de M3.

`source-before` y `source-after` conservan los seis archivos de reparación.
Sólo tres archivos de producción cambian respecto al workspace acreditado:
artifact_cache.rs, model_factory.rs y model_sources.rs. INDEX conserva sus
inventarios completos y los de las herramientas. `REPAIR.patch` es el cambio real.

Los comandos nuevos fueron release `cargo build --offline --release --locked
--workspace --bins --examples`, descubrimiento y ejecución `cargo test --offline
--locked --workspace --all-targets`, clippy del mismo alcance con `-D warnings` y
pytest de `tests/rust_migration/test_integration_*.py`. Se usaron los entornos
nativos preparados existentes; en Mac se pasó CARGO_TARGET_DIR antes de cargar el
wrapper para que todos los probes apuntaran al release actual. Los cores Torch,
MLX, ONNX y CT2 conservan sus identidades previas. Linux usó el contenedor existente.

No se repitieron las matrices neurales completas ni la suite Python original sin
cambios. Sus resultados completos y las reparaciones previas permanecen en el
recibo anterior, con las identidades y límites allí declarados. Los números nuevos
anteriores corresponden sólo a las ejecuciones indicadas, no a otra ejecución de
16000tests ni a nuevos2247vectores/516scores.

M2 queda aceptado con su cadena de evidencia y esta reparación verificada. M3–M8
siguen pendientes. El comando Python instalado y todos los archivos originales
se conservan; no se ha promovido la aplicación Rust completa.

`LEDGER.md` contiene el registro completo y `RULINGS.md` todas las decisiones de
este plan y su coste si fueran incorrectas. No hay menores nuevos diferidos; los
de bloques anteriores se conservan en sus recibos correspondientes.
