# Builder

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/builder.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** builder, estado de construcción, pasos, producto final, director opcional.
**Grafo:** pasos contribuyen al estado o producen un builder sucesor; finalización
consume ese estado y devuelve un producto. El director llama pasos correlacionados
sobre la misma construcción. No exigir dos setters, chaining, ni que el producto
sea distinto del builder en todas las variantes; distinguir variantes explícitas.

| Lenguaje | Fragmento de paso y finalización |
|---|---|
| P | `def size(self, n): self.n = n; return self` / `def build(self): return Box(self.n)` |
| JS | `size(n) { this.n = n; return this; } build() { return new Box(this.n); }` |
| TS | `size(n: number): this { this.n = n; return this; } build(): Box { return new Box(this.n); }` |
| J | `Builder size(int n){ this.n=n; return this; } Box build(){ return new Box(n); }` |
| CS | `Builder Size(int n) { this.n=n; return this; } Box Build() => new Box(n);` |
| CPP | `Builder& size(int n) { n_=n; return *this; } Box build() const { return Box{n_}; }` |
| G | `func (b *Builder) Size(n int) *Builder { b.n=n; return b }; func (b *Builder) Build() Box { return Box{b.n} }` |
| R | `fn size(mut self, n: usize) -> Self { self.n=n; self } fn build(self) -> BoxSpec { BoxSpec { n: self.n } }` |

**Portabilidad:** Rust consuming builder devuelve un valor movido, no una referencia
`self` mutable convencional. Un builder inmutable crea otro builder; typestate puede
cambiar `Builder<Missing>` a `Builder<Ready>`. Hace falta flujo y sustitución genérica.
**Negativo:** `User.set_name().set_age()` sin construcción/finalización observable.
**Límite:** no afirmar validación de todas las combinaciones ni orden obligatorio
salvo evidencia de control o tipos. Ejemplo ampliado en [casos](../use-cases.md).

