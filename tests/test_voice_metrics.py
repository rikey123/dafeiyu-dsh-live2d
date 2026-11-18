from types import SimpleNamespace

import pytest
from pipecat.frames.frames import InterruptionFrame, MetricsFrame, OutputTransportMessageUrgentFrame
from pipecat.metrics.metrics import TTFBMetricsData

from server.pipecat_voice import DuckObserver
from server.voice_metrics import MetricsRegistry, SessionMetrics


def test_metrics_are_bounded_and_report_nearest_rank():
    metrics = SessionMetrics()
    for value in range(100):
        metrics.add("tts.ttfb", value)
    metrics.add("tts.ttfb", float("nan"))
    metrics.add("user text", 12)
    metrics.increment("ack_rejected")
    result = metrics.snapshot()
    assert result["series"] == {"tts.ttfb": {"n": 64, "p50_seconds": 67.0, "p95_seconds": 96.0}}
    assert result["counts"]["ack_rejected"] == 1
    assert result["percentile_method"] == "nearest-rank"


def test_registry_bounds_sessions_and_resets_on_reconnect():
    registry = MetricsRegistry(max_sessions=2)
    old = registry.start("one")
    old.increment("interruptions")
    assert registry.start("one").snapshot()["counts"]["interruptions"] == 0
    registry.start("two")
    registry.start("three")
    assert registry.get("one") is None


def test_screen_decision_history_is_scalar_only_bounded_and_snapshot_is_detached():
    metrics = SessionMetrics()
    for i in range(50):
        metrics.record_screen_decision({'mode': 'proactive', 'status': 'waiting', 'reason': 'low_desire',
            'desire': i / 100, 'must_wait': .01, 'speak_threshold': .8, 'wait_threshold': .2,
            'intent': 'comment', 'intent_confidence': .4, 'non_wait_probability': .99,
            'data': 'private-image', 'user_text': 'private-conversation', 'api_key': 'private-key'})
    result = metrics.snapshot()['screen']
    assert result['sample_limit'] == len(result['decisions']) == 32
    assert result['decisions'][0]['desire'] == .18
    assert 'private-' not in str(result)
    result['decisions'][0]['desire'] = 0
    assert metrics.snapshot()['screen']['decisions'][0]['desire'] == .18
    for event in (None, {'mode': 'requested', 'desire': .9, 'must_wait': .1},
                  {'mode': 'proactive', 'desire': True, 'must_wait': .1},
                  {'mode': 'proactive', 'desire': float('nan'), 'must_wait': .1}):
        metrics.record_screen_decision(event)
    assert len(metrics.snapshot()['screen']['decisions']) == 32


@pytest.mark.asyncio
async def test_observer_records_framework_events_without_content():
    metrics = SessionMetrics()
    observer = DuckObserver(metrics)
    await observer.on_push_frame(SimpleNamespace(frame=MetricsFrame(data=[TTFBMetricsData(processor="LocalSpeechTTS#0", value=.25)])))
    await observer.on_push_frame(SimpleNamespace(frame=InterruptionFrame()))
    await observer.on_push_frame(SimpleNamespace(frame=OutputTransportMessageUrgentFrame(message={"data": {"type": "voice.speaker", "accepted": False, "text": "private"}})))
    result = metrics.snapshot()
    assert result["series"]["tts.ttfb"]["n"] == 1
    assert result["counts"]["interruptions"] == result["counts"]["speaker_rejections"] == 1
    assert "private" not in str(result)
