"""Record an IR precision gap without executing the sample programs.

Run with the project Python; JSON goes to stdout. This is an audit probe, not a
test asserting that the current incorrect facts must remain present.
"""
import hashlib
import json
from pathlib import Path

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project

SOURCES = {
    'python': 'class Product: pass\ndef build():\n x = Product()\n x = None\n return x\n',
    'java': 'class Product {} class Demo { Product build(){ Product x = new Product(); x = null; return x; } }',
    'typescript': 'class Product {} function build(){ let x: Product | null = new Product(); x = null; return x; }',
}


def main():
    cases = []
    for language, source in SOURCES.items():
        graph = link_project([lower_source(source, language, 'sample')])
        cases.append({
            'language': language, 'source': source,
            'expected_certain_returns_new': [],
            'diagnostics': graph.diagnostics,
            'observed_returns_new': [
                {'callable': graph.entities[f.subject].name,
                 'type': graph.entities[f.object].name, 'attrs': f.attrs}
                for f in graph.facts if f.relation == 'RETURNS_NEW'
            ],
        })
    engine = Path(lower_source.__code__.co_filename).parent
    print(json.dumps({'cases': cases, 'engine_sha256': {
        str(p.relative_to(engine)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(engine.glob('*.py'))
    }}, indent=2))


if __name__ == '__main__':
    main()
