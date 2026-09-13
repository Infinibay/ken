# Factory Method

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/factory-method.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** creator base, operación de creación reemplazable, creator concreto,
contrato de producto y cliente del producto. **Grafo clásico:** un algoritmo llama
un slot de creación; una implementación reemplaza ese slot y retorna producto
concreto compatible. La llamada al slot debe ser la que participa del algoritmo.

| Lenguaje | Fragmento del punto de creación |
|---|---|
| P | `class CsvJob(Job):` con `def create(self): return CsvReader()` |
| JS | `class CsvJob extends Job { create() { return new CsvReader(); } }` |
| TS | `class CsvJob extends Job { create(): Reader { return new CsvReader(); } }` |
| J | `class CsvJob extends Job { @Override Reader create(){ return new CsvReader(); } }` |
| CS | `class CsvJob : Job { protected override IReader Create() => new CsvReader(); }` |
| CPP | `struct CsvJob : Job { std::unique_ptr<Reader> create() override { return std::make_unique<CsvReader>(); } };` |
| G | `func Run(c Creator) { r := c.Create(); r.Read() }` — variante por contrato, sin override de clase |
| R | `trait Job { fn create(&self) -> Box<dyn Reader>; fn run(&self) { self.create().read(); } }` — variante con default de trait |

**Portabilidad:** no inventar `OVERRIDES` en Go; usar conformidad y slot invocado.
**Negativo:** `new_reader()` libre que siempre construye el mismo tipo. Se puede
ofrecer como regla `construction.simple-factory`, sin llamarlo Factory Method
clásico. **Límite:** instanciación indirecta por DI necesita modelos aparte.

