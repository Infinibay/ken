# Optimizar coste sin confundir desarrollo con generalización

Continuación autorizada el15 de octubre de2026 del diseño de búsqueda aprobado.
El usuario exige conservar180/200 piezas correctas top1 y197/200 top10 en las
mismas200 consultas; además pide más pruebas para comprobar si90% se sostiene.
No release, tags ni promoción del default. La suficiencia del fragmento continúa
separada de identidad; no se vuelve a imponer como gate ni se cambian etiquetas.

## Responsabilidades y uso

- **InferenceBatch** es un límite de ejecución: puntúa pares consulta/documento
  preservando el orden de entrada, los tokens admitidos y los pesos. Su tamaño
  decide padding y memoria temporal, no relevancia ni pertenencia del top10.
  Uso: `CPUReranker(registration, batch_size=1).score(query, documents)`.
- **OptimizationControl** registra un único cambio de runtime, fuente y assets
  antes de ejecutarlo; cierra ALL200 sin Gold y sólo después calcula calidad,
  pérdidas, latencia completa y pico de proceso. Las versiones anteriores quedan
  intactas; un control rechazado también se conserva.
- **HeldoutCorpus** contiene preguntas nuevas y referencias canónicas curadas
  por los dos revisores ya autorizados. El implementador no las usa para ajustar
  políticas. La revisión cruzada y el sello preceden a toda evaluación.
- **FrozenCandidate** liga fuente, modelos, política y runner a sus hashes. La
  elección del candidato optimizado usa sólo las200 consultas de desarrollo.
  La validación nueva compara v132 y el candidato elegido, sin seleccionar otro
  candidato basándose en el resultado de la reserva nueva.

Las fronteras mantienen la decisión de relevancia en los rankers y la medición
en los runners. No introducir identificadores, rutas o reglas del benchmark en
la política; no sustituir salidas por pools, órdenes o scores históricos.

## Evidencia y prioridades

Baseline completo v132:top1=180/200,top10=197/200,mediana4.162s,p955.334s,
pico1.976GB. La inferencia68M tiene mediana3.083s; el nativo1.035s y piezas0.098s.
En sus1988 pares, mediana377 tokens,474 alcanzan512. El padding consume186577
de903944 posiciones procesadas (20,6403%). No sumar percentiles de etapas.

1. v133 cambia sólo el lote neuronal4→1. Reduce padding y limita activaciones;
   puede pagar más overhead de llamadas. Se decide con ALL200 real, no con la
   intuición de que un batch mayor/menor debe ser más rápido.
2. Después del cierre, usar la evidencia para elegir el siguiente cambio único:
   planificación por longitud, recursos de ORT o eliminación de copias/trabajo
   repetido. No correr otro benchmark de modelos en paralelo.
3. Mantener versiones sin pérdida de los dos pisos y con una mejora demostrada
   de coste; registrar también regresiones individuales aunque el total pase.
4. Congelar el candidato seleccionado antes de acceder a las nuevas preguntas.
   Ejecutar ambos candidatos con el mismo scorer de identidad y los mismos
   límites; reportar resultados nuevos por separado, sin mezclarlos con los200
   usados en ajustes para ocultar diferencias.

La referencia aproximada de1s/100 archivos sigue pendiente en los cuatro repos
pequeños. Informar tamaños indexados reales, p50/p95/máximo, carga/warmup y RSS;
no inflar el denominador con ficheros ignorados. CPU es obligatorio; esta tarea
no necesita GPU. No hay un tope numérico de RAM nuevo acordado.

## Pruebas nuevas y límites de independencia

Dos estratos de100:50clases+50símbolos y50módulos+50archivos. Cada tipo conserva
30EN/20ES y40behavior/10lookup. Fuentes/indexación son los mismos ocho repos
autenticados; esto comprueba consultas y piezas nuevas, no repositorios nuevos.
Se favorece disjunción de archivos con principalv98 y calibración mediante
exclusiones opacas. No mirar salidas/scores al curar ni adaptar preguntas al motor.

Las reservas anteriores y v104 permanecen cerradas. Sólo se admiten recibos
opacos externos ya conocidos para verificar exclusiones; si no existen, declarar
la intersección v104 no verificada y no buscar dentro de su payload. No inventar
una certificación de disjunción. Gold nuevo permanece privado y sólo se puntúan
salidas cerradas de ambos candidatos. Reportar intervalos y denominadores; un
90% observado en200 casos no prueba un piso poblacional90% con confianza95%.

Las pruebas de código ejercitan ONNX real sobre un grafo pequeño con respuestas
derivadas a mano: límite real de batch1, alineación de logits/documentos,
padding enmascarado y rechazo de configuración inválida. No se cuenta una prueba
unitaria adicional como un nuevo caso de recuperación acertado.

Referencia oficial consultada sobre recursos de runtime:
[ONNX Runtime: threads](https://onnxruntime.ai/docs/performance/tune-performance/threading.html),
[memoria](https://onnxruntime.ai/docs/performance/tune-performance/memory.html).
