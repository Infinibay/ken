# Facade

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/facade.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** superficie pública, subsistemas y clientes. **Grafo:** el cliente entra
por una operación que coordina varias responsabilidades y reduce la exposición de
sus APIs. Imports/exports y uso externo ayudan a establecer la frontera.

| Lenguaje | Fragmento de orquestación |
|---|---|
| P | `def checkout(self, cart): self.stock.reserve(cart); return self.pay.charge(cart)` |
| JS | `export async function checkout(cart) { await stock.reserve(cart); return pay.charge(cart); }` |
| TS | `async checkout(cart: Cart): Promise<Receipt> { await this.stock.reserve(cart); return this.pay.charge(cart); }` |
| J | `Receipt checkout(Cart c){ stock.reserve(c); return pay.charge(c); }` |
| CS | `Receipt Checkout(Cart c) { stock.Reserve(c); return pay.Charge(c); }` |
| CPP | `Receipt checkout(const Cart& c) { stock.reserve(c); return pay.charge(c); }` |
| G | `func (f Facade) Checkout(c Cart) Receipt { f.Stock.Reserve(c); return f.Pay.Charge(c) }` |
| R | `fn checkout(&self, c: &Cart) -> Receipt { self.stock.reserve(c); self.pay.charge(c) }` |

**Portabilidad:** una función exportada basta como superficie. **Negativo:** función
de negocio interna con dos colaboradores, sin frontera identificable. **Límite:**
los nombres «subsystem»/«facade» no prueban arquitectura; mantener candidato si no
hay evidencia de consumidores. La atomicidad del checkout es otro análisis.

