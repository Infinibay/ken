# Flyweight

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/flyweight.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** pool, clave, estado intrínseco compartido, contexto extrínseco y consumidor.
**Grafo:** lookup y construcción correlacionados con la misma clave; objeto
almacenado se reutiliza; operación recibe estado contextual desde fuera. Compartir
un objeto cacheado es evidencia necesaria de una variante, no suficiente.

| Lenguaje | Fragmento de internación y uso |
|---|---|
| P | `if key not in pool: pool[key] = Glyph(key)` / `pool[key].draw(x, y)` |
| JS | `if (!pool.has(key)) pool.set(key, new Glyph(key)); pool.get(key).draw(x, y);` |
| TS | `const glyph: Glyph = pool.get(key) ?? createAndStore(key); glyph.draw(x, y);` |
| J | `pool.computeIfAbsent(key, Glyph::new).draw(x, y);` |
| CS | `pool.GetOrAdd(key, k => new Glyph(k)).Draw(x, y);` |
| CPP | `auto [it, added] = pool.try_emplace(key, key); it->second.draw(x, y);` |
| G | `g,ok:=pool[key]; if !ok { g=&Glyph{Key:key}; pool[key]=g }; g.Draw(x,y)` |
| R | `pool.entry(key).or_insert_with(\|\| Glyph::new(key)).draw(x, y);` |

**Portabilidad:** modelos de mapas/entry APIs y callbacks. **Negativo:** memoización
de números o caché de respuestas sin objetos con estado extrínseco. **Límite:**
no afirmar inmutabilidad, ahorro de memoria o creación única concurrente; algunas
APIs pueden ejecutar la factory más de una vez bajo contención.

