"""Accumulated Builder construction must receive the collected state."""
import pytest
from .test_gof_executable import evaluate

@pytest.mark.parametrize('language',['python','typescript'])
@pytest.mark.parametrize('variant',['identity','copy','noise','unrelated','discarded','other_return','shadowed','read_only'])
def test_accumulated_builder_keeps_collection_origin(language,variant):
 if language=='python':
  value='self.steps' if variant=='identity' else 'list(self.steps)'
  if variant=='unrelated':value='list(other)'
  prefix='def list(value):\n return []\n' if variant=='shadowed' else ''
  body=f'  result=Product({value})\n'
  if variant=='read_only':body='  print(self.steps)\n  result=Product([])\n'
  if variant=='noise':body+='  print(123)\n'
  if variant in ('discarded','other_return'):body+='  result=Product([])\n'
  source=prefix+'class Product:\n def __init__(self,steps): self.steps=steps\nclass Builder:\n def __init__(self): self.steps=[]\n def add(self,item): self.steps.append(item)\n def build(self):\n'+body+'  return result\n'
 else:
  value='this.steps' if variant=='identity' else '[...this.steps]'
  if variant=='unrelated':value='[...other]'
  if variant=='shadowed':value='copy(this.steps)'
  body=f'let result=new Product({value});'
  if variant=='read_only':body='console.log(this.steps); let result=new Product([]);'
  if variant=='noise':body+='console.log(123);'
  if variant in ('discarded','other_return'):body+='result=new Product([]);'
  source='function copy(x:number[]):number[]{return [];} class Product {constructor(public steps:number[]) {}} class Builder { steps:number[]=[]; add(item:number){this.steps.push(item);} build(){'+body+'return result;} }'
 assert bool(evaluate(source,language,'builder#accumulated-state')) is (variant in ('identity','copy','noise'))
