# Revisión de referencias inglesas v212

Encontré una implementación directa completa para cada pedido. La operación de mapping también tiene una especialización completa por delegación (`setenv`). Las delegaciones y vecinos parciales se separan de las implementaciones independientes; no se modificó ninguna referencia.

## 1. pytest: lookup y causa del AttributeError

`src/_pytest/monkeypatch.py::annotated_getattr` (93–100) realiza `getattr(obj, name)` (95); captura `AttributeError as e` (96); añade `type(obj).__name__`, `ann` y `name` al error (97–98), y usa `from e` (99). Cumple la conjunción completa.

La localización no se calcula dentro del helper: se recibe en `ann`. `derive_importpath` (103–110) obtiene `module` de la ruta por puntos y llama al helper sólo si `raising`; `resolve` (65–90) construye `used` por componentes y llama al helper en su fallback. Son delegaciones condicionales del mismo diagnóstico. `derive_importpath` retorna `(attr,target)` y `resolve` tiene otras rutas de error/importación; no son segundas implementaciones directas del lookup enriquecido.

En particular, la causa es la excepción del `getattr` dentro de `annotated_getattr`, no cualquier `AttributeError` anterior que `resolve` haya descartado. `MonkeyPatch.setattr` y `delattr` sólo llegan al helper en la forma string; sus errores locales no preservan esa misma conjunción. `compat.safe_getattr` (237–251) devuelve default en vez de enriquecer errores.

La enumeración AST de los81 archivos Python `src` (0 errores de parseo) encontró un solo `raise AttributeError(...) from ...`: el de `annotated_getattr`. Este dato apoya la búsqueda; no prueba ausencia de todo alias dinámico.

## 2. pytest: estado previo y pila de items

`src/_pytest/monkeypatch.py::MonkeyPatch.setitem` (312–317) captura `oldval = dic.get(name, NOTSET)` (314), asigna `dic[name] = value` (316) y luego añade `(dic, name, oldval)` a `self._setitem` (317). El estado se captura **antes**, mientras el append ocurre después de una asignación exitosa.

`MonkeyPatch.setenv` (334–352) es una coincidencia completa **por delegación especializada**: termina en `self.setitem(os.environ, name, value)` (352). La consulta dice mapping, sin excluir el mapping de entorno. No constituye otro algoritmo independiente.

`MonkeyPatch.delitem` (319–332) también guarda estado en `_setitem`, pero borra en vez de asignar un valor temporal. `setattr` usa `_setattr`, y `delenv` delega al borrado. `undo` es consumidor, no el productor de la secuencia solicitada.

`NOTSET` es un token singleton (`src/_pytest/compat.py:41–47`). `undo` lo interpreta como ausencia y elimina la clave; para otro valor restaura el previo (`monkeypatch.py:439–449`). La ausencia no se guarda como booleano: si un mapping ya contuviera exactamente el token `NOTSET` como valor legítimo, ese caso no se distinguiría de ausencia. Es un caveat del centinela, no una nueva etiqueta ni un cambio de consulta.

## 3. junit5: dos caminos del blocker

`junit-platform-engine/src/main/java/org/junit/platform/engine/support/hierarchical/SingleLock.java::SingleLock.SingleLockManagedBlocker.isReleasable` (86–88) contiene:

```java
return this.acquired || (this.acquired = SingleLock.this.lock.tryLock());
```

La clase interior implementa `ForkJoinPool.ManagedBlocker` (72) y declara `volatile boolean acquired` (74). Si la bandera ya es verdadera, el OR cortocircuita; si es falsa, se guarda y devuelve el resultado de `tryLock`. Es la única implementación localizada de los dos caminos completos.

`CompositeLock.CompositeLockManagedBlocker.isReleasable` (125–127) sólo hace `return this.acquired`; no intenta un lock ni actualiza la bandera con `tryLock`. `SingleLock.tryAcquire` (45–47) llama `tryLock` sin conservar el estado del blocker. `SingleLockManagedBlocker.block` (77–83) usa `lockInterruptibly`: es otra ruta, que puede bloquear. `SingleLock.acquire` (50–53) entrega el blocker al scheduler; no es otra consulta no bloqueante completa.

Caveat lingüístico: la lectura conjunta de «returning … or updating …» describe los dos caminos de la expresión. Si se interpreta «or» como que basta cualquiera de las propiedades aisladas, el método de `CompositeLock` satisface devolver una bandera previa. Por eso sólo afirmo unicidad para **el comportamiento completo de bandera previa más fallback tryLock**; conservo explícita la lectura más débil sin modificar el texto.

## Procedencia y límites

Sólo se leyeron fuentes físicas de pytest/junit5; no se usó Ken ni se abrieron Gold/datasets, reservas, outputs de ranking/métricas o helpers del motor. Se conserva contexto de revisiones públicas anteriores y no se afirma ceguera absoluta. El incidente v203 de snippets históricos correspondía a attrs, no a estos pedidos, y no fue reutilizado.

Las citas del JSON y sus SHA256 se comprobaron contra los bytes físicos. No se ejecutaron pruebas, modelos, benchmarks o compilaciones. La revisión es estática y no certifica tiempos, scheduling ni toda implementación posible de `Lock`. No contiene recomendaciones de scoring o implementación.

JSON SHA256: `5501be6ada654bef9ecf4734731a520aa3fb8ae06567daee51d444728c1c3e1e`.
