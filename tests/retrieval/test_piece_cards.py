import pytest
from ken.retrieval.model import CodeMatch
from tests.retrieval.test_piece_catalog import source_owners


def test_source_cards_group_native_owners_at_requested_piece_kind(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_cards import build_piece_cards
    root,owners,k=source_owners;catalog=SourceCatalog(root,owners)
    keys=[k['Outer.Inner.run'],k['Outer.read'],k['helper']]
    matches=[CodeMatch(key,3-i,list(owners[key]),owners[key][0].source_hash) for i,key in enumerate(keys)]
    classes=build_piece_cards(matches,'class','read values',catalog)
    assert [c['unit']['entity']['qualname'] for c in classes]==['Outer.Inner','Outer']
    files=build_piece_cards(matches,'file','read values',catalog)
    assert [c['unit']['path'] for c in files]==['src/pkg/engine.py']
    assert files[0]['unit']['entity'] is None


def test_neural_input_projection_preserves_measured_roles_and_source_lines(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_cards import build_piece_cards,card_text,validate_card
    root,owners,k=source_owners;key=k['helper'];catalog=SourceCatalog(root,owners)
    card=build_piece_cards([CodeMatch(key,1.,list(owners[key]),owners[key][0].source_hash)],'symbol','helper',catalog)[0]
    assert card_text(card)=='symbol src/pkg/engine.py helper\ndeclaration helper lines 8-9:\ndef helper():\n    return 2'
    validate_card(card,catalog)
    card['excerpts'][0]['content']='fabricated'
    with pytest.raises(ValueError,match='fabricated'):
        validate_card(card,catalog)


def test_card_validation_rejects_a_source_change_after_catalog_creation(source_owners):
    from ken.retrieval.piece_catalog import SourceCatalog
    from ken.retrieval.piece_cards import build_piece_cards,validate_card
    root,owners,k=source_owners;key=k['helper'];catalog=SourceCatalog(root,owners)
    card=build_piece_cards([CodeMatch(key,1.,list(owners[key]),owners[key][0].source_hash)],'symbol','helper',catalog)[0]
    (root/key.path).write_text('changed\n')
    with pytest.raises(ValueError,match='changed'):
        validate_card(card,catalog)
