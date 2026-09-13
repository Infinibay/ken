# Plan de implementación y validación

Estado: diseño y criterios de aceptación; no resultados de tests nuevos.
Volver al [índice](README.md).

## 1. Puerta de entrada a implementación

Antes de continuar el motor, completar una revisión del diseño con los siguientes
artefactos. No es una solicitud automática de permiso; es una condición de calidad
para no fijar accidentalmente las limitaciones del prototipo.

| Artefacto | Estado en esta revisión | Criterio para avanzar |
|---|---|---|
| Identidad, tipo/valor/storage y evidencia | Propuestos | Ninguna regla confunde nombres con identidad |
| Semántica de unknown, negación y cardinalidad | Propuesta | Contraejemplos de mundo abierto resueltos sin falsos negativos |
| Gramática y bindings | Referencia abreviada | Gramática completa y diagnósticos definidos antes del parser |
| 23 patrones y variantes | Análisis por patrón | Cada variante tiene claim, requisitos y negativos |
| Archivos declarativos | Borradores visibles | Queries completas, schema congelado y carga segura |
| Ejemplos de ocho lenguajes | Fragmentos documentados | Fixtures autónomas y baseline semántico revisado |
| Costos y memoria | Presupuestos de diseño | Benchmark reproducible, sin promesas no medidas |
| Rust o Python | Decisión pendiente de mediciones | Misma semántica, empaquetado verificado en plataforma objetivo |

La revisión encontró brechas suficientes para **no considerar el prototipo listo**.
No se continuó implementando el motor durante esta fase de documentación. Los
checks anteriores del prototipo no validan el lenguaje propuesto aquí.

## 2. Orden de construcción propuesto

1. Congelar un núcleo pequeño: schema tipado, identidad, spans, bindings, resultados
   y contratos de vistas. Convertir ejemplos representativos en oráculos revisados.
2. Parser KenQL y evaluador de referencia sobre grafos hechos a mano. Demostrar
   semántica de joins, unknown, variantes, negación y cardinalidad sin depender aún
   de la calidad del frontend.
3. Adaptadores para sintaxis y declaraciones de ocho lenguajes. Publicar matriz de
   capacidades reales. Conservar nodos no normalizados.
4. Resolución, operaciones y flujo local; imports/exports y modelos mínimos de APIs.
   Validar primero Builder, Iterator, Strategy funcional y Factory Method.
5. Loader declarativo y catálogo. Una variante se activa solo si su consulta y
   fixtures están completas. El archivo puede existir con variantes aún draft.
6. Ampliar flujo entre llamadas, recursos y concurrencia de forma incremental.
7. Índices, cachés y backend optimizado sobre el mismo corpus semántico.
8. CLI/MCP, agrupaciones por directorio, documentación de cobertura y packaging.

No presentar «23 soportados» porque hay 23 nombres en el catálogo. Publicar cobertura
por `(patrón, variante, lenguaje, capacidad, test)`.

## 3. Arquitectura de caché y rendimiento

Default: **500 MB decimales = 500,000,000 bytes de almacenamiento persistente**.
Es configuración de producto propuesta. No es un límite de RAM del proceso.

Capas cacheables: IR por archivo, exports y resúmenes por módulo, componentes de
resolución, índices de snapshot y plan compilado de consulta. Resultados de consulta
solo si su clave incluye snapshot, versión de regla, modo de evidencia y opciones
semánticas. Un resultado parcial no se reusa como exhaustivo.

Claves: hashes de contenido, ruta lógica, versiones de grammar/adaptador/schema,
configuración de lenguaje, modelos de API y dependencias semánticas. No confiar
solo en mtime. Un cambio de alias exportado invalida consumidores aunque sus textos
no cambien. Separar invalidez de parseo de invalidez de linking.

Evicción LRU con bytes reales, incluyendo índices persistentes. Entradas mayores
que el límite se procesan sin cachear. Cero desactiva lectura/escritura de caché para
permitir comparación reproducible. Configuración inválida produce error claro;
archivo de caché corrupto produce recuperación controlada. Escrituras atómicas y
coordinación de procesos deben impedir sobrescrituras parciales y pérdida de
actualizaciones en el registro de reglas.

RAM, resultados intermedios y tiempo tienen límites propios. Índices por kind,
relación, extremos y atributos selectivos; planificar joins por cardinalidad; compilar
alternativas compartidas una vez; limitar Cartesian products y caminos; recuperar
source snippets solo al renderizar resultados. Las búsquedas de nombre deben evitar
análisis de efectos costoso. Cargar 23 archivos de reglas no equivale a reparsar el
proyecto 23 veces.

## 4. Protocolo de benchmarks

Datasets: 100, 1.000 y 10.000 archivos; mezcla por lenguaje; proyectos con imports
cíclicos, overloads, closures, grandes funciones y muchos homónimos. Un corpus
sintético valida escalado, pero también medir repositorios reales con licencia y
revisión humana de muestras.

Separar: scan/hash, parseo, lowering, resolución, flujo, índices, compilación de
query y evaluación. Medir cold/warm y un cambio de archivo/export, CPU, RSS máximo,
tamaño persistente, p50/p95 por varias repeticiones y resultados completos/parciales.
Registrar hardware, versión, worker count, procesos externos y configuración.

Consultas: selector exacto, regex, join selectivo, join de alta cardinalidad,
negación, conteo, camino cíclico y lote de variantes. Verificar resultados antes
de comparar velocidad. No aceptar un backend «más rápido» que omita relaciones o
aplique budgets más bajos. No hay objetivo de milisegundos comprometido hasta medir
el diseño completo.

## 5. Rust y distribución

PyPI distribuye wheels con extensiones nativas y sdist; la guía PyPA incluye
Maturin como backend para extensiones Rust. No hace falta convertir Rust a C.
[PyPA: Maturin](https://packaging.python.org/en/latest/key_projects/#maturin).

Una opción es núcleo Rust para tablas/joins/caminos y wrapper Python. Evitar cruzar
la frontera por cada arista: intercambiar buffers o lotes y devolver bindings
compactos. Otra opción es Python hasta encontrar el cuello real. Ninguna obliga
a cambiar KenQL ni los archivos del catálogo.

`uv tool install ken` debe instalar un wheel compatible cuando esté publicado.
Instalar desde sdist un núcleo Rust requeriría toolchain Rust y herramientas de
compilación, salvo fallback Python explícito. PyPI no compila el Rust por el usuario.
La disponibilidad de wheels depende de tags de Python, arquitectura, ABI y libc.
Linux y macOS son los objetivos; definir x86_64/arm64, glibc/musl y versiones mínimas
en la fase de packaging. No prometer «Linux» universal con un único wheel.

Criterios: instalar wheel en entorno limpio sin Rust; instalar sdist con toolchain;
`uv tool install` y CLI/MCP operativos; archivos `.toml` del catálogo incluidos en
wheel y sdist; tests de conformidad idénticos entre backends. Verificar las matrices
actuales de Maturin/PyO3 cuando se elija esa implementación.

## 6. Corpus multilenguaje

Cada uno de los 184 fragmentos del catálogo (23 × 8) inicia una fixture documental,
no una casilla ya aprobada. Algunas son variantes funcionales, no GoF clásico.
Cada fixture final debe tener imports y tipos auxiliares, versión de lenguaje,
programa válido y oráculo manual de roles/hechos esperados.

Por variante/lenguaje aplicable:

- Positivo mínimo y positivo idiomático con nombres renombrados.
- Negativo cercano eliminando una relación esencial.
- Variante con aliases/imports y llamada en otro archivo.
- Ambigüedad de tipos o dependencia ausente que exige candidate/unknown.
- Identificadores homónimos y shadowing para evitar enlaces falsos.
- Reordenamiento léxico inocuo y cambio de formato que no cambien la detección.
- Ejemplo de sintaxis avanzada pertinente: closure, yield, generics, spread, etc.

No imponer ocho copias literales del mismo ejemplo con clases. La fixture Go de
Template Method por composición tiene distinta variante de una Java con override.
Una macro Rust no expandida puede tener resultado esperado `unsupported`, no match.

Los compilers verifican validez de fixtures cuando estén disponibles en CI. Tree-
sitter debe verificarse por separado: parsear sin error no prueba tipado correcto.
No ejecutar código del repositorio analizado; ejecutar fixtures propias en pruebas
es una operación distinta y controlada.

## 7. Oráculos y pruebas del lenguaje

Grafos construidos a mano para probar semántica de consultas independientemente
del frontend. Dos backends deben producir los mismos bindings, estado de verdad,
evidencia esencial y razones de incompletitud. No comparar solamente cantidades.

Casos mínimos: identidad vs nombre; variables libres; optional sin multiplicación;
uniones con scopes; ausencia con mundo abierto; cuentas con intervalos; cero saltos;
ciclos; límites de tiempo/filas; regex inválida o costosa; Unicode; nulos vs atributos
ausentes; TypeScript unknown; spreads y bindings parciales; errores de schema.

Pruebas metamórficas: renombrar símbolos preserva firmas no nominales; agregar clase
homónima no enlaza destinos; eliminar evidencia obligatoria degrada o elimina match;
reducir cobertura nunca vuelve demostrada una negación antes desconocida; acotar
presupuesto nunca transforma un resultado parcial en «ausencia confirmada».

Fuzzing de parser, serialización y loader declarativo con límite de recursos. Queries
inválidas deben rechazarse antes de escanear todo el repo. Serialización round-trip
conserva modalidad, scopes, spans y versiones, no solo entidades.

## 8. Calidad del catálogo y criterios de release

Un test positivo demuestra una forma concreta. Para estimar precisión, etiquetar
muestras externas con varios revisores y registrar desacuerdos de intención.
Separar precisión de firmas de la atribución del nombre GoF. Reportar falsos
positivos/negativos por variante; no promediar todos los lenguajes como si fueran
uniformes.

Release exige: corpus versionado, regresión de Ken existente, typing/lint pertinentes,
packaging de reglas, explicaciones útiles, presupuestos y límites documentados,
y ninguna variante habilitada sin consulta y negativos revisados. Reglas draft
siguen visibles pero no se ejecutan por defecto. Los resultados deben indicar
versión y variante para reproducirse después de actualizar el catálogo.
