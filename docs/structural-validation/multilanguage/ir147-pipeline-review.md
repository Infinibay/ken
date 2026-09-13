# IR 1.47: catálogo, buscador y caché del grafo

Continuación de la [revisión algorítmica GoF](gof-algorithm-review.md). Se comprobaron
los 33 TOML públicos: 23 conceptos GoF y diez modernos, con 56 variantes ejecutables
y 15 operaciones. Las 34 variantes en diseño siguen visibles y no se anuncian
como implementadas. La [auditoría del catálogo](catalog-ir-contracts.md) distingue
validación de una consulta, positivos fuente y garantías semánticas.

## Cambios funcionales

Las consultas de uso del ejercicio pasan al TOML de su patrón y se pueden componer
mediante `match` o seleccionar desde la CLI:

- `factory-method.client_flow`
- `builder.directed_state`
- `bridge.returned_primitive`
- `strategy.consumed_policy`
- `template-method.dependent_steps`
- `singleton.observed_lazy_use`

Las consultas originales y las operaciones publicadas coinciden en 34 controles
positivos/negativos. Sus contratos son opcionales: no toda implementación válida
de un patrón tiene que retornar un resultado, usar dos hooks o tener un director.

La [revisión moderna](modern-catalog-review.md) agrega 149 pruebas y la variante
opt-in `architecture.dependency-injection#retained-object`. Rechaza sobrescrituras
lineales de input/campo y conserva la consulta general para configuraciones no
lineales. Cada concepto moderno tiene positivos y negativos en tres lenguajes,
con trabajo independiente alrededor del algoritmo. Esto no prueba todas las
variantes ni la intención de un programa arbitrario.

## Rendimiento y conservación de resultados

1. Los caminos acotados evitan repetir estados convergentes a igual profundidad
   y modalidad. Conservan el primer testigo; no colapsan distintas profundidades,
   porque un ciclo puede satisfacer un mínimo de longitud. El
   [caso sintético](ir147-path-convergence.json) pasa de 524.286 a 70 aristas
   examinadas, manteniendo dos resultados. El
   [runner](../../../examples/bench/validate_path_query.py) permite reproducir el
   caso; no representa un factor de aceleración general en repositorios.
2. La compilación reutiliza AST por texto exacto dentro de una petición, entre
   validación y ejecución. Cada regla sigue validando su metadata. No hay AST
   mutable compartido entre peticiones ni caché que esconda ediciones de consultas.
3. El índice agrupa relaciones al crearse y construye los índices de sujeto/objeto
   sólo al necesitarlos. Mantiene orden, duplicados de hechos, snapshot de miembros
   y selección del bucket menor. Esto evita construir índices completos en pases
   que sólo recorren unas pocas relaciones.

La [medición del pipeline](search-pipeline-review.md) separa parseo, enlace,
proyección, búsqueda y caché fría/caliente sobre fuentes externas. Desplazar trabajo
hacia el primer acceso a un índice no cuenta por sí solo como mejora: se mide
la búsqueda completa además de cada etapa.

Con el mismo catálogo y cinco repeticiones sin la suite en paralelo, la mediana
de búsqueda con caché caliente baja de **161 a 68 ms** en Retry Java, de
**119 a 51 ms** en Chain Rust y de **2.718 a 2.208 ms** en Flask. Son scopes de
8, 7 y 24 archivos respectivamente, no repositorios completos. El enlace de Flask
baja de 3.636 a 1.066 ms y el pico de asignaciones Python de aproximadamente
165 a 130 MB.

Existe una regresión de etapa: el lote aislado `execute_rules` de Flask sube de
376 a 723 ms en ese harness. La construcción de índices y la recolección de
objetos se concentran en otros momentos. Dos probes de índices anticipados no
ofrecieron una mejora consistente de tiempo/cola/memoria y se descartaron.
La búsqueda completa mejora, pero una cache hit de Flask todavía ronda dos
segundos. Reducir reconstrucción y volumen del grafo sigue siendo trabajo pendiente.

La [regresión externa](ir147-pipeline-corpus.json) conserva 74 presencias esperadas
en 281 ejemplos y 6.463 consultas completas, con los mismos matches, archivos,
commits, hechos y diagnósticos. Las etiquetas de directorio no son un oráculo de
precisión/recall. No se atribuye un aumento de cobertura a esta optimización.

## Caché

La caché existente guarda unidades y el grafo completo comprimidos en SQLite, con
límite configurable de 500 MB decimales por defecto. La clave incluye contenido,
ruta, lenguaje, versión del IR y parsers. Un hit del grafo evita parsing y enlace;
no evita descompresión, reconstrucción de objetos ni proyección para consultar.

Las nuevas [pruebas de invalidación](../../../tests/structural/test_graph_cache_invalidation.py)
verifican edición, alta, baja, cambio de parser y aislamiento ante mutaciones del
llamador. Los archivos sin cambios se reutilizan cuando falla la clave del grafo;
se vuelve a enlazar el proyecto completo. No hay aún enlace incremental entre
archivos ni caché persistente de resultados del buscador.

Configuración en `.ken/structural.json`:

```json
{"cache": {"enabled": true, "max_mb": 500}}
```

`KEN_STRUCTURAL_CACHE_MB` y el argumento explícito tienen precedencia. Cero desactiva
la caché. Las pruebas existentes conservan eviction, presupuesto físico, concurrencia
y recuperación de entradas corruptas.

## Validación final

Los [controles finales](ir147-pipeline-checks.json) registran **7.257 passed y
149 xfailed** en 261,64 segundos para todo Ken. La auditoría focal del catálogo
pasa 262 pruebas; incluye una aserción de cobertura agregada después de la
colección de la suite completa. Mypy pasa en 107 archivos. El
[wheel verificado](ir147-pipeline-wheel.json) contiene los 67 módulos/TOML exactos
del motor escaneado: fuera del checkout exporta/verifica 69 fixtures y ejecuta
las 104 definiciones del catálogo sobre un grafo vacío sin matches espurios.

## Límites que permanecen

El nuevo núcleo de instrucciones no sustituyó todavía el grafo que consume KenQL.
Quedan análisis de definiciones que alcanzan argumentos, aliases, efectos y valores
entre métodos. Los 149 xfail del ejercicio GoF hacen visibles obligaciones aún no
satisfechas; algunas son contratos opcionales más fuertes. Ninguna optimización
convierte esas expectativas pendientes en pruebas aprobadas.
