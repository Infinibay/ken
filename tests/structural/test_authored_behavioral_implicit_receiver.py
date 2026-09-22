"""Bare member calls imply this only when resolved as non-static members."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project

@pytest.mark.parametrize('language',['java','csharp','cpp'])
@pytest.mark.parametrize('mode',['instance','static_target','static_caller','local_callable'])
def test_bare_member_receiver_preserves_language_semantics(language,mode):
 static_target='static ' if mode=='static_target' else ''
 static_caller='static ' if mode=='static_caller' else ''
 parameter=''
 if mode=='local_callable':
  parameter='System.Action hook' if language=='csharp' else 'void (*hook)()' if language=='cpp' else 'Runnable hook'
 call='hook.run()' if mode=='local_callable' and language=='java' else 'hook()'
 source='class Base { public: '+static_target+'void hook(){} '+static_caller+'void run('+parameter+'){'+call+';} };' if language=='cpp' else 'class Base {'+static_target+'void hook(){} '+static_caller+'void run('+parameter+'){'+call+';} }'
 graph=link_project([lower_source(source,language,'sample.'+language)])
 synthetic=[f for f in graph.facts if f.relation=='RECEIVER' and f.attrs.get('basis')=='resolved-implicit-instance-member']
 assert bool(synthetic) is (mode=='instance')
 if synthetic:assert synthetic[0].object.endswith('/CLASS:Base/THIS')


def test_cpp_free_function_called_from_method_is_not_this():
 source='void helper(){} class Base { public: void run(){helper();} };'
 graph=link_project([lower_source(source,'cpp','sample.cpp')])
 assert not [f for f in graph.facts if f.relation=='RECEIVER' and f.attrs.get('basis')=='resolved-implicit-instance-member']
