# Abstract Factory

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/abstract-factory.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** contrato de factory, implementaciones de familia, dos o más roles de
producto, cliente. **Grafo:** una familia expone operaciones que devuelven productos
con contratos distintos; otra familia implementa esos mismos slots con productos
alternativos; el cliente consume contratos y recibe la factory. Relacionar cada
slot con su producto conserva la coherencia de familia. Dos métodos cualesquiera
que hacen `new` son solo un candidato débil.

| Lenguaje | Fragmento de la familia concreta |
|---|---|
| P | `def button(self): return DarkButton()` / `def menu(self): return DarkMenu()` |
| JS | `const dark = { button: () => new DarkButton(), menu: () => new DarkMenu() };` |
| TS | `class Dark implements UIFactory { button(): Button { return new DarkButton(); } menu(): Menu { return new DarkMenu(); } }` |
| J | `class Dark implements UIFactory { public Button button(){ return new DarkButton(); } public Menu menu(){ return new DarkMenu(); } }` |
| CS | `class Dark : IUIFactory { public IButton Button() => new DarkButton(); public IMenu Menu() => new DarkMenu(); }` |
| CPP | `struct Dark : UIFactory { std::unique_ptr<Button> button() override; std::unique_ptr<Menu> menu() override; };` |
| G | `func (Dark) Button() Button { return DarkButton{} }; func (Dark) Menu() Menu { return DarkMenu{} }` |
| R | `impl UIFactory for Dark { fn button(&self) -> Box<dyn Button> { Box::new(DarkButton) } fn menu(&self) -> Box<dyn Menu> { Box::new(DarkMenu) } }` |

**Portabilidad:** contratos estructurales en JS/TS y Go; Rust puede usar tipos
asociados y genéricos en lugar de trait objects. Hace falta sustitución de tipos.
**Negativo:** servicio que crea un logger y un DTO sin familias intercambiables.
**Límite:** compatibilidad visual/semántica de productos no se deduce del tipo.

