# Interpreter

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/interpreter.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** expresión, terminales/no terminales, contexto y resultado. **Grafo:**
árbol de expresiones; evaluación recursiva pasa contexto a hijos y combina
resultados según operación. Enum + match es variante tan relevante como clases.

| Lenguaje | Fragmento de evaluación binaria |
|---|---|
| P | `def eval(self, env): return self.left.eval(env) + self.right.eval(env)` |
| JS | `eval(env) { return this.left.eval(env) + this.right.eval(env); }` |
| TS | `eval(env: Env): number { return this.left.eval(env) + this.right.eval(env); }` |
| J | `int eval(Env e){ return left.eval(e) + right.eval(e); }` |
| CS | `int Eval(Env e) => left.Eval(e) + right.Eval(e);` |
| CPP | `int eval(Env const& e) const override { return left->eval(e)+right->eval(e); }` |
| G | `func (a Add) Eval(e Env) int { return a.Left.Eval(e)+a.Right.Eval(e) }` |
| R | `match self { Expr::Add(a,b) => a.eval(env)+b.eval(env), Expr::Num(n) => *n }` |

**Portabilidad:** patrón algebraico no tiene `SUBTYPE_OF`; necesita variantes de
sum types y destructuring. **Negativo:** Composite que suma tamaños de archivos,
sin representación de un lenguaje/contexto. **Límite:** intención de interpretar
una gramática rara vez es demostrable solo por forma; reportar evaluación recursiva.

