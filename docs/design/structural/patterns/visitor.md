# Visitor

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/visitor.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** elementos de varios tipos, accept, visitor, operaciones específicas por
elemento y cliente. **Grafo:** accept invoca operación del visitor pasando el elemento;
selección de operación depende del tipo de elemento; diferentes visitors implementan
operaciones sobre la misma familia. Una llamada `v.visit(self)` aislada es débil.

| Lenguaje | Fragmento de accept |
|---|---|
| P | `class Number:` con `def accept(self, v): return v.visit_number(self)` |
| JS | `class NumberNode { accept(v) { return v.visitNumber(this); } }` |
| TS | `class NumberNode implements Expr { accept(v: Visitor) { return v.visitNumber(this); } }` |
| J | `Result accept(Visitor v){ return v.visit(this); }` con overload para `NumberNode` |
| CS | `Result Accept(IVisitor v) => v.Visit(this);` con overload tipado |
| CPP | `void accept(Visitor& v) override { v.visit(*this); }` con overload tipado |
| G | `func (n Number) Accept(v Visitor) Result { return v.VisitNumber(n) }` |
| R | `fn accept<V: Visitor>(&self, v: &mut V) -> V::Output { v.visit_number(self) }` |

**Portabilidad:** resolver overloads Java/C#/C++; Go/Python usan métodos distintos.
Rust `match` exhaustivo sobre enum es una alternativa de diseño, pero no se etiqueta
Visitor clásico si no existe visitor separado. **Negativo:** callback al que se pasa
`self` para logging. **Límite:** cobertura de todas las variantes de elemento necesita
mundo cerrado y tipos completos.
