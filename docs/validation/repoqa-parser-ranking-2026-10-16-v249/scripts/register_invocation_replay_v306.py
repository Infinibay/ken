"""Register two policy orders on fixed public240 pools and closed neural logits."""
from pathlib import Path
import hashlib,subprocess,sys
base=Path.cwd();folder=Path(__file__).parent;producer=folder/'replay_invocation_policy_v306.py';old=(folder/'replay_view_scale_v288.py').read_text();text=old.replace("'output/analysis/view-scale-v288-old240'","'output/analysis/invocation-policy-v306-old240'").replace("['baseline_mean','code_only','rank_fusion','standardized_mean']","['before','invocation']").replace("prediction['orders']['baseline_mean']","prediction['orders']['before']")
a=text.index('def composition_orders(');b=text.index('\ndef sha(',a);text=text[:a]+'''def composition_orders(card, code, native):
    means=[(a+b)/2 for a,b in zip(card,code,strict=True)]
    order=sorted(range(len(card)),key=lambda i:(-means[i],native[i]))
    return {'before':order,'invocation':order}

'''+text[b:]
anchor="w = Path.cwd()\n";addition='''w = Path.cwd()
import importlib.util
legacy_engine=w/'output/frozen/repoqa-final-cpp-v296'
def load_legacy(name):
    path=legacy_engine/'src/ken/retrieval'/name
    spec=importlib.util.spec_from_file_location('legacy_v306_'+name.removesuffix('.py'),path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module
legacy_requirements=load_legacy('symbol_requirements.py');legacy_operations=load_legacy('source_operations.py')
old_requested_operations=legacy_requirements.requested_operations
''';assert text.count(anchor)==1;text=text.replace(anchor,addition)
text=text.replace("'hypothesis': 'Actual source-card and complete-code views use the same model but their raw-logit scales need not be interchangeable. Compare unchanged equal mean with code-only, fixed k60 rank fusion and within-query standardized mean. All prior source constraints/paths/exact bypass and budgets unchanged. No learned parameters or per-language/repository routing. Pure already-closed-logit diagnostic; no model inference or blind acceptance.'", "'hypothesis': 'An explicitly requested active invocation needs an owned call; storing a callback, declaration-time defaults and deferred nested/lambda bodies do not establish it. Compare existing mean/source preferences with one new syntactic operation family on the exact same128symbol neural pools; preserve non-symbols and22unique exact bypasses. No names/IDs/repositories in policy or fitted weights.'")
text=text.replace("    'status': 'Registered BEFORE orders and Gold',","    'legacy_policy_sources': {name:sha(legacy_engine/'src/ken/retrieval'/name) for name in ('symbol_requirements.py','source_operations.py')},\n    'status': 'Registered BEFORE orders and Gold',")
text=text.replace('            relations = OperationWitnesses(catalog)','            relations = OperationWitnesses(catalog)\n            legacy_relations = legacy_operations.OperationWitnesses(catalog)')
anchor="            lookup = {json.dumps(unit, sort_keys=True): value for unit, value in zip(units, observed, strict=True)}";extra="            assert all((facts - {'invocation'}) == legacy_relations.for_owner(EntityKey(path=unit['path'], **unit['entity'])) for unit,facts in zip(units,observed,strict=True)), ('legacy operation witness changed',query_id)\n"+anchor;assert anchor in text;text=text.replace(anchor,extra)
a="                base=[units[i] for i in indices];allowed=requested";b="                base=[units[i] for i in indices];allowed=old_requested_operations(case['query']) if name=='before' else requested";assert a in text;text=text.replace(a,b)
assert not producer.exists();producer.write_text(text);print(hashlib.sha256(producer.read_bytes()).hexdigest(),flush=True);raise SystemExit(subprocess.run([sys.executable,str(producer)]).returncode)
