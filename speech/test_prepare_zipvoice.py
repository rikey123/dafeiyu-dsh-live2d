import pytest

from speech.prepare import prepare_zipvoice


def test_existing_incomplete_model_is_not_overwritten(tmp_path):
    target = tmp_path / "zipvoice"
    target.mkdir()
    existing = target / "tokens.txt"
    existing.write_text("user content", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or modified"):
        prepare_zipvoice(target)
    assert existing.read_text(encoding="utf-8") == "user content"
