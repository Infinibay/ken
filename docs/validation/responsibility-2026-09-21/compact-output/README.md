# Salida compacta por defecto

`ken_who` / `ken tools who` devuelve ahora estado, candidatos, ubicación, score
heurístico y una cita breve relevante. Conserva condiciones, contraevidencia,
supuestos de reformulación y el número de candidatos que no pudieron comprobarse.
`full=True` / `--full` devuelve el formato detallado anterior, sin cambiar el ranking.

En dos llamadas reales sobre Ken para «Who provides SQLite connection helpers?»,
ambos formatos conservaron los mismos candidatos y puntuaciones. El JSON normalizado
pasó de **6.832 a 538 caracteres: 92,1% menos**. Es una medición de este ejemplo,
no una estimación de tokens o ahorro general. Parte del diagnóstico completo
incluye candidatos omitidos al agotar el límite de lectura, retenidos como contador
en el compacto.

- [Respuesta compacta](compact.json)
- [Respuesta completa](full.json)
- [Comparación y comando](comparison.json)
- [49 pruebas pasadas](tests.xml)

Las pruebas incluyen el CLI real en ambos modos, paridad con MCP, conservación
del formato anterior en `--full`, selección de evidencia relevante, ambigüedad,
condiciones, delegación, negaciones y fuentes ausentes. Mypy pasó en los ocho
archivos del paquete; Ruff y la comprobación de espacios también pasaron.

El evaluador histórico `scripts/evaluate_responsibility.py` solicita ahora `--full`
para conservar su contrato de diagnóstico.
