# Ken en el benchmark público completo de Semble

Actualización2026-10-15: **Semble conserva la ventaja**. Su NDCG@10macro es
**0,854385**, frente a **0,836503** del Ken contextual235CPU (48), que mejora desde
**0,818955** del control21. En las1251consultas públicas, top1: Ken906/1251
(72,42%) ySemble935/1251 (74,74%). Las referencias son mayormente dearchivo;
no equivalen al90%estricto de función y todas sus líneas decisivas visibles.

## Corrida contextual48 completa

| Variante | MacroNDCG@10 | MicroNDCG@10 | Top1 público | Hit@10 |
|---|---:|---:|---:|---:|
| Semble original fijado |0,8543853796|0,8546561631|935/1251|98,96%|
| Ken21 anterior |0,8189553482|0,8192913662|857/1251|96,80%|
| Ken48 contextual235CPU |0,8365028637|0,8368466502|906/1251|96,72%|

Los63workers48 completaron1251IDsúnicos,exit0 y0errores/faltantes, con índices
fuente100235owners preparados antes de consultas. El modelo numérico se entrenó
sólo en16repos de desarrollo disjuntos; no con relevancias de estos63. La
comparación es pública y adaptativa de investigación, no aceptación ciega.
Usa el mismo scorer original, mismas consultas/targets y máximo10puestos.
El perfil conserva fuente5 (incluido el defectoC heredado); el índicecorregido7
requiere otra corrida real, no una etiqueta nueva sobre vectores anteriores.

El parent48 falló sólo al importar Semble para el cálculo final desde la venv
API.48b evaluó sus respuestas intactas en la venv Semble instalada y verificó
hashes de todas las fuentes originales/adapter/scorer. No repitió búsquedas ni
modificó resultados, referencias o puestos. Ambos recibos y el fallo quedan
preservados en `output/development/semble-contextual-v48/`.

[Reporte48porconsulta](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-contextual-v48/report.json),
[registro48](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-contextual-v48/registration.json) y
[recibo48b del scorer](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-contextual-v48/rescore-registration.json).
RSS descriptivo394,45–749,48MiB/worker, sin Torch/Transformers importados;
p95 porrepo160,10–14212,50ms,31/63exceden1s/100ci_files en corrida concurrente.
No se afirma cumplimiento final de recursos. El checkout original/default no
fue promovido y la reserva independiente sigue sin abrirse.

## Serie inicial15 (histórica)

En la serie inicial del2026-10-14, Ken archivosAPI obtuvo0,812770, sus ubicaciones
antes del recorte0,818562 y el control porpropósito0,822199. Las tablas y detalles
siguientes documentan esa serie, no reemplazan la comparación48 anterior.

Completamos las **1.251 consultas originales, 63 repositorios, 19 lenguajes**, sin consultas faltantes ni errores en ninguno de los motores. La referencia de Semble se volvió a ejecutar localmente y coincide con sus 63 resultados publicados con una diferencia máxima de 2.22e-16. No se ajustó el motor con estos resultados.

## Resultados comparables

NDCG principal: promedio de los 63 promedios por repositorio, exactamente como `run_benchmark._save_results`. El README describe promedio por consulta; también conservamos ese segundo agregado en los JSON. El 0.8544 publicado corresponde al primero.

| Herramienta / configuración | NDCG@10 API nativa | NDCG@10 ubicaciones antes del recorte | Top-1 según referencias del benchmark | Hit@10 API |
|---|---:|---:|---:|---:|
| Semble original | 0.854385 | 0.854385 | 935/1251 (74.74%) | 98.96% |
| Ken API: archivos | 0.812770 | 0.818562 | 859/1251 (68.67%) | 96.48% |
| Ken API: símbolos | 0.785868 | 0.788281 | 859/1251 (68.67%) | 93.76% |
| Ken control por propósito: archivos | 0.814648 | 0.822199 | 867/1251 (69.30%) | 96.24% |
| Ken control por propósito: símbolos | 0.785473 | 0.787887 | 867/1251 (69.30%) | 93.21% |

Las variantes por propósito son controles de banco existentes, separados de la API pública. La API experimental usa el mismo perfil Potion CPU que veníamos midiendo; el checkout original y su configuración predeterminada siguen sin integrar estos cambios. La columna de ubicaciones es un diagnóstico de recuperación, sin cuerpos de fuente en la respuesta; no certifica el contrato de evidencia visible.

Promedio por consulta: Semble **0.854656**, Ken archivos API **0.813603**, Ken archivos antes del recorte **0.819295**.

## Qué se mantuvo idéntico

- Semble 0.6.2, commit `0e5e02832ae0340c0feb637d2b7213fe065571fd`. Los 63 commits de `repos.json` y cada `benchmark_root` se verificaron antes de ejecutar; se conservan los repositorios y sus subdirectorios declarados.
- Todas las consultas de `load_tasks`, en su orden original, y sus **1.253 referencias principales + 243 secundarias = 1.496 objetivos**. No se excluyeron repositorios o lenguajes por soporte del parser ni por rendimiento.
- Se importaron sin modificar `benchmarks.metrics.target_rank` y `ndcg_at_k`. Relevancia binaria, descuento logarítmico, coincidencia por ruta y solapamiento de rango cuando existe. Se conserva incluso la colisión de dos referencias en un mismo puesto.
- Diez puestos como máximo. Ninguna deduplicación en el scorer ni fragmentos convertidos en puestos adicionales. El modo archivos de Ken deduplica dentro de su API existente; el modo símbolos conserva su lista de entidades.
- Modelo fijado `minishlab/potion-code-16M-v2`, revisión `e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b`; pesos SHA256 `75cf7a6c2171b230ad19b1e7d8e0b1aee86da5a02af8e7cacedd9921d227623c`. Los motores mantienen sus propias representaciones, política de tokenización e ignorados, registradas en los artefactos.
- Semble: `alpha=None`, `rerank=True`, cinco búsquedas por consulta y evaluación de la última lista, igual que su runner. Ken: perfil congelado v15, propósito `auto`, sin juez neuronal adicional y sin pistas de categoría, idioma u objetivos en las solicitudes.

El rango comparado es el chunk nativo de Semble y el `entity_span` nativo de Ken. También conservamos un diagnóstico de solapamiento del primer fragmento visible. Ninguno de estos diagnósticos equivale a exigir todas las líneas decisivas de una implementación.

## Cuánto influye el formato

La API de archivos de Ken conserva un máximo de 12.000 caracteres JSON y 40 líneas visibles por resultado: devuelve en promedio **6.744 resultados** en esta corrida. La observación de las ubicaciones nativas devuelve **9.035**; las búsquedas exactas únicas conservan su corte temprano y algunos pools contienen menos de diez archivos. Semble devuelve diez en cada consulta.

El protocolo suplementario se registró después de la medición inicial para aislar ese efecto. No se cambiaron ranking, índices, modelo ni consultas. Se verificaron **5.004 comparaciones de prefijo**: en las cuatro variantes y todas las consultas, la secuencia devuelta por la API es exactamente el prefijo del ranking observado antes del recorte.

Para archivos API, retirar el recorte añade **0.005792 NDCG**, y la brecha restante con Semble es **0.035824**. El top-1 permanece en **859/1251**. El formato explica una parte pequeña de la diferencia; el resto sigue en el conjunto de decisiones de indexación, recuperación y ordenamiento. Esta última atribución conjunta es una inferencia del control, no una ablación que identifique cada causa.

## Dónde aparecen las diferencias

Promedios por lenguaje calculados sobre sus promedios por repositorio:

| Lenguaje | Repos | Ken archivos API | Semble | Diferencia Ken − Semble |
|---|---:|---:|---:|---:|
| bash | 3 | 0.8529 | 0.8396 | +0.0133 |
| c | 3 | 0.7036 | 0.7550 | -0.0514 |
| cpp | 3 | 0.8374 | 0.8876 | -0.0501 |
| csharp | 3 | 0.8197 | 0.8715 | -0.0518 |
| elixir | 3 | 0.8687 | 0.9059 | -0.0372 |
| go | 3 | 0.8231 | 0.9103 | -0.0872 |
| haskell | 3 | 0.7258 | 0.7736 | -0.0478 |
| java | 3 | 0.7771 | 0.8027 | -0.0255 |
| javascript | 3 | 0.8865 | 0.9111 | -0.0246 |
| kotlin | 3 | 0.7904 | 0.8026 | -0.0121 |
| lua | 3 | 0.9005 | 0.8354 | +0.0651 |
| php | 3 | 0.8423 | 0.8638 | -0.0216 |
| python | 9 | 0.8457 | 0.8771 | -0.0314 |
| ruby | 3 | 0.8468 | 0.9154 | -0.0686 |
| rust | 3 | 0.7168 | 0.8263 | -0.1095 |
| scala | 3 | 0.8855 | 0.9213 | -0.0358 |
| swift | 3 | 0.7657 | 0.8478 | -0.0821 |
| typescript | 3 | 0.6983 | 0.7420 | -0.0436 |
| zig | 3 | 0.7900 | 0.8990 | -0.1091 |

Ken trata Haskell, Scala, Swift, Elixir, Lua y Zig como texto en este perfil. Esa limitación queda incluida. Las diferencias grandes también aparecen en lenguajes con parser, como Rust y Go; por tanto esta comparación no permite atribuir el déficit sólo al soporte de lenguajes.

Promedios por consulta dentro de cada categoría (703 semantic, 344 architecture, 204 symbol):

| Categoría | Ken archivos API | Semble |
|---|---:|---:|
| semantic | 0.8111 | 0.8466 |
| architecture | 0.7511 | 0.8091 |
| symbol | 0.9277 | 0.9592 |

El control por propósito apenas mejora el agregado global y empeora Bash de 0.8529 a 0.7168. Este resultado desaconseja promover esa prioridad como regla universal sin revisar sus supuestos y su clasificación de roles.

## CPU, memoria y alcance de la medición

Ambos motores corrieron en CPU. Ningún proceso de recuperación cargó Torch, Transformers o MLX. El máximo RSS del proceso principal de un repositorio fue **384.7 MiB en Ken** y **543.2 MiB en Semble**. Estas cifras no incluyen la suma de todos los procesos: Semble empleó cuatro workers de indexación y Ken parsing serial por repositorio; se prepararon varios repositorios en paralelo y cada repositorio usó un proceso nuevo.

Las latencias y tiempos de indexación están conservados, pero la preparación concurrente y las cinco repeticiones de Semble frente a una llamada por modo de Ken impiden tratarlas como una certificación aislada o una comparación controlada de velocidad.

## El objetivo del 90% sigue vigente

**1.462 de 1.496 referencias sólo identifican archivo** y 34 incluyen rango. Para estas últimas basta cualquier solapamiento. El top-1 de la tabla usa ese criterio público. El objetivo aprobado de Ken conserva archivo + entidad o fragmento correctos + TODAS las anclas decisivas visibles, dentro de los presupuestos acordados. La serie inicial de desarrollo obtuvo157/400 (39,25%); la API validada posterior74b alcanza286/400 (71,5%) sobre fuente7 real, con política3 de evidencia y16modelos251 excluyendo su repo. Ninguna alcanza90%. Estos resultados se mantienen separados del benchmark público. La reserva privada no fue abierta ni utilizada en esta corrida.

## Evidencia y reproducción

- [Resultados completos por consulta y hashes de respuestas](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-public-1251-v1/scores.json)
- [Ubicaciones sin recorte, paridad y hashes](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-public-1251-v1/locations-only-scores.json)
- [Verificación de integridad, dispositivo y memoria](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-public-1251-v1/integrity.json)
- [Reproducción de los 63 resultados publicados](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-public-1251-v1/reference-reproduction.json)
- [Registro de consultas y revisiones](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-public-1251-v1/registration.json)
- [Solicitudes públicas sin referencias](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/development/semble-public-1251-v1/requests.jsonl)
- [Protocolo principal](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/experiments/search-engine/semble-public-protocol-v1.md) y [diagnóstico suplementario](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/experiments/search-engine/semble-public-protocol-v2.md)
- [Productor público](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/experiments/search-engine/semble_public_run.py), [adaptador al scorer original](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/experiments/search-engine/semble_public_score.py) y [observador de ubicaciones](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/experiments/search-engine/semble_public_locations.py)
- [Scorer original fijado](/private/tmp/ken-search-eval-20261014/tools/semble/benchmarks/metrics.py) y [resultado publicado fijado](/private/tmp/ken-search-eval-20261014/tools/semble/benchmarks/results/semble-hybrid-a772a37d558c.json)

Seis pruebas del adaptador pasan, incluida conservación de puestos, referencias que colisionan, consultas faltantes y promedios macro/micro. Todos los 1.251 IDs aparecen exactamente una vez por modo; cero errores. La identidad del productor coincide entre todos los repositorios y ambos motores. El engine se validó contra su manifiesto congelado antes de cada proceso.

Recepción de fuente Ken: `731391de6f32dd636bb8e24588867a6f4e841ee5dedc55b570e8ec1a77dd74be`. Perfil: `666916dcd69f00fd3f161cb8d203931adcccf0691d056124c4f09cc08f9506b3`. Consultas públicas SHA256: `c8ccb7efc678ccb97b5a03442047ee630b1e225d6009682584d0ffc6f14aca53`.

Para volver a calcular las métricas sin ejecutar los motores:

```bash
cd /Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace
PYTHONPATH=/private/tmp/ken-search-eval-20261014/tools/semble \
  /private/tmp/ken-search-eval-20261014/venv/bin/python \
  experiments/search-engine/semble_public_score.py \
  output/development/semble-public-1251-v1 \
  --tool-root /private/tmp/ken-search-eval-20261014/tools/semble \
  --output /private/tmp/ken-semble-public-rescore.json
```
