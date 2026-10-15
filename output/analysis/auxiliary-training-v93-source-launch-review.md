# Revisión independiente: aptitud del paso fuente 93b

**APTO sólo para construir la fuente ALL8.** Sin bloqueos en los metadatos entregados y su ligadura al sello. Esto no autoriza propuestas, lectura de requests/referencias, entrenamiento ni evaluación.

Verifiqué 3202 archivos físicos contra SHA256, bytes, OID y modo Git; los ocho HEAD y árboles están limpios y corresponden a sus pins. Los inventarios declaran 2476 fuentes compatibles; sus recuentos y bytes coinciden. Las 13440 identidades del inventario conservan hash y rangos físicos válidos. Los 15 archivos de licencia coinciden con sus hashes y tamaños registrados. Son comprobaciones de identidad de los archivos, sin interpretación legal.

Las ocho raíces y procedencias canónicas son distintas. Comprobé directamente su disjunción con los 16 repositorios públicos de desarrollo y los 63 públicos de Semble. La disjunción con los 12 de reserva se acepta como certificación opaca del curador, enlazada por el receipt de normalización y el hash del sello; no inspeccioné identidades privadas. Los recuentos de consultas, idiomas y alternativas siguen siendo attestations del curador.

Los cuatro inventarios de fuente se leyeron como metadata. El receipt del piloto y su tar sellado sólo se recorrieron para calcular SHA256: no se parsearon ni desempaquetaron. No abrí consultas, referencias o reserva, no ejecuté el productor ni creé marcadores.

Ligaduras para este paso:

- Engine receipt: `4ebee803348ded840b948be0912e58924faf6ae218cd107d1cbb6963cd2f892d`; 600 archivos congelados verificados.
- Productor 93b: `48809026d6ea68306c64605a708d2dd51c21ab8a70c4a0f0be175f95c9c0ee61`.
- Metadata: `ab8063641f684e05b42cf32376e73bea9ad6ad45bff2025be0824f0f8791b493`.
- Receipt de normalización: `c12b19c2b494ed45611015cb8a7bcb59a695160c456c37a2ca1452509b9f1466`.
- Sello: `bd84e1af801f271f7643a39f9010e1b8d11965e3a564a66ea814aee47c3fd7c7`.
- Paquete opaco: `1d9152342ef3c9a547461c07775d25fc556f1937ab7c48ae35009f2d79bdfcf1`.

Las tres guardas prospectivas de assets de 66c/42 y las copias archivadas de los tres controladores mantienen los hashes esperados. El productor 93b revisado sólo prepara índices reales con extractor 7, después contexto completo y ambas vistas de fuente para todos los repositorios, antes de cualquier request.

Los índices y vectores nuevos son el resultado de este paso y aún no se exigen como entrada. Al completarse ALL8 se requiere su revisión independiente de fidelidad/completitud, y luego ligar el SHA de requests antes de propuestas. El futuro ajuste requiere su propia revisión de datos y exclusión completa por fold; este informe no abre ningún gate de ajuste.

Nota temporal: root inició la construcción reversible sólo de fuente con la curación independiente y la revisión de código antes de emitirse este APTO de metadata. Este informe cierra metadata/procedencia; no anticipa la revisión de los assets nuevos ni autoriza consultas.
