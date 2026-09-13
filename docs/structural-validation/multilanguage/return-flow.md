# Retornos secuenciales: valores sobrescritos y aliases

IR 1.19.0 introduce un análisis limitado de orígenes de bindings locales para
Python, JavaScript, TypeScript, Java y C#. El [probe antes](ir-assignment-precision.json)
emitía `RETURNS_NEW Product` después de reemplazar el producto por null; el
[probe después](ir-assignment-precision-after.json) ya no lo emite en los tres
lenguajes de esa reproducción. No se ejecutan los programas analizados.

Los 54 tests en `tests/structural/test_return_flow.py` incluyen creación conservada,
reasignación que mata la creación, asignación posterior al retorno, retorno muerto
y aliases con snapshot del origen. `y=x; x=null; return y` conserva el producto;
`x=null; y=x; x=Product(); return y` no lo retorna. `RETURN_REACHES` conserva la
escritura inmediata del binding devuelto y `RETURN_ORIGIN` su origen resuelto.

Las exclusiones tienen tests: control condicional, bucles, finally, closures que
pueden escribir con nonlocal, exec, yield, +=, destructuring, walrus, import que
redefine el binding, shadowing en bloques y lecturas antes de inicializar. El pase
emite `RETURN_FLOW_STATUS unsupported` en vez de atribuirles flujo secuencial.
El estado solo cubre ese pase; no certifica otras relaciones del IR. Se asume
semántica ordinaria de bindings léxicos, sin mutación de frames ni sustitución de
código en ejecución; no es un análisis de reflexión o código generado.

La [regresión del corpus](return-flow-corpus-regression.json) fija los hashes del
motor y de las entradas. Compara contra v10: mismos 281 ejemplos, 53 presencias del
patrón etiquetado por upstream, mismas combinaciones de roles y ninguna consulta
incompleta. La corrección mejora la precisión de los casos reproducidos; no agrega
detecciones esperadas a ese corpus ni constituye una medición global de precisión.

Pendiente: CFG y joins de ramas, lecturas de miembros con bases distintas, alias
por referencia en C++/Go/Rust, retornos implícitos, efectos entre procedimientos y
reemplazo del resumen histórico en ámbitos no soportados. En esos ámbitos,
`RETURNS_NEW` todavía puede sobreaproximar las asignaciones que llegan al retorno;
consultar `RETURN_ORIGIN` y el estado del pase cuando se necesite esta precisión.
