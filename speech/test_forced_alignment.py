from types import SimpleNamespace

import pytest

from speech.forced_alignment import validate_items


def test_alignment_keeps_true_character_intervals():
    items = [SimpleNamespace(text="你", start_time=0.12, end_time=0.29), SimpleNamespace(text="好", start_time=0.36, end_time=0.59)]
    assert validate_items(items, 1.0) == [{"text": "你", "start_s": 0.12, "end_s": 0.29}, {"text": "好", "start_s": 0.36, "end_s": 0.59}]


@pytest.mark.parametrize("start,end", [(0.5, 0.1), (-0.1, 0.2), (0, 3), (float("nan"), 0.2)])
def test_alignment_rejects_invalid_model_output(start, end):
    with pytest.raises(ValueError):
        validate_items([SimpleNamespace(text="你", start_time=start, end_time=end)], 1.0)
