# Prototype

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/prototype.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

Implementación IR 1.26.0: `derived-clone`, `explicit-copy` y `field-copy` tienen
queries en el [TOML ejecutable](../../../../src/ken/structural/patterns/prototype.toml).
La nueva [copia por campos](../field-copy.md) conserva objeto y última escritura
hasta el retorno, con alternativas por rama y exclusiones de escapes.
Ver [auditoría Python/TypeScript](../../../structural-validation/multilanguage/prototype-field-copy.md).

**Roles:** prototipo, operación de copia, estado copiado, nuevo objeto y consumidor.
**Grafo:** resultado distinto recibe valores derivados del estado de la instancia
fuente; consumidor solicita copia mediante un contrato común. Distinguir copia
superficial, profunda y copy-on-write cuando hay evidencia.

| Lenguaje | Fragmento de copia |
|---|---|
| P | `def clone(self): return Node(self.name, self.children.copy())` |
| JS | `clone() { return new Node(this.name, [...this.children]); }` |
| TS | `clone(): Node { return new Node(this.name, [...this.children]); }` |
| J | `Node copy(){ return new Node(name, new ArrayList<>(children)); }` |
| CS | `Node Copy() => new Node(name, new List<Node>(children));` |
| CPP | `std::unique_ptr<Node> clone() const { return std::make_unique<Node>(*this); }` |
| G | `func (n *Node) Clone() *Node { c := *n; c.Children = append([]*Node(nil), n.Children...); return &c }` |
| R | `impl Clone for Node { fn clone(&self) -> Self { Self { name: self.name.clone(), children: self.children.clone() } } }` |

**Portabilidad:** copy constructors y `#[derive(Clone)]` requieren modelo de
lenguaje; una macro no expandida debe quedar como capacidad pendiente.
**Negativo:** método que retorna `self` o un objeto nuevo con constantes sin leer
el prototipo. **Límite:** copiar una colección no implica copiar recursivamente sus
elementos; los ejemplos pueden compartir hijos.
