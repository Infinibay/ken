# chi: handlers adaptados

Repositorio: https://github.com/go-chi/chi, commit
`b1c9ab47626cc46b34393ad4d35779c4363c4e1e`.
Escaneo estático de 30 archivos de `middleware/`, sin ejecutar código del proyecto.
El [JSON](chi-modern.json) conserva hashes de fuentes y motor, evidencia y presupuestos.
No hubo diagnósticos de parsing ni consultas incompletas.

La nueva consulta `architecture.adapted-continuation-wrapper` devuelve 37
combinaciones de roles en 31 fábricas distintas. Algunas tienen varias llamadas
a la continuación: no son 37 middleware independientes. Tiempo de consulta en esta
ejecución: 4,035 ms, 2627 estados y 1165 filas examinadas; no es un benchmark general.

Casos revisados manualmente:

| Caso | Evidencia | Evaluación |
|---|---|---|
| CleanPath, clean_path.go:12 | Retorna HandlerFunc con closure que modifica RoutePath y llama next.ServeHTTP | Positivo confirmado |
| GetHead, get_head.go:10 | Retorna HandlerFunc; dos sitios de llamada a next en caminos distintos | Positivo, dos evidencias; no prueba dos invocaciones por petición |
| Timeout, timeout.go:33 | Closure asignada a fn, pasada a HandlerFunc; delega tras crear contexto con timeout | Positivo confirmado tras ampliar la consulta |

Problema encontrado y corregido: la variante inicial sólo seguía argumentos
callable directos. Omitía Timeout y otras fábricas que usan una variable local.
KenQL representa esos argumentos como VALUE → valor leído → LOADED_FROM → storage;
ASSIGNED_FROM conecta el storage con el callable. Seguir directamente VALUE al
storage tampoco sirve. Con ese recorrido adicional, los resultados aumentaron
de 21 combinaciones / 17 fábricas a 37 / 31. Cuatro regresiones propias cubren
esta forma en Go, Python, JavaScript y TypeScript.

Límites abiertos: ASSIGNED_FROM es evidencia de asignación, no reaching-definitions;
puede haber una reasignación posterior. El adaptador no tiene identidad de API
resuelta: un callback descartado por una función arbitraria comparte esta forma.
No se verifica registro en el router, orden, cancelación efectiva ni forwarding.
Las otras coincidencias requieren revisión individual antes de publicar precisión.
El middleware implementado mediante objetos, delegación entre fábricas o helpers
entre archivos puede seguir omitido.

Reproducción:

```sh
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/chi \
  --prefix middleware/ --collection modern --output /tmp/chi-modern.json
```
