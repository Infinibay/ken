# Revisión independiente de los callers 93b

El parent de propuestas, worker y fuente son coherentes con el diseño original de 251 features. No encontré un nuevo bloqueo de código. **No se aprueba todavía lanzamiento o fit**: faltan la entrega sellada, sus bindings y los artefactos reales de fuente. No abrí metadata/consultas/labels auxiliares ni identidades privadas, ejecuté controladores o cambié archivos de implementación/marcadores.

El parent exige el receipt exacto, worker esperado, fuente completa de ocho repos y SHA del productor source93b antes de abrir las 96 requests. Valida la proyección pública con id/repo/request y cinco campos internos exactos: auto, symbol, 10, 12.000 y query no vacía. Conserva doce consultas por cada repo y copia los índices con SHA idéntico para replay. Cualquier fallo de worker aborta conservando parciales; no hay exclusión de consultas.

El worker sigue el camino de API69/81: retrieve_contextual, evidence_features y contextual_features(source_views=True). Los guards de encoders/expansión y source views permanecen explícitos; el fingerprint numérico es un placeholder identificado como proposals-only y no se carga NumericRanker. No se emplean scores supervisados de 69 ni de otros folds para decidir los pools. El exact bypass deja las 24 columnas de contexto/vistas neutrales como 66c/69. Los spans/señales/entidades guardados se reconstruyen desde los índices fuente copiados y ligados; todavía habrá que verificar esa correspondencia real.

Para ejecutar, el SHA de metadata debe estar ligado al sello/attestation del curador y ocho identidades canónicas y raíces distintas; el SHA esperado de requests debe pertenecer a la proyección pública del mismo sello. Un hash CLI aislado o nombres locales no prueban esas relaciones. La revisión pendiente debe comprobar ids de string no vacíos/namespace global, cuota 64 EN/32 ES y disjunción opaca 16 dev/63 públicos/12 privados sin abrir identidad o contenido privado al implementer/revisor.

Después de los workers, habrá que comprobar los ocho recibos, scripts/assets/source/requests, todas las filas qid/index/features, pools y los índices copiados antes de recibir labels en el fitter. El parent guarda los hashes efectivos, pero no recalcula las 251 columnas ni sustituye esa revisión. Los 96 targets y los 16 conjuntos de 471 grupos requieren su propio PRE-FIT; nada de este informe abre su marcador.

Bindings revisados:

- Parent: `250f45ab62106d53fe412ffaaaf70f4da7008c2fced86b5ee890f5446661fb32`.
- Worker: `eea1bbdae068245e78906f92e79e7c391e6a3bc4d1e12a2c31ed80b35af8b97d`.
- Fuente: `48809026d6ea68306c64605a708d2dd51c21ab8a70c4a0f0be175f95c9c0ee61`.

Recibo detallado: `auxiliary-training-v93-callers-review.json`. El diseño y el guard original corregido se conservan en `auxiliary-training-v93-design-review.{md,json}`.
