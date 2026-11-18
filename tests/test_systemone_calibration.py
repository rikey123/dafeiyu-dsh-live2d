import pytest

from scripts.evaluate_systemone import binary_metrics, load_cases, ROOT


def test_calibration_measures_probabilities_not_just_labels():
    perfect = binary_metrics([(0., False), (1., True)])
    uncalibrated = binary_metrics([(.49, False), (.51, True)])
    assert perfect['accuracy_at_half'] == uncalibrated['accuracy_at_half'] == 1
    assert perfect['brier'] == perfect['ece'] == 0
    assert uncalibrated['brier'] == pytest.approx(.2401)
    assert uncalibrated['ece'] == pytest.approx(0)  # Same occupied bin; coarse ECE alone can hide errors.
    assert binary_metrics([])['brier'] is None
    with pytest.raises(ValueError):
        binary_metrics([(float('nan'), True)])


def test_smoke_dataset_is_bounded_and_has_no_implicit_audio():
    cases = load_cases(ROOT / 'scripts/fixtures/systemone-labels.json')
    assert len(cases) == 8 and all(c['_pcm'] is None for c in cases)
