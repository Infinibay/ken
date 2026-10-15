# Revisión independiente ALL16: fuente léxica95

**Fidelidad APTO sólo para el catálogo de fuente, conservando sus diagnósticos.** No encontré bloqueos de integridad. No es aprobación de proyección, evidencia visible, targets, fit o API. No abrí consultas, referencias originales, payload auxiliar ni reserva; no ejecuté productor/ajustes ni creé marcadores.

Verifiqué freeze `13fec1b8eaf9e6d017d72d61c7ddaee61af83a9a9d8776be34354918b5734556`,604archivos y los600anteriores byteidénticos; registro de catálogo `5c5c1d79ca3d4310b80c3dd4f9f1c5936dbf3cb452be8b69fe4919b953781581`. Los20inputs,16índices,16catálogos y16inventarios mantienen sus hashes.

| Comprobación exhaustiva | Resultado |
|---|---:|
| Archivos físicos originales |6314|
| Owners canónicos conservados |50967|
| Pasajes con body contrastado físicamente |124851|
| Contextos con texto, propietario y binding AST verificados |36194|
| Partes físicas verificadas |89866|
| Scopes AST con bytes/ancestría verificados |46483|
| Contextos con partes de otro owner descendiente |939|

Reproduje los contextos/diagnósticos con el helper congelado y añadí recorrido independiente de AST y bytes: carrier único admisible, límites físicos exactos, partes sin gaps ni texto inventado, propietarios/ordinales canónicos en cada línea no vacía y ownerNone sólo en blancos. La reextracción de archivos con parser reconocido produjo cero diferencias en pasajes/metadatos canónicos bajo la convención legacy de extent de módulo; no se tocó esa metadata. Los índices originales conservan extractor7/generación/hash. El JSON mecánico registra32testigos por hash, dos por repo; las verificaciones cubrieron todos los contextos.

Hay37402callables canónicos y36194contextos autorizados. Los1208restantes están explícitamente diagnosticados:695por gramática estructural no disponible,371por scope ambiguo/parcial y142en archivos cuyo AST contieneERROR. Son denominadores por owner; los diagnósticos por archivo corresponden a538/109/9archivos respectivamente. El inventario completo conserva4195archivos source_checked,1944sin parser canónico y175sin pasajes. ERROR del parser no prueba fuente inválida en su compilador ni una referencia incorrecta.

**Límite concreto:** `code` de Ajv `enum.ts` queda rechazado por la coma después de su método AST.95no representa ese testigo. `split_iter` de Boltons y `Marked.parseMarkdown` sí conservan contexto con sus hijos reales. Se preserva95con ese rechazo conservador; no corresponde afirmar que recuperó los tres casos, cambió targets o mejoró resultados.

La procedencia certifica sólo contención de fuente. No afirma ejecución, target, retorno resuelto, rama tomada u orden runtime. Clases/callables anidados mantienen sus fronteras; scopes anónimos no adquieren identidades canónicas inventadas. Una futura proyección/presentación debe versionarse y respetar la misma autorización, las referencias originales, ALL400 y presupuestos finales.

Los catálogos ocupan58055079B. El productor reporta31242.415ms como suma de fases por repo y236748800B de RSSpeak: preparación fuente sin modelo/query, en entorno concurrente; no son certificado de API ni mejora causal.

[Detalle mecánico](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/lexical-source-v95-review-mechanical.json) · [Informe JSON](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/lexical-source-v95-review.json)
