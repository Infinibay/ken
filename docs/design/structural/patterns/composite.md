# Composite

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/composite.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** componente, hoja, compuesto, colección recursiva, operación uniforme.
**Grafo:** hoja y compuesto cumplen el mismo contrato; el compuesto contiene
componentes e invoca la misma operación de contrato en ellos, combinando resultados.
La recursión debe pasar por el tipo/contrato, no solo por cualquier colección.

| Lenguaje | Fragmento del compuesto |
|---|---|
| P | `def size(self): return sum(child.size() for child in self.children)` |
| JS | `size() { return this.children.reduce((s, c) => s + c.size(), 0); }` |
| TS | `class Group implements Node { children: Node[] = []; size() { return this.children.reduce((s,c) => s+c.size(),0); } }` |
| J | `public int size(){ return children.stream().mapToInt(Node::size).sum(); }` |
| CS | `public int Size() => children.Sum(c => c.Size());` |
| CPP | `int size() const override { int n=0; for (auto& c : children) n+=c->size(); return n; }` |
| G | `func (g Group) Size() int { n:=0; for _,c:=range g.Children { n+=c.Size() }; return n }` |
| R | `fn size(&self) -> usize { self.children.iter().map(\|c\| c.size()).sum() }` |

**Portabilidad:** reconocer callbacks de reduce/map y modelos de colecciones;
Rust también puede usar enum recursivo sin trait. **Negativo:** lista de listeners
que reciben eventos, sin componente uniforme recursivo. **Límite:** no inferir que
el grafo de objetos sea acíclico.

