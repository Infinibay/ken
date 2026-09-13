# Decorator

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/decorator.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** contrato, wrapper, componente envuelto, comportamiento añadido.
**Grafo:** wrapper y componente cumplen contrato; wrapper delega la operación y
agrega un efecto o transforma entrada/salida. Composición de wrappers observada
refuerza la variante, sin exigirla siempre.

| Lenguaje | Fragmento de decoración |
|---|---|
| P | `def read(self): return self.inner.read().upper()` |
| JS | `const upper = read => (...args) => read(...args).toUpperCase();` — variante funcional |
| TS | `class Upper implements Reader { read(): string { return this.inner.read().toUpperCase(); } }` |
| J | `public String read(){ return inner.read().toUpperCase(); }` |
| CS | `public string Read() => inner.Read().ToUpperInvariant();` |
| CPP | `std::string read() override { return upper(inner_->read()); }` |
| G | `func (u Upper) Read() string { return strings.ToUpper(u.Inner.Read()) }` |
| R | `impl<R: Reader> Reader for Upper<R> { fn read(&self) -> String { self.0.read().to_uppercase() } }` |

**Portabilidad:** closures capturadas son wrappers válidos; un decorador sintáctico
Python no implica este patrón. **Negativo:** delegación pura sin efecto añadido,
que solo prueba wrapper. **Límite:** Proxy puede añadir logging; no usar la existencia
de un efecto como separación absoluta.

