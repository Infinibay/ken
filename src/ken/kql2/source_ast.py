"""KQL views over the canonical AST, independent of legacy entity identities."""
from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Iterator
from ken.structural_store import Store
from ken.structural_store.common_ast import View
from ken.common_ast.environment import Environment
from .values import ASTValue, QueryValue, Unknown

SELECTORS={'node','expression','statement'}
RELATIONS={'contains','contains_direct','same_symbol','visible_at','initialized_at'}


class SourceAST:
    def __init__(self, store: Store, snapshot: int, check: Callable[[],None]):
        self.store,self.snapshot,self.check=store,snapshot,check
        self.views: OrderedDict[int,View]=OrderedDict()
        self.bindings: dict[int,tuple[Environment,dict[int,int]]]={}
        self.units=dict((unit,(path,language)) for unit,path,language in store.db.execute(
            'SELECT u.unit_id,u.path,u.language FROM k2_units u JOIN k2_snapshot_units m ON m.unit_id=u.unit_id WHERE m.snapshot_id=?',(snapshot,)))

    def view(self, unit: int) -> View:
        if unit not in self.views:
            self.views[unit]=View(self.store,unit)
            while len(self.views)>2:
                old,_=self.views.popitem(last=False)
                self.bindings.pop(old,None)
        self.views.move_to_end(unit)
        return self.views[unit]

    def classified(self) -> bool:
        """An opaque node prevents certifying absence over classified domains."""
        for unit in self.units:
            self.check()
            view=self.view(unit)
            if view.fallback is not None:
                if not view.fallback.nodes or any(n.category=='opaque' for n in view.fallback.nodes): return False
            else:
                row=self.store.db.execute('''SELECT 1 FROM k2_ast_nodes n JOIN k2_ast_strings s
                    ON s.unit_id=n.unit_id AND s.string_id=n.category
                    WHERE n.unit_id=? AND s.value='opaque' LIMIT 1''',(unit,)).fetchone()
                if row is not None: return False
                if not self.store.db.execute('SELECT 1 FROM k2_ast_nodes WHERE unit_id=? LIMIT 1',(unit,)).fetchone(): return False
        return True

    def scan(self, selector: str, *, kind: str | None=None, name: str | None=None, parent: ASTValue | None=None) -> Iterator[QueryValue]:
        for unit in ((parent.unit,) if parent else self.units):
            self.check()
            view=self.view(unit)
            scopes=view.rows('scopes')
            for node in view.nodes(kind=kind,name=name,parent=parent.node.id if parent else None):
                self.store.scanned+=1
                self.check()
                if selector!='node' and node.category!=selector: continue
                path,language=self.units[unit]
                scope=scopes[node.scope]
                yield ASTValue(self.snapshot,unit,node,path,language,scope.namespace,scope.kind)

    def relation(self, name: str, arguments: tuple[QueryValue,...]) -> QueryValue:
        a,b=arguments
        if not isinstance(a,ASTValue) or not isinstance(b,ASTValue): return Unknown('ast_node_unknown')
        self.check()
        if a.snapshot!=b.snapshot or a.unit!=b.unit: return False
        if name=='contains_direct': return b.node.parent==a.node.id
        if name=='contains': return a.node.id<b.node.id<a.node.subtree_end
        view=self.view(a.unit)
        if a.unit not in self.bindings:
            symbols=view.rows('symbols')
            occurrences={s.declaration:s.id for s in symbols}
            occurrences.update((r.node,r.symbol) for r in view.rows('references') if r.status=='known' and r.symbol is not None)
            self.bindings[a.unit]=(Environment(view.rows('scopes'),symbols,language=a.language),occurrences)
        environment,occurrences=self.bindings[a.unit]
        left=occurrences.get(a.node.id)
        if left is None: return Unknown('symbol_unresolved')
        if name=='same_symbol':
            right=occurrences.get(b.node.id)
            return left==right if right is not None else Unknown('symbol_unresolved')
        resolution=environment.resolve(environment.symbols[left].name,b.node.scope,b.node.start)
        if resolution.status!='known': return Unknown(resolution.reason)
        if resolution.symbol!=left: return False
        if name=='visible_at': return True
        return resolution.availability=='available' if resolution.availability!='unknown' else Unknown(resolution.reason)
