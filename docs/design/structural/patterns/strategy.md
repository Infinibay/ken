# Strategy

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/strategy.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** consumidor, slot/argumento de algoritmo, implementaciones intercambiables,
entrada/salida. **Grafo:** consumidor invoca el algoritmo suministrado bajo contrato
común; varios valores pueden ocupar ese rol. No exigir objeto, clase ni dos
implementaciones locales si el punto de extensión es externo.

| Lenguaje | Fragmento de algoritmo inyectado |
|---|---|
| P | `def order(xs, key): return sorted(xs, key=key)` |
| JS | `const order = (xs, compare) => [...xs].sort(compare);` |
| TS | `const order = (xs: Item[], cmp: (a: Item,b: Item) => number) => [...xs].sort(cmp);` |
| J | `void order(List<Item> xs, Comparator<Item> cmp){ xs.sort(cmp); }` |
| CS | `void Order(List<Item> xs, Comparison<Item> cmp) => xs.Sort(cmp);` |
| CPP | `template<class Cmp> void order(std::vector<Item>& xs, Cmp cmp) { std::sort(xs.begin(), xs.end(), cmp); }` |
| G | `func Order(xs []Item, less func(i,j int) bool) { sort.Slice(xs, less) }` |
| R | `fn order<F: FnMut(&Item,&Item)->Ordering>(xs: &mut [Item], cmp: F) { xs.sort_by(cmp); }` |

**Portabilidad:** protocolos de comparador y callbacks requieren modelos de API;
los criterios de Python key y comparator no se equiparan en tipos, solo en rol.
**Negativo:** cualquier parámetro escalar usado en un cálculo. **Límite:** un callback
puede ser Observer o Command; importa el uso como variación de algoritmo.

## Correlación de la política suministrada — IR 1.39.0

Las dos variantes ejecutables reutilizan `strategy.supplied_policy`: unit,
configure, supplied y policy. La política tiene que recibir la última escritura
fuente directa de un parámetro de su configurador, o una entrada final de
constructor soportada. Una asignación histórica seguida de sobrescritura no basta.
La consulta pública no exige invocación ni intención de algoritmo por sí sola.

La variante por objeto invoca el mismo campo desde otro método y necesita un
slot del contrato nominal mediante DECLARED_TARGET o TARGET. Conserva el requisito
actual de dos subtipos observados; la propuesta de admitir extensiones externas
sin implementaciones locales sigue pendiente. La variante callable usa CALLEE_VALUE
del mismo campo. La configuración debe ser lineal bajo el pase disponible, aunque
la invocación pueda ocurrir dentro de ramas o bucles de otro método.

Python con descriptores expone una escritura fuente, sin garantizar qué valor
almacena o devuelve el descriptor. La estructura todavía se solapa con State,
Command, Bridge, Decorator e Interpreter. Ver [contrato y evaluación](../strategy-binding-inputs.md).
