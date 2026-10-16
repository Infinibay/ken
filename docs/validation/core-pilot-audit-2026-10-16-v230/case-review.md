# Revisión manual del piloto CORE v227

**No encontré una función correcta penalizada sólo por formato o por otro UUID entre los13top1 negativos que sí devolvieron documento.** Los otros dos negativos no devolvieron nada: error de longitud de consulta. Hay documentación y tests relacionados que pueden servir de contexto, pero no son demostrablemente el mismo código o una función completa equivalente a las referencias. No se cambiaron qrels ni se calculó una puntuación relajada.

Leí los15errores Top1 del informe cerrado (18casos totales): **8documentación/changelog,3tests,2wrappers del verbo HTTP OPTIONS y2sinrespuesta**. No es una revisión de cada slot incorrecto de top10. La comparación exacta contra todos los positivos de cada consulta dio0documentos top1 con el mismo texto; la comparación semántica de las piezas completas tampoco demostró una implementación equivalente. Esto no certifica que los qrels agoten toda utilidad para un programador.

## Casos revisados

| Caso público / nivel | Top1 y comparación manual |
|---|---|
| `mwaskom__seaborn-3069` / `LEVEL-2` | La FAQ explica cómo categorías se ubican en índices enteros y cómo superponer gráficos. No contiene la rutina que debe dar ±0.5 de margen, suprimir grid o invertir y; no es la misma función bajo otro UUID. |
| `pallets__flask-5014` / `LEVEL-2` | El test rechaza "app.ui", un nombre no vacío con punto. La petición trata el nombre vacío y la referencia es el constructor que almacena/valida name. Coinciden Blueprint y ValueError, pero no la condición ni la responsabilidad. |
| `psf__requests-1724` / `LEVEL-2` | No existe top1: la API rechazó la consulta por longitud para reranking. No hay contenido predicho que pudiera ser la referencia con formato distinto. |
| `psf__requests-1766` / `LEVEL-2` | options() envía el verbo HTTP OPTIONS; la petición pide entrecomillar qop en un header Digest. La referencia obtiene qop y compone el header. El wrapper no contiene esa operación. |
| `psf__requests-1921` / `LEVEL-2` | La regresión recuperada pone None en headers de una llamada s.get, mientras la consulta contrapone ese caso conocido al None en session.headers. merge_setting es la implementación que actualmente elimina None sólo desde request_setting. |
| `psf__requests-2317` / `LEVEL-2` | La FAQ habla de descompresión/decodificación de respuestas y soporte de plataformas. El defecto solicitado ocurre al convertir el nombre del método de la petición con builtin_str; la referencia contiene esa instrucción literal. |
| `psf__requests-2931` / `LEVEL-2` | El test ejecuta put con Content-Type como str y data="\xff"; no es el cuerpo de _encode_params que llama to_native_string(data). Hay relación con datos no ASCII, pero no identidad ni una implementación completa equivalente. |
| `psf__requests-5414` / `LEVEL-2` | La guía de migración menciona InvalidURL para escapes porcentuales inválidos y contiene debugging/licencia. No es el prepare_url que parsea host y decide IDNA para el dominio que empieza por punto. |
| `psf__requests-6028` / `LEVEL-2` | El changelog cita arreglos antiguos de proxy/auth de 2013–2014. La consulta trata Python3.8.12/Requests2.27; la referencia es prepend_scheme_if_needed, que reconstruye el URL con auth/netloc. No hay ese código en el top1. |
| `mwaskom__seaborn-3069` / `LEVEL-3` | La misma FAQ conceptual que en Level2 no contiene los tres ajustes de ejes pedidos. Level3 incluye explícitamente _adjust_cat_axis, que apaga el grid y fija los límites en el orden invertido para y. No son código equivalente ni el mismo documento reidentificado. |
| `psf__requests-1142` / `LEVEL-3` | El documento mezcla streaming y respuesta HTTP; su Content-Length de ejemplo es de la respuesta y el fragmento visible muestra uploads POST/generadores. La consulta pide no añadir Content-Length a un GET saliente; la referencia prepare_content_length escribe inicialmente "0". |
| `psf__requests-1724` / `LEVEL-3` | No existe top1: también en Level3 la consulta Unicode1724 fue rechazada por longitud para reranking. No es un falso negativo de equivalencia textual o de matching. |
| `psf__requests-1766` / `LEVEL-3` | options(self,...) llama self.request("OPTIONS",...). No construye qop ni un header Digest; la referencia sí compone ese header. Es la versión de método del mismo equívoco léxico del caso Level2. |
| `psf__requests-1921` / `LEVEL-3` | El top1 reproduce el contrato conocido: poner None en parámetros de método elimina una clave de sesión. La consulta ya cita ese contrato y pregunta por el caso distinto de asignar None directamente en session.headers. Es documentación útil del vecino, no la misma implementación merge_setting. |
| `psf__requests-6028` / `LEVEL-3` | El changelog menciona auth/redirect/proxies de otras versiones; la evidencia visible termina centrada en SSL/Python2.6. Las referencias incluyen prepend_scheme_if_needed y funciones de proxy, que no están implementadas en ese texto. |

## Evidencia especialmente clara

- **Qop no es OPTIONS.** `psf__requests-1766`, L2: top1 `55196e94-…`, líneas1–9, acaba en `request('options', url, **kwargs)`. L3: `99160011-…`, líneas1–9, acaba en `self.request('OPTIONS', ...)`. Los positivos `01b5f37b-…` / `b861c405-…`, líneas79–82, construyen `qop=auth` y el header `Digest`. Son operaciones distintas, no dos formatos del mismo código.
- **Blueprint vacío no es nombre con punto.** `pallets__flask-5014`, L2: top1 `8af6ea82-…`, líneas1–3, prueba `Blueprint("app.ui", __name__)`. El positivo `6560b95e-…`, líneas22–25, está en el constructor y valida/guarda `name`. El test usa una cadena no vacía y otra regla; no sustituye al sitio de implementación que debe cambiarse.
- **None por llamada no es None en la sesión.** `psf__requests-1921`, L2: el test top1 `1cbd8a32-…`, líneas3–6, pasa `headers={'FOO': None}` a `s.get`. L3: la documentación top1 `6b2e0067-…`, líneas40–46, dice explícitamente *method-level parameter*. La query ya conoce ese contrato y pregunta por `session.headers['Accept-Encoding'] = None`. `merge_setting`, positivos `790c7bc1-…` / `6ed88a3c-…`, líneas21–29, fusiona ambos mapas pero elimina None recorriendo sólo `request_setting`. Test y documentación son contexto útil, sin ser esa función ni la condición defectuosa.
- **Unicode del método frente a decoding de respuesta.** `psf__requests-2317`, L2: la FAQ top1 `a525ddeb-…`, líneas8–15, describe descompresión y Unicode de respuestas. El positivo `bf35586c-…`, líneas51–66, convierte `method = builtin_str(method)` y construye la petición. La dirección y el objeto de datos son distintos.
- **El caso binario tiene un vecino útil, no identidad probada.** `psf__requests-2931`, L2: top1 `d5da719c-…`, líneas1–5, prueba un header Unicode con `data='\xff'`. El positivo `914ee7cc-…`, líneas23–34, contiene `_encode_params` y `to_native_string(data)`. El test puede contribuir a investigar encoding; faltan contexto de versiones/imports y el caso explícito de bytes UTF-8 para probar equivalencia. No es el mismo cuerpo de implementación.
- **Los límites de entrada no son matching.** `psf__requests-1724`, L2/L3: `results=[]` y `ValueError: query is too long for reranking; shorten the search question`. No hay pieza predicha cuya equivalencia pudiera rescatarse.

El JSON contiene IDs completos, quotes literales por caso, SHA del documento, archivo/registro físico de corpus y líneas lógicas del texto. Las citas no son supuestas líneas del archivo original del repositorio, que este corpus no proporciona.

## Qué estructura se perdió, y en qué etapa

El corpus original ya está compuesto por `_id` y `text`; algunas unidades están cortadas antes del wrapper. En Level3/proxy, por ejemplo, el positivo `97cdf1ac-…` contiene sólo la firma de `send` en2líneas, `5f3d81fc-…` contiene su docstring y otro chunk comienza por `try:`. No sería correcto atribuir esos cortes al acto de escribir `.txt`.

El wrapper mantiene el texto literal pero transforma cada chunk en un archivo independiente `documents/<UUID>.txt`. En los13top1 observados la metadata es uniformemente `entity.kind=file`, `qualname=null`, `owner=null`: se pierde la selección de parser por lenguaje, la identidad AST de función/clase, las rutas semánticas y las relaciones entre chunks o miembros de un mismo owner. Un snippet que empieza `def options(self,...)` no acredita por sí solo el nombre completo de su clase. Esta limitación puede afectar recuperación, pero aquí no se hizo una prueba causal del ranking.

Después hay otra etapa: la evidencia visible puede mostrar sólo una parte del documento. El changelog top1 de `psf__requests-6028` L3 muestra líneas144–155 sobre SSL/Python2.6, aunque el documento completo también contiene menciones más generales a auth/proxy. Se validaron los18fragmentos visibles contra los textos originales. Esto distingue selección de evidencia de selección de documento.

**El criterio CORE aplicado no compara snippets exactos ni su formato:** pregunta si el ID del documento recuperado pertenece a qrels. Una misma función íntegra bajo otro ID o un duplicado exacto sería un falso negativo demostrable que merecería documentarse; no se encontró uno en estos13top1. Que un test, FAQ o contrato ayude a un humano es otra cuestión: puede revelar límites de exhaustividad de relevancia, sin volverlo el mismo punto de implementación ni autorizar una reetiquetación retrospectiva.

## Alcance y cierre

Sólo se leyeron los archivos CORE públicos cerrados autorizados. No se abrió RepoQA ni ninguna reserva o Gold privado; no se ejecutó el engine, modelos o benchmarks y no se alteraron criterios, consultas, órdenes, resultados o etiquetas. Las referencias focales se revisaron para establecer diferencias de responsabilidad; no se afirma una auditoría semántica completa de todos los positivos de los casos Level3 con33/37documentos.

Input principal SHA256 (`core-report-v224.json`): `b46ae4aa7ded74ace5c35e51e98df6f42c0d444bdff8cfa27c4ac24bdbc145c0`. El recibo JSON lista los hashes de cada input efectivamente leído y conserva cada error dentro del alcance original.

JSON SHA256: `dd64d7ab59e337bd3ebc4390bd834949b9dbf42cb801d8848854bf491765ff49`.
