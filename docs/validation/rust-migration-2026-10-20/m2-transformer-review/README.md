# Cierre de revisión de transformers nativos

La revisión independiente del rango e6dd00fc..f55c17a encontró dos problemas importantes y ningún crítico. Ambos se reprodujeron antes de corregirse: el consumidor final de CI carecía de CARGO_TARGET_DIR y usaba fuentes temporales ya retiradas; la declaración autenticada include_prompt=false se aceptaba sin aplicar la exclusión.

La preparación registra ahora el target del workspace y el consumidor usa los metadatos persistentes mediante PreparedTransformerTests. El registro rechaza explícitamente la exclusión de prompts y valores malformados, conservando el comportamiento inclusivo predeterminado. Los tests ejercitan un proceso real con entorno limpio después de retirar leases y declaraciones con hashes actualizados. Se realizó una sola reparación y no se solicitó otra revisión.

La suite completa de herramientas pasó 367/367 en cada plataforma. El workspace Rust pasó 267 tests en macOS y 257 en Linux, sin fallos ni omisiones; formato y Clippy con warnings denegados también pasaron. Estos logs corresponden al código corregido. Los originales1066 permanecen intactos.

La evidencia neuronal anterior está preservada en ../m2-transformer-acceptance y se volvió a interpretar desde su checkout y tooling congelados exactos. SOURCE.json demuestra que la única diferencia productiva es el guard de siete líneas previo a inferencia: no cambió ninguna operación tensorial ni módulo nativo. No se atribuyen hashes de hosts nuevos a observaciones antiguas ni se afirma una nueva ejecución neuronal de33perfiles. Una primera repetición desde imports del checkout actual fue rechazada correctamente por procedencia FastEmbed; el replay desde el checkout congelado pasó.

M2 aún no está aceptada: siguen pendientes adquisición/perfiles/fábrica e integración, además de M3–M8 de la aplicación. Los dos hallazgos menores diferidos son la clasificación genérica del error de scores no finitos y el espacio final conocido en test_transformer_sources.py:31. review.md conserva el informe completo; rulings.md y progress.md conservan todas las decisiones, límites y correcciones del registro anterior. La rama y los originales se conservan.
