# Revisión independiente del diseño y controladores 93b

El diseño es compatible con el contrato: 96 consultas auxiliares de entrenamiento, 400 consultas originales de aceptación intactas y una sola variante fija. Las guardas prospectivas señaladas en source93 quedaron cerradas en 93b antes de ejecutar. **Esto no aprueba todavía la metadata, el lanzamiento fuente ni el fit**: el sello y la attestation del curador siguen pendientes. No abrí metadata auxiliar, consultas/etiquetas nuevas o identidades privadas, ejecuté controladores/modelos ni modifiqué código/datos/marcadores.

El protocolo distingue correctamente el diagnóstico 91 de una explicación causal. Añadir datos cambia juntos volumen, diversidad y distribución lingüística; una mejora no aislaría uno de esos factores. La aceptación sigue siendo ALL400, baseline 286/298, evidencia 3 y los límites originales. El gate de cinco adicionales sólo habilita una posterior validación API; no equivale a 90% ni aceptación privada/pública externa.

La primera versión source93 registraba los hashes actuales de los assets/template y aceptaba cualquier freeze internamente válido. Eso no probaba identidad con 66c/69. Un POC puramente en memoria cambia query_prefix y recalcula EncoderSpec: la consistencia interna del registro todavía pasa con el mismo graph, pero el espacio de consulta cambia. No modifiqué ningún registro real. Source93b ahora exige el receipt exacto y hashes esperados de static/context/template antes de abrir metadata; el template usa conexión RO. El worker también fija receipt/static/context/translation y revisión de expansión. Verifiqué los cuatro hashes esperados contra los archivos actuales y las copias archivadas; los originales retirados se conservan.

El código fuente completa ALL8 índices con index_project/iter_files/extractor7, después ALL8 contextos completos y después ALL8 vistas. No tiene una fase de consultas. El worker exige source completo de ocho repositorios, requests con sólo id/repo/request y doce consultas por repo. Usa los mismos encoders CPU, proyecciones propias, prefix512 y loader de vistas existente, con reutilización sólo por texto+hash exactos. La nueva evidencia auxiliar mantiene 251 columnas originales; el bypass exacto conserva neutralidad de las 24 columnas context/view. No se incorporan POS90 o empates92.

La separación más importante para el entrenamiento compartido está respetada por el worker revisado: no importa/carga NumericRanker ni usa un teacher supervisado. El perfil es explícitamente proposals-only y la recuperación usa canales estáticos/pretrained. Usar después scores de un modelo all16 u OOF de otro fold para seleccionar pools o negativos auxiliares volvería a introducir posibles etiquetas del repo retenido. Esa frontera deberá conservarse en el ensamblador/fitter aún no revisado.

Antes de lanzar fuente, falta revisar el sello inmutable, metadata con ocho raíces e identidades canónicas distintas, pins/licencias y attestation opaca de disjunción respecto de 16 repos dev, 63 públicos y 12 privados. Un nombre local distinto o booleano no prueba por sí solo la identidad canónica. No se pide al implementer/revisor abrir nombres, consultas o referencias privadas. El prefijo de source_only_inputs comprueba ubicación, no el papel semántico de cada archivo: la metadata revisada debe enumerar sólo los inventarios públicos y sello opaco previstos; calcular su digest no debe convertirse en parsear etiquetas para generar fuente/features.

Después hacen falta recibos reales de archivos, índices, generaciones, textos, vectores y recodes; el código solo no prueba esos artefactos. Los pools y las 96 filas de consultas deben quedar sellados antes de que el fitter reciba labels, con binding por qid/index/hash/generación. La elegibilidad debe conservar exactamente identidad, fuente propia y TODAS las anclas; errores de curación se corrigen por fuente de forma independiente antes del fit, conservando fallos anteriores y sin quitar ejemplos por baja recuperación.

El pre-fit posterior debe verificar los 16 conjuntos con 375 grupos dev no retenidos más 96 auxiliares, 471 por fold, sin filtrar exactos o no positivos. Deben quedar ligados las matrices originales dev intactas, namespaces únicos, orden/tamaños de grupos, labels, fuentes y todos los scripts; perturbar las 25 consultas retenidas no puede alterar el entrenamiento. El fit, exports, respuestas y scorer requerirán otra revisión de cierre. Los recursos de preparación no son un certificado API.

Bindings revisados:

- Freeze93: `4ebee803348ded840b948be0912e58924faf6ae218cd107d1cbb6963cd2f892d`.
- Source93b: `48809026d6ea68306c64605a708d2dd51c21ab8a70c4a0f0be175f95c9c0ee61`.
- Worker93b: `eea1bbdae068245e78906f92e79e7c391e6a3bc4d1e12a2c31ed80b35af8b97d`.

Recibo y evidencia del hallazgo cerrado: `auxiliary-training-v93-design-review.json`.
