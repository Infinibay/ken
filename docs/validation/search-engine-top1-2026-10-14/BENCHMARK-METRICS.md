# Qué significa el NDCG de Semble

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
