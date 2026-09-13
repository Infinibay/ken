# Iterator

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/iterator.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** secuencia, estado de recorrido, next/resume y condición de fin.
**Grafo:** produce elementos incrementales y conserva progreso; consumidor usa
protocolo de iteración. Generadores son variante explícita, no requieren clase.

| Lenguaje | Fragmento de protocolo o generación |
|---|---|
| P | `def items(xs):` con `for x in xs: yield x` |
| JS | `function* items(xs) { yield* xs; }` |
| TS | `function* items(xs: string[]): Generator<string> { yield* xs; }` |
| J | `class Cursor implements Iterator<Item> { public boolean hasNext(){...} public Item next(){...} }` |
| CS | `IEnumerable<Item> Items() { foreach (var x in xs) yield return x; }` |
| CPP | `Item& operator*(); Cursor& operator++(); bool operator!=(const Cursor&) const;` |
| G | `func Items(yield func(Item) bool) { for _,x:=range xs { if !yield(x) { return } } }` — variante de función iteradora |
| R | `impl Iterator for Cursor { type Item = Item; fn next(&mut self) -> Option<Item> { ... } }` |

**Portabilidad:** los protocolos tienen nombres legítimamente significativos si
se resolvieron sus contratos. Un canal Go no es automáticamente Iterator. **Negativo:**
clase que tiene métodos `next` y `hasNext` sin progreso o uso de protocolo.
**Límite:** no demostrar agotamiento, finitud o ausencia de repetición. La fila Go
requiere configurar una versión con soporte de range sobre funciones.

