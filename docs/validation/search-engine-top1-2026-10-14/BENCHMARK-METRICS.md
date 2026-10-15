# Qué significa el NDCG de Semble

Estado actual, 15 de octubre: hay dos conjuntos distintos. Sobre los 400 casos
de desarrollo, las respuestas intactas de API81 dan archivo top1 345/400
(86,25%) y NDCG@10 por archivo 0,9343641364861627. Las respuestas nativas
normalizadas de Semble dan 204/400 (51%) y 0,6887064071598579. El top1 estricto
de Ken en esos mismos casos es 286/400 (71,5%): exige además entidad o fragmento
admitido y todas las líneas decisivas visibles. El 51% nunca fue esa métrica.

En las 1251 consultas públicas de Semble, el último resultado completo de Ken
es NDCG@10 macro 0,8365028636773735 y top1 906/1251 (72,42%). Semble conserva
0,8543853795900258 y 935/1251 (74,74%). Por lo tanto no hay una contradicción:
Ken gana el diagnóstico de archivo de nuestros casos de desarrollo y pierde
la comparación pública externa. Los 400 casos están expuestos al proceso de
investigación; no sustituyen la reserva intacta ni demuestran generalización.
También difiere la versión: el resultado público corresponde al perfil48
(fuente5,235 señales); los400 actuales usan API81 (fuente7,251 señales y
política3 de evidencia). La repetición pública76b de esta base está pendiente;
no se trasladan los resultados de un perfil a otro sin ejecutarlo completo.

Los cálculos actuales de archivo sobre400 conservan los hashes de dataset,
respuestas y script en `output/development/ken-semble-file-ndcg-400-v81.json`
y `output/analysis/file-only-top1-v81-diagnostic.json`. No se repitieron búsquedas
ni se alteraron las referencias o el scorer estricto. Las secciones siguientes
conservan la explicación y las mediciones históricas de perfiles anteriores.

El 0,854 publicado por Semble es NDCG@10 sobre su propio benchmark, no una
proporción de primeros resultados correctos. Su scorer usa relevancia binaria,
ponderación `1/log2(rango+1)` y normaliza por el orden ideal. Con una sola
respuesta válida: rango 1 aporta 1; rango 2, aproximadamente 0,631; rango 10,
aproximadamente 0,289. Se promedian las puntuaciones de las consultas.

Fuente pública: [metodología](https://github.com/MinishLab/semble/blob/main/benchmarks/README.md),
[scorer](https://github.com/MinishLab/semble/blob/main/benchmarks/metrics.py) y
[coincidencia de referencias](https://github.com/MinishLab/semble/blob/main/benchmarks/data.py).
La copia examinada es commit `0e5e02832ae0340c0feb637d2b7213fe065571fd`.

El conjunto descargado contiene 1251 consultas y 1496 referencias, incluidas
243 secundarias. De esas referencias, 1462 sólo indican archivo y 34 incluyen
rango. Una referencia de archivo acepta cualquier chunk de ese archivo; una
referencia con rango acepta cualquier solapamiento con sus líneas. El scorer
usa el rango nativo completo del chunk, no necesariamente el prefijo que el
formateador muestra al agente. Consultas y referencias fueron generadas y
revisadas por un LLM según su documentación. Esto evalúa descubrimiento de
código y ranking; no demuestra función precisa y toda evidencia visible en top1.

Ken todavía no tiene un resultado comparable sobre ese benchmark completo.
Nuestro 37,75% histórico de top1 estricto no se puede comparar directamente
con su 0,854. La comparación común ya ejecutada usa nuestras mismas 400
consultas y las salidas de ambos motores: archivo top1 60,25% vs 51%; archivo
y todas las anclas visibles 37,75% vs 16,25%. Véase `SEMBLE-400.md` para las
limitaciones del adaptador externo y el control experimental de Ken utilizado.

Podemos añadir NDCG como diagnóstico complementario sobre conjuntos con
referencias de relevancia adecuadas. No reemplaza el gate aprobado de al menos
90% de top1 estricto, ni permite convertir un resultado de top10 en top1.

## Diagnóstico común calculado después de la consulta del usuario

Sobre las mismas 400 consultas y salidas anteriores de Ken-role-v11 y Semble
nativo normalizado v2, se aplica NDCG binario por archivo. Cada archivo válido
recibe crédito sólo en su primera aparición; se normaliza por los archivos
válidos distintos de las referencias originales. No se juzga aquí la función
ni las anclas visibles. No se cambian las referencias del scorer estricto.

| Métrica de archivo | Ken | Semble |
|---|---:|---:|
| NDCG@10 | 0,724404 | 0,688706 |
| Archivo top1 | 0,6025 | 0,51 |
| Algún archivo válido entre diez | 0,855 | 0,8575 |

La cobertura de archivo entre los primeros diez es casi igual; Ken ordena
antes sus archivos válidos. Esto no compara con el 0,854 del otro conjunto de
1251 consultas, ni mide la aceptación estricta. Recibo completo con hashes y
400 puntuaciones por motor: `output/development/ken-semble-file-ndcg-400.json`;
script `experiments/search-engine/score_file_ranking.py`, con cinco ejemplos
matemáticos verificados antes de calcular resultados.

## Control posterior v15

Con política de tokenizer corregida y preferencia de escritura literal para
símbolos, Ken obtiene NDCG de archivo 0,739228, archivo top1 247/400 (61,75%) y
archivo entre diez 350/400 (87,50%). Semble permanece en 0,688706, 204/400 (51%)
y 343/400 (85,75%) en las mismas salidas nativas. Se conserva el recibo anterior;
el nuevo es `output/development/ken-semble-file-ndcg-400-v15.json`.
El control Ken pasa además top1 estricto en 157/400 (39,25%). Esta cifra no es
un NDCG, no pertenece al benchmark externo de 1251 consultas y no demuestra
el 90% aprobado. No se ha promovido el control de rol a configuración pública.

## Comparación directa completada en las 1.251 consultas de Semble

La corrida completa posterior reprodujo NDCG@10 0,854385 de Semble, con los
63 repositorios, revisiones y scopes originales, el scorer sin modificar y
cero consultas faltantes o errores. Ken API archivos obtiene 0,812770;
el ranking antes del recorte de presentación obtiene 0,818562. El control
experimental por propósito llega a 0,822199 antes del recorte. En este
conjunto Semble conserva la ventaja. El top1 según sus referencias es
935/1251 (74,74%) para Semble y 859/1251 (68,67%) para Ken API archivos.

Se verificaron 5.004 prefijos para aislar el recorte de presentación. El
resultado estricto de 157/400 y el objetivo del 90% permanecen separados.
Informe completo, metodología, controles y recibos:
[SEMBLE-PUBLIC-BENCHMARK.md](SEMBLE-PUBLIC-BENCHMARK.md).
