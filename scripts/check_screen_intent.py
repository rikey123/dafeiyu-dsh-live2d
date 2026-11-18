"""Explicit opt-in, bounded live text intent checks. Never captures a desktop.

Uses the owner's independently configured System One key, not DSH credentials.
No settings writes, model generation, TTS or retry. The default is offline/no-op.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.storage import DEFAULTS
from server.systemone import SystemOneClient


async def run():
    import sqlite3
    database = sqlite3.connect((ROOT / 'data/companion.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    keys = ['systemone_provider', 'systemone_ark_model', 'systemone_ark_api_key', 'systemone_api_key',
        'systemone_timeout_ms', 'screen_request_threshold']
    rows = database.execute('SELECT key,value FROM settings WHERE key IN (' + ','.join('?' for _ in keys) + ')', keys).fetchall()
    database.close()
    settings = {**DEFAULTS, **{key: json.loads(value) for key, value in rows}}
    cases = [
        ('current_screen_question', '你现在能看到我的屏幕吗？上面这个窗口写了什么？', True),
        ('visible_error_request', '帮我看看这个报错，屏幕上红色那一行什么意思？', True),
        ('hardware_not_screen_access', '显示器应该买27寸还是32寸？', False),
        ('explicit_refusal', '不要看我的屏幕，先聊点别的。', False),
    ]
    client = SystemOneClient(settings)
    report = {'method': 'live System One; four fixed synthetic text cases; no desktop, DSH generation or TTS',
        'provider': client.provider.name, 'model': client.model, 'threshold': settings['screen_request_threshold'], 'cases': []}
    try:
        for name, text, expected in cases:
            started = time.monotonic()
            probability = await client.screen_request(text, [])
            observed = probability is not None and probability >= settings['screen_request_threshold']
            report['cases'].append({'name': name, 'expected': expected, 'probability': probability,
                'passed': probability is not None and observed == expected, 'reason': client.last_reason,
                'elapsed_ms': round((time.monotonic() - started) * 1000)})
    finally: await client.close()
    out = ROOT / '.runtime/dsh-acceptance/screen-intent-live.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if not all(case['passed'] for case in report['cases']): raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Make exactly four paid fixed-text System One requests')
    args = parser.parse_args()
    if args.live: asyncio.run(run())
    else: print('Not run: --live explicitly enables four fixed-text System One requests; no screen or TTS.')
