# Restricciones de calidad

2026-10-14. Alcance numérico: mejora del engine de búsqueda descrita en [el diseño](docs/superpowers/specs/2026-10-14-search-engine-top1-design.md). Estado: contrato aprobado por el usuario; verificadores y motor en implementación. Este documento no certifica que Ken alcance actualmente sus objetivos.

## Piso de trabajo

- No añadir supresiones de tipado/lint, stubs sin implementar, secretos, tests omitidos ni aserciones debilitadas para conseguir un resultado verde.
- Una modificación deliberada de contrato requiere explicar y probar el contrato nuevo; no eliminar pruebas de compatibilidad sin revisar sus consumidores.
- Preservar cambios anteriores del usuario. No reset, stash ni commits ajenos al trabajo propio.
- No cambiar referencias, denominadores, exclusiones, presupuesto de salida o umbrales después de inspeccionar aceptación para declarar éxito.
- Mantener procesamiento local de consultas y código. Las descargas de modelos/dependencias no autorizan enviar código a servicios externos.

## Aceptación de búsqueda

El usuario exige **top‑1 mínimo 90% y archivo más función o fragmento correctos**. El diseño aprobado lo concreta con evidencia visible:

| Dimensión | Condición | Verificador previsto | Estado |
|---|---|---|---|
| Calidad primaria | `strict_top1 >= 0.90` global y macro por repositorio | `ken bench --engine retrieval --gate ...` | Verificador implementado; aceptación pendiente |
| Preguntas difíciles y multilingües | `strict_top1 >= 0.90` en comportamiento, EN y ES | Mismo gate con estratos congelados | Verificadores y curación congelados; aceptación pendiente |
| Identidad determinista | 100% de los casos de identificador único calificado | Suite de lookup y regresión | 48/48 en slice anterior; repetir con el perfil final |
| Reserva | 300 positivos en 12 repositorios nuevos; 60 negativos separados | Manifiesto y registro de uso | Curada y congelada independientemente; sin usar |
| Evidencia | Hash y rangos fieles; errores/abstenciones positivas cuentan como fallos | Scorer y pruebas de presentación/frescura | Implementados; validar perfil final |
| Rendimiento aprobado | Referencia aproximada de 1 s por cada 100 archivos indexables del repositorio, para la respuesta completa; CPU y RAM contenida, sin necesitar GPU | Medición reproducible del perfil público final, p50/p95/máximo y pico de RAM en el equipo del usuario | Pendiente |

`candidate_recall@100 >= 0.98` es un checkpoint diagnóstico de desarrollo, no un reemplazo del 90% en primer lugar. El usuario reemplazó los 500 ms iniciales por 3–5 segundos y luego precisó una referencia escalable de aproximadamente 1 segundo por cada 100 archivos del repositorio para obtener la respuesta final. Se informan los archivos indexables reales según la política de exclusiones existente (sin inflar el denominador con archivos ignorados), p50/p95/máximo del tiempo de respuesta completa y pico de RAM. CPU y bajo consumo de RAM son las condiciones esenciales; no hay un límite numérico de RAM pactado. Las pruebas históricas con modelos pesados/GPU no transfieren calidad al perfil de CPU. Se informan también arranque, indexación y memoria; la indexación se mide aparte de la consulta con índice preparado. No se añade cobertura porcentual global ni un linter nuevo para esta tarea.

## Uso de los gates

Las 60 preguntas anteriores sirven para desarrollo/regresión, nunca como única certificación. Cambios del scorer o de etiquetas deben quedar versionados con motivo y comparación histórica; no se reescribe el resultado anterior. La reserva sólo se usa cuando fuente, perfil y modelos están congelados. Tras inspeccionar sus fallos deja de ser reserva.

La promoción predeterminada exige recibo del gate, compatibilidad y revisión. Hasta entonces se informa avance y métricas observadas, sin declarar alcanzado el 90%. Una falla bloquea la promoción; no autoriza a bajar el umbral.

## Criterio vigente de pieza verificable, 15 de octubre

El usuario precisó después que la respuesta debe identificar la pieza solicitada
(clase, módulo, símbolo o archivo) y permitir verificar sus requisitos en el
contexto devuelto. El protocolo `experiments/search-engine/cpu-verifiable-pieces-v98.md`
concreta ese criterio: identidad correcta y juicio ciego de relevancia/suficiencia
completo, con citas literales para todas las facetas. Encontrar la identidad sola
no satisface el 90%. Se mantiene además identidad top‑10 de al menos 95%, sin
excluir errores, faltantes o abstenciones del denominador positivo.

Las 200 consultas descriptivas de desarrollo no sustituyen aceptación privada.
La reserva nueva v104 la curan los dos revisores autorizados, sin exposición al
implementador antes de congelar el motor; no se abre la reserva antigua para
ajustar resultados. Los presupuestos vigentes por tarjeta son 64 líneas físicas,
4 citas y 12000 caracteres canónicos. No se amplían para hacer pasar casos.

CPU es el mínimo obligatorio; una GPU/acelerador puede aprovecharse si está
disponible y es más rápido con salida válida. No se requiere hardware potente.
Se conserva la referencia aproximada de tiempo por cantidad de archivos y se
miden tiempo completo, arranque, indexación y RAM por separado. Una mejora de
ranking sin contexto suficiente o con gasto inaceptable no cumple el objetivo.
