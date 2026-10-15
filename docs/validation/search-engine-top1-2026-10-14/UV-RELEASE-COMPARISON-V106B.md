# Ken publicado frente al experimental: mismas 200 consultas

15 de octubre de 2026. La release limpia `ken-rank==0.17.0`, instalada mediante
`uv tool`, obtiene **45/200 (22,5%) top‑1** y **103/200 (51,5%) top‑10**.
El motor experimental v102 obtiene **168/200 (84%)** y **197/200 (98,5%)**,
respectivamente. Ambas métricas exigen identificar la pieza solicitada:
clase, módulo, símbolo o archivo. Esta comparación no puntúa suficiencia de
evidencia y no constituye aceptación sobre la reserva privada nueva.

| Tipo, 50 consultas cada uno | Publicado top‑1 | Experimental top‑1 | Publicado top‑10 | Experimental top‑10 |
|---|---:|---:|---:|---:|
| Clase | 9/50, 18% | 44/50, 88% | 26/50, 52% | 50/50, 100% |
| Módulo | 14/50, 28% | 44/50, 88% | 32/50, 64% | 49/50, 98% |
| Símbolo | 10/50, 20% | 43/50, 86% | 18/50, 36% | 50/50, 100% |
| Archivo | 12/50, 24% | 37/50, 74% | 27/50, 54% | 48/50, 96% |
| Total | 45/200, 22,5% | 168/200, 84% | 103/200, 51,5% | 197/200, 98,5% |

Las diferencias observadas son +61,5 puntos porcentuales en top‑1 y +47 puntos
en top‑10. El conjunto de desarrollo tiene 30 consultas EN y 20 ES por tipo,
40 de comportamiento y 10 de búsqueda calificada por tipo, sobre ocho repos.
La ventaja corresponde al pipeline completo: no a un único cambio o modelo.
No es comparable directamente con la primera muestra histórica de 60 consultas.

## Instalación y Git

La instalación anterior tenía metadata 0.16.0 y un enlace editable al checkout,
pero el código de ese checkout ya declaraba 0.17.0. Se preservó su recibo antes
de reemplazarla, sin editar los archivos de trabajo del usuario.

Se consultó PyPI, se descargó el wheel oficial 0.17.0 y se verificó su SHA‑256:
`c6f55c259557b3bb396ad8a553bb3598cbc68e9cff2c79efdf2462fa354c5af5`.
Después de `uv tool install --force ken-rank==0.17.0`, se verificaron los 341
archivos del paquete instalado contra el wheel. El recibo ya no contiene una
dependencia editable y `ken` importa desde `site-packages`.

Tras `git fetch origin`, `main` local y `origin/main` coinciden en
`6286d91032a973ab5b3001df272e870ebd922281`: cero commits por delante o detrás.
No había commits pendientes que fusionar; no se ejecutó merge, reset ni stash.
Los cambios locales preexistentes se conservaron.

## Método y comprobaciones

- Misma matriz pública de 200 consultas que v102; SHA‑256
  `837a88a2c995a58257142ab763b8ac0035abc35b9d5f06759778f7ac3074305e`.
- Mismos snapshots: se copiaron y verificaron los 4760 archivos fuente fijados.
  Cada motor mantiene sus propias reglas de admisión e índices separados.
- La release usa su modelo estático incluido `ken/static-qwen3-r512-v2` y sus
  herramientas reales. `scope=symbols` para clase/símbolo y `scope=files` para
  módulo/archivo; esta política se fijó antes de ejecutar consultas.
- Preguntas originales literales, sin traducción añadida al publicado, sin
  filtrar candidatos, promover métodos a clases ni elegir un modo por su acierto.
  Cada posición nativa se conserva, incluso cuando devuelve otro tipo de pieza.
- La equivalencia de identidades usa el catálogo completo previo a consultas,
  sin aportar candidatos. Cero símbolos del tipo solicitado quedaron sin
  resolver. Un segundo cálculo directo por los campos nativos reprodujo 45/103.
- Se cerraron las 200 respuestas antes de puntuar con el Gold de desarrollo
  previamente abierto en v102. Cero errores y cero consultas faltantes.
  El scorer de identidad de v102 se conservó y reprodujo exactamente 168/197.
- La instalación nativa agrega `.ken/` a `.gitignore`: la primera captura v106
  se conserva como diagnóstico sin puntuar. En v106b se restauró el `.gitignore`
  fijado y se reaplicó el indexador nativo publicado sobre ese archivo antes de
  consultar. Se verificaron nuevamente los 4760 hashes al terminar.
- Nueve tests del adaptador verifican identidad, definiciones duplicadas,
  posiciones nativas y conservación del snapshot. No se alteró el motor publicado.

La evidencia suficiente del experimental sigue en **76/200 (38%)** según sus
juicios ciegos v102. No se asignó ese criterio a la release en este control;
no inferirlo de sus aciertos de identidad. El objetivo de 90% conjunto sigue
pendiente. Las nuevas consultas privadas de aceptación no se abrieron.

Artefactos relativos al workspace experimental:

- `output/development/uv-installed-baseline-v106b/registration.json`
- `output/development/uv-installed-baseline-v106b/installed-origin.json`
- `output/development/uv-installed-baseline-v106b/remote-audit.json`
- `output/development/uv-release-vs-experimental-v106b/report.json`
- `output/frozen/uv-release-identity-v106b/CONTROL-MANIFEST.json`
- `output/frozen/uv-release-report-v106b/CONTROL-MANIFEST.json`

Fuentes de distribución: [PyPI ken-rank 0.17.0](https://pypi.org/project/ken-rank/0.17.0/)
y el manifiesto JSON de PyPI conservado con la captura. Las cifras de calidad
provienen de las ejecuciones locales y no de esas páginas.
