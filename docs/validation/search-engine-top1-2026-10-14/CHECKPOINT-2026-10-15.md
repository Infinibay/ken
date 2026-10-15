# Checkpoint solicitado antes de continuar

El usuario autorizó commit y push del trabajo de búsqueda a `origin/main`, sin
tag ni release. El checkout de investigación está en
`output/search-engine-2026-10-14/workspace`, rama `codex/search-engine-top1`.
Su `origin` local apunta al checkout principal; el destino autorizado de
publicación es el `origin` de ese checkout: `https://github.com/Infinibay/ken.git`.
No se incorporan los cambios ajenos copiados al preparar el workspace.

Estado medido, 15 de octubre:

- Corpus descriptivo actual de 200 consultas: identidad top‑1 168/200, **84%**;
  identidad top‑10 197/200, **98,5%**; pieza correcta y evidencia suficiente
  visible 76/200, **38%**. El objetivo conjunto de 90% sigue pendiente.
- Comparación directa con release limpia PyPI/uv 0.17.0 sobre las mismas
  consultas: 45/200, **22,5% top‑1**, y 103/200, **51,5% top‑10** de identidad.
- Los rerankers INT8 17/32/68M no superaron el objetivo. No se promueve ninguno.
  Hay variación de puntuación por composición del batch en el 17M INT8;
  el control FP32 sintético fue estable, sin demostración de mejora de calidad.
- Evidencia v105: replay completo CPU cerrado. Las 200 consultas conservan
  expansión, bypass exacto y orden/identidad de todos sus candidatos; las
  **3928 tarjetas** respetan autenticidad y presupuestos **64 líneas, 4 citas,
  12000 caracteres canónicos por tarjeta**. Cambian 90 primeras tarjetas.
  Falta juicio ciego de las nuevas tarjetas antes de medir utilidad conjunta.
- La reserva nueva v104 sigue privada y en curación independiente. No se
  abrieron sus consultas, entidades ni Gold. La reserva antigua tampoco se abre.
- CPU debe funcionar con RAM moderada; un acelerador opcional puede usarse
  cuando la medición demuestre una ventaja. No se exige una GPU potente ni se
  adopta un dispositivo/modelo nuevo sin comprobar salida y rendimiento.

La corrección v105 identifica la fuente como unidad de evidencia: puede mostrar
una definición corta completa aunque el índice la haya partido en pasajes.
Los rangos de dueños anidados siguen separados y la truncación sigue explícita.
Los fallos restantes incluyen tarjetas que mencionan helpers sin mostrar su
operación y cortes que omiten condiciones o retornos decisivos. La identidad
84% también requiere mejorar: evidencia perfecta por sí sola no alcanza 90%.

Se preservan código, tests, protocolos e historial; además, el paquete
`output/checkpoints/search-engine-2026-10-15/MANIFEST.json` conserva resultados
cerrados de desarrollo, consultas públicas, referencias de desarrollo ya
abiertas, juicios sellados y los modelos numéricos aprendidos. Cada archivo
comprimido se recupera con `gzip.decompress` y se valida por su SHA‑256 original.
No contiene los nuevos datos privados de aceptación. Los pesos externos y
vectores derivados conservan registros para descargarlos o reconstruirlos.
Los recibos incluyen rutas de ejecución originales: el paquete no se presenta
como un instalador portable de un solo comando.

La publicación PyPI se dispara únicamente con tags `v*`; subir `main` sólo
activa CI. No se modifica la versión 0.17.0 ni se crea un tag.
