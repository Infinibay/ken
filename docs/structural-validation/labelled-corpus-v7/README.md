# Regresión GoF con IR 1.14.0

Se repitió el corpus de 281 ejemplos aislados con las 23 consultas GoF canónicas,
después de añadir contextos sintácticos de retry, comparación nula, enlace entre
llamadas y operaciones, e inicializadores C# sin campo de gramática.

Los hashes de entrada coinciden con v6. Se conservan las 53 presencias del patrón
etiquetado, sin pérdidas ni nuevas presencias. Todas las consultas finalizaron
dentro de presupuesto y no hubo excepciones del runner. `comparison.json` resume
la comparación; `manifest.json` fija commits y hashes del motor.

El corpus GoF no mide la cobertura de los nuevos queries modernos. Para cache-aside,
los tests propios cubren cinco lenguajes y la auditoría de iluwatar documenta
una variante Optional aún omitida. Las presencias de etiquetas no equivalen a
precisión de clasificación ni a exhaustividad de los frontends.
