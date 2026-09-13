# Adapter

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/adapter.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** contrato objetivo, adaptador, adaptee y traducción de operación/datos.
**Grafo:** cliente usa contrato objetivo; adaptador lo cumple; su operación transforma
argumentos/resultados y llama al adaptee de contrato diferente. Adaptación de clase
por herencia múltiple y de objeto por composición son variantes.

| Lenguaje | Fragmento de adaptación |
|---|---|
| P | `def read(self, n): return self.legacy.fetch_bytes(n).decode()` |
| JS | `read(n) { return decode(this.legacy.fetchBytes(n)); }` |
| TS | `class Adapter implements Reader { read(n: number): string { return decode(this.legacy.fetchBytes(n)); } }` |
| J | `public String read(int n){ return decode(legacy.fetchBytes(n)); }` |
| CS | `public string Read(int n) => Decode(legacy.FetchBytes(n));` |
| CPP | `std::string read(int n) override { return decode(legacy_.fetch_bytes(n)); }` |
| G | `func (a Adapter) Read(n int) string { return decode(a.legacy.FetchBytes(n)) }` |
| R | `impl Reader for Adapter { fn read(&self, n: usize) -> String { decode(self.legacy.fetch_bytes(n)) } }` |

**Portabilidad:** una función que envuelve otra también puede adaptar. Requiere
contrato inferido/observado si no hay anotaciones. **Negativo:** delegado del mismo
contrato sin adaptación observada. **Límite:** dos nombres de tipo distintos pueden
ser aliases del mismo contrato; resolver antes de usar desigualdad.

