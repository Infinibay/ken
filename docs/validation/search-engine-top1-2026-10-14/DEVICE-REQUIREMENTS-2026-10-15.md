# Dispositivos y presupuesto de ejecución

Aclaración explícita del usuario2026-10-15: CPU es el mínimo obligatorio, no una
prohibición de GPU. Sin GPU debe responder dentro del presupuesto; si existe un
acelerador utilizable, detectarlo y elegir la alternativa más rápida. Tener una
GPU potente nunca puede ser requisito. Mantener consumo de RAM moderado.

Referencia de tiempo autorizada: aproximadamente1segundo por cada100archivos del
repositorio; antes indicó una respuesta de3–5segundos como orientación relativa.
La letraX en la última aclaración no fija un nuevo número ni revoca esa referencia.
Reportar archivos indexados, latencia finalp50/p95 y peakRSS con alcance explícito.

La comparación registrada v98 continúa forzada enCPU para verificar el mínimo.
Su CPUExecutionProvider/máscarasCPU son controles experimentales, no el modo por
defecto decidido para producto. No modificar ni mezclar esos tiempos con GPU.

En integración normal: modoauto, conservar overrides explícitos y respaldar con
CPU ante proveedor ausente, inicialización/inferencia fallida, salida inválida o
menor rendimiento del acelerador. Medir latencia representativa completa de la
etapa con transferencias y calentamiento separados; disponibilidad no demuestra
queGPUsea más rápida en lotes pequeños. Reutilizar la política de dispositivos
existente antes de duplicar selección. La elección de backend no puede alterar
silenciosamente el modelo, el presupuesto visible ni los criterios de calidad.
