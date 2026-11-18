"""Bounded in-memory, content-free voice diagnostics."""

from collections import OrderedDict, deque
import math
import re
import threading


class SessionMetrics:
    def __init__(self):
        self.lock = threading.RLock()
        self.series = {}
        self.screen_decisions = deque(maxlen=32)
        self.counts = {"interruptions": 0, "speaker_rejections": 0, "ack_rejected": 0, "playback_completed": 0,
                       "systemone_requests": 0, "systemone_success": 0, "systemone_fallback": 0,
                       "systemone_initiative_probes": 0, "systemone_initiative_accepted": 0,
                       "systemone_initiative_wait": 0, "systemone_initiative_unavailable": 0,
                       "systemone_initiative_stale": 0,
                       **{f"screen_{name}": 0 for name in ("frames", "busy", "probes", "replies", "wait", "unavailable",
                                                          "low_desire", "must_wait", "wait_intent", "low_confidence")}}

    def add(self, name, value):
        if name not in {f"{stage}.{kind}" for stage in ("stt", "llm", "tts", "playback", "systemone") for kind in ("ttfb", "processing", "completion")}:
            return
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            return
        with self.lock:
            self.series.setdefault(name, deque(maxlen=64)).append(float(value))

    def increment(self, name):
        with self.lock:
            if name in self.counts:
                self.counts[name] += 1

    def record_screen_decision(self, event):
        """Retain only bounded scalar decisions, never screenshots or dialogue."""
        if not isinstance(event, dict) or event.get('mode') != 'proactive':
            return
        sample = {'mode': 'proactive'}
        if event.get('style') in {'quiet', 'balanced', 'lively'}:
            sample['style'] = event['style']
        for key in ('status', 'reason'):
            value = event.get(key)
            if isinstance(value, str) and re.fullmatch(r'[a-z_]{1,80}', value):
                sample[key] = value
        for key in ('desire', 'must_wait', 'speak_threshold', 'wait_threshold', 'intent_confidence_threshold',
                    'intent_confidence', 'intent_probability', 'non_wait_probability'):
            value = event.get(key)
            if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1:
                sample[key] = float(value)
        if 'desire' not in sample or 'must_wait' not in sample:
            return
        if event.get('intent') in {'wait', 'comment', 'cheer', 'warn', 'empathize'}:
            sample['intent'] = event['intent']
        elif event.get('intent') is None:
            sample['intent'] = None
        with self.lock:
            self.screen_decisions.append(sample)

    def snapshot(self):
        with self.lock:
            result = {}
            for name, values in self.series.items():
                ordered = sorted(values)
                result[name] = {"n": len(ordered), "p50_seconds": ordered[math.ceil(.50 * len(ordered)) - 1],
                                "p95_seconds": ordered[math.ceil(.95 * len(ordered)) - 1]}
            return {"sample_limit": 64, "percentile_method": "nearest-rank", "series": result, "counts": dict(self.counts),
                    "screen": {"sample_limit": 32, "decisions": [dict(item) for item in self.screen_decisions]}}


class MetricsRegistry:
    def __init__(self, max_sessions=100):
        self.lock = threading.RLock()
        self.sessions = OrderedDict()
        self.max_sessions = max_sessions

    def start(self, session_id):
        with self.lock:
            self.sessions.pop(session_id, None)
            item = SessionMetrics()
            self.sessions[session_id] = item
            while len(self.sessions) > self.max_sessions:
                self.sessions.popitem(last=False)
            return item

    def get(self, session_id):
        with self.lock:
            return self.sessions.get(session_id)


registry = MetricsRegistry()
