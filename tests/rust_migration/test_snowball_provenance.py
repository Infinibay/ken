"""The original stem dependency is pinned by bytes, not its version label alone."""
import copy
from tools.rust_migration.snowball_provenance import ORIGINAL_FILES,validate_original

def test_exact_original_stem_sources_are_required():
    value=dict(format='ken-original-snowball/2',distribution='3.0.1',python='3.12.9',files=copy.deepcopy(ORIGINAL_FILES),factory=dict(bytes=2932,sha256='c49181c971ec472ca30d6bb1cfa1ab4507c52a69d6bf7e5d9d587eb313a0e261'))
    assert not validate_original(value)
    for mutation in ['version','python','missing','bytes','digest','factory']:
        changed=copy.deepcopy(value)
        if mutation=='version':changed['distribution']='3.1.0'
        elif mutation=='python':changed['python']='3.13.0'
        elif mutation=='missing':changed['files'].pop('among.py')
        elif mutation=='bytes':changed['files']['basestemmer.py']['bytes']+=1
        elif mutation=='factory':changed['factory']['sha256']='0'*64
        else:changed['files']['english_stemmer.py']['sha256']='0'*64
        assert validate_original(changed),mutation
