# Regresión GoF tras incorporar lambdas tipadas y Optional

El corpus de 281 ejemplos aislados conserva las 53 presencias de etiquetas de v7.
Los hashes de entrada coinciden. Todas las consultas completaron el presupuesto,
sin excepciones. También se compararon las combinaciones completas de roles:
`match-changes.json` está vacío, no sólo los contadores de presencia.

El motor del escaneo usa IR 1.15.0: ownership de lambdas Java/C#/C++, valor del
cuerpo de expresión y modelo acotado de Optional. Los metadatos descriptivos de
cache-aside se actualizaron después del escaneo; las consultas ejecutables no
cambiaron. El manifest conserva los hashes exactos usados al ejecutar.

La ganancia moderna se valida por separado en
[iluwatar caching](../web-frameworks/iluwatar-caching.md): findAside pasa de cero
matches a un positivo revisado. Ese módulo no forma parte de los 281 ejemplos
GoF, por lo que no se añade a su contador. La suite incluye 33 tests nuevos de
lambdas y Optional, además de las regresiones anteriores de cache-aside.
