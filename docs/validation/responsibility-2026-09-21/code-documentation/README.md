# Documentación de módulos, clases, métodos y funciones

Se amplió `ken_who` para incluir la documentación de módulos. La versión anterior
ya consultaba funciones, métodos y clases del índice de código; el ejemplo sobre
«guardar findings» no significaba que consultara las notas persistidas.

El índice guarda los docstrings de módulo en `ci_intent_sources` con
`source_kind='module_docstring'` y sin `symbol_id`. La búsqueda ahora incluye esas
filas además de los símbolos. La lectura actual mantiene su propietario y la
inspección de un módulo apunta al fragmento de documentación mediante líneas,
sin inventar un qualname de función.

Cuatro llamadas reales a `python -m ken tools who`, con el modelo configurado
`ken/static-qwen3-r512-v2`, devolvieron primero el componente esperado:

| Responsabilidad consultada | Tipo | Primer resultado | Confianza heurística |
|---|---|---|---:|
| Ayudas de conexión SQLite | Módulo | `src/ken/db.py` | 0,637 |
| Resolver imports JS/TS con tsconfig y workspaces | Clase | `AliasResolver` | 0,890 |
| Hacer fsync de segmentos modificados | Método | `VectorStore.flush` | 0,857 |
| Resolver rutas confinadas al proyecto | Función | `resolve_project_path` | 0,750 |

Las preguntas usan términos próximos a los docstrings: validan el recorrido y
los tipos, no comprensión general o probabilidad calibrada. Las limitaciones
lingüísticas y de recuperación de la evaluación inicial siguen vigentes.

Respuestas completas: [módulo](module.json), [clase](class.json),
[método](method.json), [función](function.json).
[Resultados con preguntas y comandos reproducibles](results.json).

Pasaron **45 pruebas focales**, incluidas ocho regresiones nuevas. Cubren los
cuatro tipos por MCP y CLI con una nota persistida engañosa que no debe afectar
la búsqueda; la documentación de padres no se atribuye a hijos; retirar o cambiar
un docstring de módulo no reutiliza la afirmación anterior; y un nombre de módulo
igual al qualname de un método no produce una colisión. Mypy pasó en los siete
archivos del paquete.

```sh
.venv/bin/python -m pytest tests/test_responsibility.py tests/test_mcp_schema.py \
  tests/test_mcp_read.py tests/test_doc_intent_integration.py -q -o addopts=''
```

Cada resultado conserva `kind`, `source.documentation_kind`, evidencia,
supuestos, score y `coverage.findings_used=false`. La confianza sigue siendo
heurística: citar documentación actual no demuestra el comportamiento del código.
