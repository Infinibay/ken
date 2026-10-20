"""Protocol framing is independent from numerical acceptance."""
import pytest
from tools.rust_migration.fastembed_process import decode_frames


def test_frames_reject_ambiguous_nonfinite_and_oversized_json():
    assert decode_frames('{"id":"one"}\n{"id":"two"}\n')==[{'id':'one'},{'id':'two'}]
    for raw in ['{"id":"a","id":"b"}\n','{"x":NaN}\n','[]\n','\n','{"x":1}\ntrash\n',' '* (16*1024*1024+1)]:
        with pytest.raises(ValueError):decode_frames(raw)
