# Revisión del consumidor de citas léxicas

**APTO bajo la precondición de catálogo registrado y autenticado por el caller.** Sin bloqueos observados para entradas que cumplen ese contrato. Helper `484d0efcd115c7aee312c1cb05580072b9cc6f7c22a48125e46ce43c6f072300`. No modifica el catálogo95, API, ranking, selector, targets ni reglas.

Verifiqué31tests combinados y6103selecciones sintéticas, con44097comprobaciones de propietario por línea visible. Las citas mantienen texto físico, Unicode/CRLF, owners/ordinales de hijos y ownerNone de blancos. El recorte de `source_owners` coincide exactamente con lo visible. Fuera de extent, solapamientos, partes incompletas, source stale, owner de otro archivo y límites mayores de40líneas/3fragmentos se rechazan.

La frontera de confianza debe conservarse: el caller carga el catálogo cuyo hash/política/freeze fue revisado y lo liga al índice/generación activo. No puede construir o reetiquetar un `LexicalContext` arbitrario. El helper comprueba bytes, selección y consistencia local; no autentica el owner sólo por hash de fuente ni rehace AST. Una falsificación sintética que cambia únicamente owners por otros del mismo archivo ilustra esa precondición, sin afectar los catálogos95válidos.

El caller también conserva entidad/ruta/hash primarios y aplica12000caracteres al JSONfinal completo, incluida procedencia. El helper devuelve por diseño una línea física de más de12000caracteres en un fixture: eso no es una respuesta presupuestada. Después de recortar por presupuesto debe invocarse de nuevo con los spans finales, sin metadata de líneas ocultas ni fuente abreviada/inventada.

No se incorporó loader, presentación/API final o prueba de ejecución/target/retorno. Ningún score, calidad, latencia o permiso de fit se deriva de este slice. Usé sólo fixtures; no consultas/labels/modelos, payload auxiliar, reserva, productores ni marcadores.

[Probes](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/lexical-context-evidence-v95-review-probes.json) · [Detalle JSON](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/lexical-context-evidence-v95-review.json)
